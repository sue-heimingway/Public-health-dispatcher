"""Agent ④：交叉核验质控 —— 防"误判"与"次生舆情"。

平移自急诊版：急诊质控防"漏诊、给错级"，这里防两件事：
  1. 误判：把该转 120 的判成自动回复，或把普通咨询拔高成二级；
  2. 次生舆情：对极其恐慌/愤怒的市民，回一句"请耐心等待"就是引爆点。

安全底线：任何 tier0 风险都不允许高于一级；任何 tier1 风险都不允许高于二级。
"""
from __future__ import annotations

from typing import Any

CRITICAL = "critical"
MAJOR = "major"
MINOR = "minor"


def safety_floor(ctx: dict[str, Any], screening: dict[str, Any]) -> tuple[int, list[str]]:
    reasons: list[str] = []
    floor = 4
    hard = screening["hard_risks"]
    if any(r["tier"] == 0 for r in hard):
        floor = 1
        reasons.append("触发生命/安全级风险，底线一级")
    elif any(r["tier"] == 1 for r in hard):
        floor = 2
        reasons.append("触发舆情/群体级风险，底线二级")
    # 情绪强烈时，宁可让真人温和回应，也不能把底线留在自动答复
    if (ctx["emotions"] & {"panic", "angry", "despair"}) and floor > 2:
        floor = 2
        reasons.append("情绪强烈，底线不高于二级（避免机械冷回复）")
    return floor, reasons


def verify(ctx: dict[str, Any], screening: dict[str, Any], judgment: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, str]] = []
    judge = judgment["level"]
    floor, floor_reasons = safety_floor(ctx, screening)
    hard = screening["hard_risks"]
    strong_emotion = bool(ctx["emotions"] & {"panic", "angry", "despair"})

    # ---- 1. 生命/安全风险漏判 ----
    if any(r["tier"] == 0 for r in hard) and judge > 1:
        checks.append({"id": "missed_danger", "level": CRITICAL, "name": "危险诉求漏判",
                       "detail": f"已触发「{hard[0]['name']}」等生命/安全风险，却判为 {judge} 级"})
    # ---- 2. 舆情/群体风险漏判 ----
    if any(r["tier"] == 1 for r in hard) and judge > 2:
        checks.append({"id": "missed_opinion", "level": CRITICAL, "name": "舆情风险漏判",
                       "detail": f"已触发「{hard[0]['name']}」，却判为 {judge} 级"})
    # ---- 3. 恐慌诉求被机械冷回复 ----
    if strong_emotion and judge == 4:
        checks.append({"id": "panic_cold_reply", "level": CRITICAL, "name": "恐慌诉求配冷回复",
                       "detail": "市民情绪强烈却被判自动答复（极易触发机械回复「请耐心等待」），应改温和人工回应"})
    # ---- 4. 一二级缺地址 ----
    if judge <= 2 and not ctx.get("has_location"):
        checks.append({"id": "location_gap", "level": CRITICAL, "name": "缺具体地址",
                       "detail": f"{judge} 级响应必须有确切点位，否则无法到场处置"})
    # ---- 5. 缺联系方式 ----
    if judge <= 2 and not ctx.get("has_phone"):
        checks.append({"id": "phone_gap", "level": MAJOR, "name": "缺联系电话",
                       "detail": "高风险诉求应留联系电话以便回访核实"})
    # ---- 6. 群体类缺人数 ----
    if any(r["id"] == "mass_incident" for r in hard) and not ctx.get("crowd"):
        checks.append({"id": "crowd_gap", "level": MINOR, "name": "人数未明确",
                       "detail": "群体性苗头应尽快核实涉及人数"})
    # ---- 7. 过度响应 ----
    if judge == 2 and not hard and not strong_emotion:
        checks.append({"id": "over_response", "level": MAJOR, "name": "疑似过度响应",
                       "detail": "无高危风险、无强烈情绪，却判为二级，会挤占快速响应资源"})

    critical = [c for c in checks if c["level"] == CRITICAL]
    major = [c for c in checks if c["level"] == MAJOR]
    minor = [c for c in checks if c["level"] == MINOR]
    level_checks = {"missed_danger", "missed_opinion", "panic_cold_reply"}
    data_gaps = [c for c in critical if c["id"] not in level_checks]
    level_conflicts = [c for c in critical if c["id"] in level_checks] + major
    final = min(judge, floor) if floor < judge else judge

    if level_conflicts:
        raise_level = any(c["id"] in ("missed_danger", "missed_opinion") for c in critical) or judge > floor
        verdict = "建议升级" if raise_level else "建议复核"
        conflict = True
    elif judge > floor:
        verdict, conflict = "建议升级", True
    elif data_gaps:
        verdict, conflict = "带条件放行", False
    else:
        verdict, conflict = "通过", False

    if conflict:
        headline = f"质控不通过：{verdict}（裁判 {judge} 级 → 建议 {final} 级）"
    elif data_gaps:
        headline = f"质控有条件通过：{verdict}（{'；'.join(c['name'] for c in data_gaps)}）"
    else:
        headline = f"质控通过：裁判 {judge} 级未被推翻（安全底线 {floor} 级）"

    return {
        "verdict": verdict, "conflict": conflict, "judge_level": judge,
        "floor": floor, "floor_reasons": floor_reasons, "final_level": min(final, 4),
        "checks": checks, "critical": critical, "major": major, "minor": minor,
        "data_critical": data_gaps, "headline": headline,
        "jury": [
            {"role": "分级裁判 Agent ③", "level": judge, "color": "#334155",
             "argument": judgment.get("summary", "")},
            {"role": "交叉核验 Agent ④", "level": final, "color": "#b91c1c",
             "argument": verdict + "：" + ("；".join(c["detail"] for c in (level_conflicts or data_gaps)) or "未发现冲突")},
        ],
    }
