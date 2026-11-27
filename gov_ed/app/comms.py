"""Agent ⑥：政务通报与情绪安抚生成器 —— 平移自急诊版"医患沟通安抚"。

急诊给暴躁家属解释"为什么先救别人"，这里给恐慌/愤怒/绝望的市民
生成"有原则、有人情味、可一键推送"的通报。三种语气版本 + 措辞禁忌。

三条铁律（任何版本都不许破）：
  - 不承诺"立即解决"（做不到就是二次失信）；
  - 不点名、不泄露举报人与涉事隐私；
  - 不推诿、不煽动、不传播未经核实的信息。
"""
from __future__ import annotations

from typing import Any

TONE_CUES = {
    "angry": ["投诉", "举报", "气死", "混蛋", "不作为", "糊弄", "凭什么", "坑人", "太过分", "讨说法"],
    "panic": ["害怕", "恐慌", "吓死", "怎么办", "慌", "会不会", "人心惶惶", "天塌了"],
    "despair": ["活不下去", "绝望", "轻生", "不想活", "没希望", "走投无路"],
    "urgent": ["救命", "急", "快点", "立刻", "马上", "等不及"],
}


def detect_tone(text: str) -> str:
    text = (text or "").strip()
    for tone in ("angry", "panic", "despair", "urgent"):
        if any(cue in text for cue in TONE_CUES[tone]):
            return tone
    return "neutral"


def _level_head(level: int) -> str:
    return {
        1: "你的诉求属于一级响应，我们已同步 120/110/119 与属地，正在派人赶往现场。",
        2: "你的诉求涉及需要快速核实的事项，我们已转交相关专班，正在加急处理。",
        3: "你的诉求已派发到责任部门，将按规定时限办理。",
        4: "你咨询的事项属于一般政策问题，现答复如下。",
    }[level]


def _level_tail(level: int) -> str:
    if level == 1:
        return "请在确保自身安全的前提下保持电话畅通，先执行急救员电话里的指导；属地工作人员会尽快与你联系。"
    if level == 2:
        return "在核实期间，请以官方渠道发布的信息为准，不要转发未经核实的消息；如有新情况，可随时通过本通道补充。"
    if level == 3:
        return "办理期间可在本通道查询进度；如情况发生变化（更紧急、多人同样遭遇），请立即反馈，我们会重新评估。"
    return "如对答复仍有疑问，可回复「转人工」，我们会安排工作人员跟进。"


def reply(case: dict[str, Any], level: int, tone: str | None = None,
          message: str = "") -> dict[str, Any]:
    tone = tone or detect_tone(message or case.get("text") or "")
    head = _level_head(level)
    tail = _level_tail(level)

    variants = [
        {"tone": "neutral", "label": "常规版｜标准通报", "text": f"{head}{tail}"},
        {"tone": "panic", "label": "恐慌版｜先稳情绪",
         "text": f"别慌，你的情况我们已经看到了，值班人员正在处理，不会没人管。{head}{tail}"},
        {"tone": "angry", "label": "愤怒版｜先接住情绪",
         "text": (f"你的心情我们能理解，这件事确实让人着急。我们不解释立场，先把处理安排说清楚："
                  f"{head}{tail}")},
        {"tone": "despair", "label": "绝望版｜先给支点",
         "text": (f"请你先别放弃，现在已经有专人接手你这件事。{head}{tail}"
                  f"如果你此刻有轻生念头，请立刻拨打心理援助热线或让身边的人陪你，我们也会尽快与你联系。")},
    ]
    primary = next((v["text"] for v in variants if v["tone"] == tone), variants[0]["text"])

    return {
        "tone": tone,
        "primary": primary,
        "variants": variants,
        "taboos": ["不承诺「立即解决」「马上办结」——做不到就是二次失信",
                   "不点名、不透露举报人信息与涉事人员隐私",
                   "不推诿「这不归我们管」，一律先接单再分流转办",
                   "不传播未经核实的信息，不评价其他部门与执法过程"],
        "next": "每 30 分钟通报一次进展；超过时限未办结，主动给一个确切时间点",
    }
