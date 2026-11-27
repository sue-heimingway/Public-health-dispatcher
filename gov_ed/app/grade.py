"""Agent ③：政务响应分级 —— 平移自急诊版 ESI。

四级响应，对应政务处置的四条通道：

    一级（红色）：危及生命/安全 → 转 120/110/119 + 属地立即到场
    二级（橙色）：恐慌/舆情/群体苗头 → 转 宣传部/网信办/政法
    三级（黄色）：具体诉求 → 派发责任部门工单，限时办理
    四级（蓝色）：政策咨询/一般 → 自动答复闭环

安全原则同急诊版：Agent 只自动升级、不自动降级；降级必须由人决定。
"""
from __future__ import annotations

from typing import Any

from . import config


def evaluate(ctx: dict[str, Any], screening: dict[str, Any]) -> dict[str, Any]:
    hard = screening["hard_risks"]
    reasons: list[dict[str, str]] = []
    level = 4

    # ---------------- 第 1 步：危及生命/安全 → 一级 ----------------
    tier0 = [r for r in hard if r["tier"] == 0]
    if tier0:
        level = 1
        for r in tier0:
            reasons.append({"k": "一级（生命/安全）", "v": f"{r['name']}（置信度 {r['confidence']}）"})
        return _result(1, "step1", reasons, ctx)

    # ---------------- 第 2 步：舆情/恐慌/群体 → 二级 ----------------
    tier1 = [r for r in hard if r["tier"] == 1]
    if tier1:
        level = 2
        for r in tier1:
            reasons.append({"k": "二级（舆情/群体）", "v": f"{r['name']}（置信度 {r['confidence']}）"})
        return _result(2, "step2", reasons, ctx)

    # ---------------- 第 3 步：具体诉求 → 三级；咨询 → 四级 ----------------
    cats = {f["cat"] for f in ctx["findings"]}
    if "咨询" in cats and not (cats & {"求助", "投诉", "风险"}):
        level = 4
        reasons.append({"k": "四级（政策咨询）", "v": "一般咨询，可自动答复闭环"})
    elif cats:
        level = 3
        kinds = "、".join(sorted({f["name"] for f in ctx["findings"]}))
        reasons.append({"k": "三级（具体诉求）", "v": f"识别诉求：{kinds}，派发责任部门工单"})
    else:
        level = 3
        reasons.append({"k": "三级（人工研判）", "v": "未能明确识别诉求类型，转人工研判"})

    return _result(level, "step3", reasons, ctx)


def _result(level: int, path: str, reasons: list[dict[str, str]], ctx: dict[str, Any]) -> dict[str, Any]:
    confidence = 0.9 if path in ("step1", "step2") else 0.72
    return {
        "level": level,
        "label": config.LEVEL_LABEL[level],
        "color": config.LEVEL_COLOR[level],
        "route": config.LEVEL_ROUTE[level],
        "sla_minutes": config.LEVEL_SLA[level],
        "path": path,
        "reasons": reasons,
        "confidence": confidence,
        "summary": f"{config.LEVEL_LABEL[level]} · {config.LEVEL_ROUTE[level]}",
    }
