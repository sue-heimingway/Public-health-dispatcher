"""LLM 混合层：大模型负责"理解与表达"，规则负责"分级与兜底"。

架构定位（对齐"词元工厂"大模型主题）：

    大模型  ── 诉求抽取 / 情绪识别 / 通报话术生成（语义理解、表达）
    规则引擎 ── 四级响应分级 / 社会风险排雷 / 质控安全底线（可解释、可复现、不漏报）
    人在环  ── 最终裁决（高危 / 分歧 / 舆情升级）

无 API Key、断网、超时、返回非法 JSON 时，一律**静默降级为纯规则**，主流程永不中断。
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from typing import Any

from . import config, lexicon as LEX

_TYPE_IDS = {t["id"]: t["name"] for t in LEX.APPEAL_TYPES}
_NAME_TO_ID = {t["name"]: t["id"] for t in LEX.APPEAL_TYPES}
_EMOTION_IDS = {e["id"] for e in LEX.EMOTIONS}


# ---------------------------------------------------------------- 基础调用
def _key() -> str:
    return (os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
            or config.LLM_API_KEY or "")


def _enabled() -> bool:
    return os.environ.get("LLM_ENABLED", "1") not in ("0", "false", "False")


def available() -> bool:
    return bool(_key()) and _enabled()


def chat(messages: list[dict[str, str]], temperature: float = 0.2,
         timeout: int = 15, max_tokens: int = 800) -> str:
    """OpenAI 兼容调用（DeepSeek / GLM / 任意兼容端点）。"""
    key = _key()
    if not key:
        raise RuntimeError("未配置大模型 API Key")
    url = config.LLM_BASE_URL.rstrip("/") + "/chat/completions"
    payload = {
        "model": config.LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as res:
        data = json.loads(res.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip()


def _parse_json(raw: str) -> dict[str, Any] | None:
    """宽容解析：容忍 markdown 代码块、首尾多余文字、单引号。"""
    if not raw:
        return None
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        try:
            # 兜底：把单引号换成双引号再试一次
            return json.loads(text[start:end + 1].replace("'", '"'))
        except json.JSONDecodeError:
            return None


# ---------------------------------------------------------------- 诉求抽取
def extract_appeal(text: str) -> dict[str, Any] | None:
    """大模型把市民白话抽取成结构化诉求标签。失败返回 None。"""
    type_list = "、".join(f"{i}:{n}" for i, n in _TYPE_IDS.items())
    system = (
        "你是政务诉求「精译官」，负责把市民口语化的诉求文本翻译成结构化标签。\n"
        "严格要求：只输出一个 JSON 对象，不要输出任何解释、代码块标记或多余文字。字段如下：\n"
        '{"types": ["诉求类型id数组，只能从下面列表选，可空"], '
        '"emotions": ["情绪id数组，只能从 panic/angry/despair/urgent 选，可空"], '
        '"location": "地址字符串，没有则为空字符串", '
        '"crowd": 涉及人数的整数，没有则 0, '
        '"urgent": true或false, '
        '"summary": "一句话标准摘要，40字内"}\n\n'
        f"诉求类型可选列表：{type_list}\n"
        "注意：id 必须原样使用上述列表里的英文字符串。"
    )
    raw = chat([{"role": "system", "content": system},
                {"role": "user", "content": f"市民诉求原文：{text}"}], temperature=0.1)
    return _parse_json(raw)


def merge_extraction(ctx: dict[str, Any], result: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
    """把大模型抽取结果并入规则上下文（规则结果与 LLM 结果取并集，安全方向）。"""
    if not result or not isinstance(result, dict):
        return ctx, False
    changed = False
    for t in (result.get("types") or []):
        tid = t if t in _TYPE_IDS else _NAME_TO_ID.get(t)
        if tid and tid not in ctx["terms"]:
            ctx["terms"].add(tid)
            changed = True
    for e in (result.get("emotions") or []):
        if e in _EMOTION_IDS and e not in ctx["emotions"]:
            ctx["emotions"].add(e)
            changed = True
    crowd = result.get("crowd")
    if isinstance(crowd, (int, float)) and int(crowd) > ctx.get("crowd", 0):
        ctx["crowd"] = int(crowd)
        changed = True
    loc = (result.get("location") or "").strip()
    if loc and not ctx.get("has_location"):
        ctx["location"] = loc[:50]
        ctx["has_location"] = True
        changed = True
    summary = (result.get("summary") or "").strip()
    if summary:
        ctx["summary"] = summary[:60]
        changed = True
    return ctx, changed


# ---------------------------------------------------------------- 通报生成
def compose_reply(case: dict[str, Any], level: int, tone: str) -> str | None:
    """大模型生成政务安抚通报。失败返回 None（降级为模板）。"""
    from . import comms  # 复用话术知识

    base = comms.reply(case, level, tone)
    system = (
        "你是政务「安抚通报官」，为市民诉求写一段官方、有人情味、又不失原则的回复。\n"
        "硬性红线：不承诺「立即解决」；不推诿「这不归我们管」；不点名、不泄露举报人与涉事隐私；"
        "不传播未经核实的信息；语气温和、克制。\n"
        f"该诉求被定为 {level} 级响应，处置通道是：{base.get('variants', [{}])[0].get('text', '')[:80]}\n"
        f"市民情绪为：{tone}。\n"
        "要求：只输出回复正文，120~200 字，不要任何前缀、编号或说明。"
    )
    raw = chat([{"role": "system", "content": system},
                {"role": "user", "content": f"市民诉求原文：{case.get('text', '')}\n地点：{case.get('location', '')}"}],
               temperature=0.4)
    return raw[:300] if raw else None
