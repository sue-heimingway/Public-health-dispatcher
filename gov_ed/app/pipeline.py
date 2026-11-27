"""六个 Agent 的编排层（政务版）。

流水线（每个 Agent 的产出都留痕、可回溯）：

  ① 诉求采集     → 口语变诉求类型、抓地址/人数/情绪、缺口清单
  ② 社会风险排雷 → 高危风险预警 + 补问清单 + 已排查清单
  ③ 响应分级     → 政务四级响应 + 处置通道
  ④ 交叉核验     → 安全底线 vs 裁判级别 + 次生舆情拦截
  ⑤ 舆情热点追踪 → 跟帖/多人同诉 → 自动重新评估并升级
  ⑥ 通报与安抚   → 三级语气 + 措辞禁忌

安全原则：Agent 只自动升级、不自动降级。
"""
from __future__ import annotations

import time
from typing import Any

from . import comms, grade, lexicon as L, llm, qc, risks as R
from .store import Store

RECHECK_MINUTES = {1: 5, 2: 10, 3: 30, 4: 120}


def _card(no: int, key: str, name: str, role: str, status: str,
          headline: str, points: list[str], extra: dict[str, Any] | None = None,
          confidence: float = 0.9, elapsed_ms: float = 0.0, engine: str = "rules") -> dict[str, Any]:
    return {
        "no": no, "key": key, "name": name, "role": role, "status": status,
        "headline": headline, "points": points, "extra": extra or {},
        "confidence": round(confidence, 2), "elapsed_ms": round(elapsed_ms, 2),
        "engine": engine,  # "llm" = 大模型增强，其余为纯规则
    }


def ctx_from_case(case: dict[str, Any]) -> dict[str, Any]:
    sc = case["ctx"]
    return {
        "name": case["name"], "phone": case.get("phone", ""),
        "location": case.get("location", ""), "source": case.get("source", ""),
        "crowd": sc.get("crowd") or 0,
        "text": case.get("text", ""),
        "terms": set(sc.get("terms") or []),
        "emotions": set(sc.get("emotions") or []),
        "findings": list(sc.get("findings") or []),
        "translation": list(sc.get("translation") or []),
        "emotion_list": [],
        "location_bits": list(sc.get("location_bits") or []),
        "has_location": bool(case.get("location") and case["location"] != "未明确"),
        "has_phone": bool(case.get("phone")),
        "summary": sc.get("summary", ""),
    }


# ======================================================================
# Agent ① 诉求采集
# ======================================================================
def agent_intake(ctx: dict[str, Any], payload: dict[str, Any],
                 engine: str = "rules") -> dict[str, Any]:
    t0 = time.perf_counter()
    translation = ctx["translation"]
    emotions = ctx["emotion_list"]
    bits = ctx["location_bits"]
    missing: list[str] = []
    if not ctx["has_location"]:
        missing.append("地址")
    if not ctx["has_phone"]:
        missing.append("联系电话")

    points: list[str] = []
    for pair in translation[:5]:
        points.append(f"「{pair['lay']}」 → {pair['term']}")
    if ctx.get("summary"):
        points.append(f"一句话摘要：{ctx['summary']}")
    if emotions:
        points.append("情绪识别：" + "、".join(e["name"] for e in emotions))
    if bits:
        points.append("自动抓取地址：" + "、".join(bits[:4]))
    if ctx["crowd"]:
        points.append(f"涉及人数：约 {ctx['crowd']} 人")
    if missing:
        points.append("待补：" + "、".join(missing))
    if not points:
        points.append("诉求信息不足，已生成补问清单")

    status = "warn" if missing else "done"
    head = (f"把市民口语规范为 {len(translation)} 个诉求类型" +
            (f"，抓取地址 {len(bits)} 处" if bits else "") +
            ("（大模型增强）" if engine == "llm" else ""))
    return _card(
        1, "intake", "诉求采集与地址识别", "极其敏锐的接线员", status, head, points,
        {"translation": translation, "emotions": emotions, "location_bits": bits,
         "crowd": ctx["crowd"], "missing": missing, "summary": ctx.get("summary", "")},
        confidence=0.94 if translation else 0.6,
        elapsed_ms=(time.perf_counter() - t0) * 1000, engine=engine,
    )


# ======================================================================
# Agent ② 社会风险预警
# ======================================================================
def agent_risk(ctx: dict[str, Any], screening: dict[str, Any]) -> dict[str, Any]:
    t0 = time.perf_counter()
    risks = screening["risks"]
    points = []
    for r in risks[:4]:
        points.append(f"{r['name']}（置信度 {r['confidence']}）：" + "、".join(r["hits"][:4]))
    for p in screening["partial"][:2]:
        points.append(f"证据缺口：{p['name']} 还缺 " + "、".join(p["missing"]))
    if not risks:
        points.append(f"已排查 {screening['screened']} 类社会风险，均未触发")

    status = "critical" if screening["hard_risks"] and screening["max_tier"] == 0 else \
        ("warn" if screening["hard_risks"] else "done")
    return _card(
        2, "risk", "社会风险预警", "极其敏锐的风险研判员", status, screening["headline"], points,
        {"risks": risks, "partial": screening["partial"], "cleared": screening["cleared"],
         "screened": screening["screened"], "ask": [a for r in risks[:2] for a in r["ask"]][:6]},
        confidence=max((r["confidence"] for r in risks), default=0.9),
        elapsed_ms=(time.perf_counter() - t0) * 1000,
    )


# ======================================================================
# Agent ③ 响应分级
# ======================================================================
def agent_grade(judgment: dict[str, Any]) -> dict[str, Any]:
    points = [f"{r['k']}｜{r['v']}" for r in judgment["reasons"][:5]]
    return _card(
        3, "grade", "响应分级", "极其冷静的调度台长",
        "critical" if judgment["level"] == 1 else "done",
        judgment["summary"], points, {"judgment": judgment},
        confidence=judgment["confidence"],
    )


# ======================================================================
# Agent ④ 交叉核验质控
# ======================================================================
def agent_qc(result: dict[str, Any]) -> dict[str, Any]:
    points = [f"[{c['level']}] {c['name']}：{c['detail']}" for c in result["checks"][:5]]
    if not points:
        points = ["未发现误判、次生舆情风险或数据缺口"]
    points.append(f"安全底线：{result['floor']} 级" +
                  (f"（{'；'.join(result['floor_reasons'])}）" if result["floor_reasons"] else ""))
    return _card(
        4, "qc", "交叉核验质控", "极其严苛的舆情守门员",
        "critical" if result["critical"] else ("warn" if result["conflict"] else "done"),
        result["headline"], points, {"qc": result}, confidence=0.88,
    )


# ======================================================================
# Agent ⑤ 舆情热点追踪
# ======================================================================
def agent_watch(case: dict[str, Any], store: Store, level: int) -> dict[str, Any]:
    interval = RECHECK_MINUTES.get(level, 30)
    snapshot = store.queue_snapshot(case)
    pos = store.position(case)
    points = [
        f"热点追踪：每 {interval} 分钟复核一次热度变化",
        f"当前处置队列位次：第 {pos} 位",
        "触发条件：多人跟帖「我们也这样」/ 情况更紧急 / 出现传谣 → 立即重新跑一遍 ②③④",
        "升级规则：新等级高于原等级时自动前移，并同步值班人员",
    ]
    return _card(
        5, "watch", "舆情热点追踪", "极其尽责的舆情巡检员", "watching",
        f"已纳入热点追踪：每 {interval} 分钟复核，队列第 {pos} 位", points,
        {"interval": interval, "queue": snapshot, "position": pos,
         "next_recheck_ts": time.time() + interval * 60},
        confidence=0.92,
    )


# ======================================================================
# Agent ⑥ 通报与安抚
# ======================================================================
def agent_comms(case: dict[str, Any], store: Store) -> dict[str, Any]:
    snapshot = store.queue_snapshot(case)
    level = case.get("level") or 3
    result = comms.reply(case, level)
    engine = "rules"
    if llm.available():
        try:
            primary = llm.compose_reply(case, level, result["tone"])
            if primary:
                result["primary"] = primary
                result["variants"] = [{"tone": "llm", "label": "大模型生成版", "text": primary}] + result["variants"]
                result["llm"] = True
                engine = "llm"
        except Exception:
            pass
    points = [
        f"当前推荐语气：{'安抚' if result['tone'] == 'panic' else '降温' if result['tone'] == 'angry' else '常规'}版",
        "已生成四版通报：常规 / 安抚 / 降温 / 兜底" + (" + 大模型生成版" if engine == "llm" else ""),
        f"措辞禁忌 {len(result['taboos'])} 条已内嵌",
        "市民原话可现场输入，Agent 会识别情绪并改写通报",
    ]
    return _card(
        6, "comms", "通报与情绪安抚", "极高情商的政务发言人", "done",
        "已生成政务通报（含 4 种语气 + 措辞禁忌）", points, {"comms": result},
        confidence=0.9, engine=engine,
    )


# ======================================================================
# 编排器
# ======================================================================
class Pipeline:
    def __init__(self, store: Store) -> None:
        self.store = store

    def intake(self, payload: dict[str, Any]) -> dict[str, Any]:
        ctx = L.build_context(payload)

        # 混合架构：大模型做诉求抽取 / 情绪识别（失败、超时、无 Key 一律降级纯规则）
        engine_intake = "rules"
        if llm.available():
            try:
                merged, changed = llm.merge_extraction(ctx, llm.extract_appeal(ctx["text"]))
                ctx = merged
                if changed:
                    engine_intake = "llm"
            except Exception:
                pass

        case = self.store.create_case(ctx, payload)

        a1 = agent_intake(ctx, payload, engine=engine_intake)
        screening = R.screen(ctx)
        a2 = agent_risk(ctx, screening)
        judgment = grade.evaluate(ctx, screening)
        a3 = agent_grade(judgment)
        qc_result = qc.verify(ctx, screening, judgment)
        a4 = agent_qc(qc_result)

        final_level = min(judgment["level"], qc_result["final_level"]) if qc_result["conflict"] \
            else judgment["level"]

        self.store.update_case(
            case["id"], level=final_level, final_level=final_level,
            stage="处置中" if final_level <= 2 else "待处置",
            screening={"risks": screening["risks"], "partial": screening["partial"],
                       "cleared": screening["cleared"], "screened": screening["screened"],
                       "headline": screening["headline"]},
            judgment=judgment, qc=qc_result,
        )
        case = self.store.get_case(case["id"])

        a5 = agent_watch(case, self.store, final_level)
        a6 = agent_comms(case, self.store)
        self.store.update_case(case["id"], watch=a5["extra"], comms=a6["extra"],
                               agents={"intake": a1, "risk": a2, "grade": a3,
                                       "qc": a4, "watch": a5, "comms": a6})
        case = self.store.get_case(case["id"])

        self._maybe_raise_tickets(case, screening, qc_result, final_level)
        self.store.add_timeline(
            case["id"],
            f"研判完成：{final_level} 级响应 · {'；'.join(r['name'] for r in screening['hard_risks'][:3]) or '未触发高危风险'}",
        )
        return self.store.get_case(case["id"]) or case

    def _maybe_raise_tickets(self, case: dict[str, Any], screening: dict[str, Any],
                             qc_result: dict[str, Any], level: int) -> None:
        hard = screening["hard_risks"]
        raised_p0 = False
        if level == 1:
            raised_p0 = True
            self.store.raise_ticket(
                case, "danger", f"一级响应：{hard[0]['name'] if hard else '危及生命/安全'}",
                [f"{r['name']}（{r['confidence']}）：{'、'.join(r['hits'][:3])}" for r in hard[:3]] +
                [f"处置：{hard[0]['action'] if hard else '转 120/110/119 + 属地'}"],
                agent="Agent ②③",
            )
        elif hard and screening["max_tier"] == 0:
            raised_p0 = True
            self.store.raise_ticket(
                case, "danger", f"生命/安全风险：{hard[0]['name']}（需值班人员立即确认）",
                [f"{r['name']}：{'、'.join(r['hits'][:3])}" for r in hard[:3]] +
                [f"下一步：{hard[0]['action']}"], agent="Agent ②",
            )
        elif hard and level == 2:
            raised_p0 = True
            self.store.raise_ticket(
                case, "danger", f"舆情/群体风险：{hard[0]['name']}（快速响应）",
                [f"{r['name']}：{'、'.join(r['hits'][:3])}" for r in hard[:3]] +
                [f"转办：{hard[0]['dept']}"], agent="Agent ②",
            )

        if qc_result["conflict"] and level == qc_result["final_level"] and level < qc_result["judge_level"]:
            raised_p0 = True
            self.store.raise_ticket(
                case, "conflict",
                f"Agent ③ 判 {qc_result['judge_level']} 级，Agent ④ 认为应为 {qc_result['final_level']} 级",
                [c["detail"] for c in (qc_result["critical"] + qc_result["major"])][:4],
                agent="Agent ③④",
            )

        data_gaps = qc_result.get("data_critical", [])
        for gap in data_gaps:
            self.store.raise_ticket(
                case, "missing_info", f"质控卡住：{gap['name']}",
                [gap["detail"], "该缺口不补齐不能安全放行"],
                agent="Agent ④", options=["已补齐，重新评估", "值班人员接管并担责", "暂按现等级处理"],
            )
        if screening["partial"] and not raised_p0 and not data_gaps:
            first = screening["partial"][0]
            self.store.raise_ticket(
                case, "missing_info", f"研判缺关键信息：{first['name']}",
                [f"缺：{'、'.join(first['missing'])}", "补齐后 Agent 会自动重评估"],
                agent="Agent ②", options=["已补齐，重评估", "暂不补齐，先按现等级处理", "值班人员接管"],
            )

    # ---------------------------------------------------------- 舆情上报 / 复评
    def recheck(self, case: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
        if case["stage"] == "已接管":
            return {"ok": False, "message": "该事项已由值班人员接管，Agent 停止自动干预"}

        kind = report.get("kind") or "worse"
        text = (report.get("text") or "").strip()
        ctx = ctx_from_case(case)

        if kind == "worse":
            ctx["emotions"].update({"urgent", "panic"})
            ctx["text"] += "，情况更紧急了"
        elif kind == "spread":
            ctx["crowd"] = max(ctx["crowd"], 30)
            ctx["emotions"].add("panic")
            ctx["terms"].add("rumor_panic")
            ctx["text"] += "，很多人跟帖说也是这样"
        elif kind == "rumor":
            ctx["terms"].add("rumor_panic")
            ctx["text"] += "，有人开始传谣了"
        else:
            ctx["text"] += "，" + text

        # 用补充文本重新抽取一遍，合并进上下文
        if kind == "spread":
            extra = L.normalize_text("好多人跟帖说也是这样")
            ctx["terms"] |= {f["id"] for f in extra["findings"]}
            ctx["crowd"] = max(ctx["crowd"], extra["crowd"])

        screening = R.screen(ctx)
        judgment = grade.evaluate(ctx, screening)
        qc_result = qc.verify(ctx, screening, judgment)
        new_level = min(judgment["level"], qc_result["final_level"]) if qc_result["conflict"] \
            else judgment["level"]
        old_level = case.get("level") or 4

        self.store.update_case(
            case["id"], screening={"risks": screening["risks"], "partial": screening["partial"],
                                   "cleared": screening["cleared"], "screened": screening["screened"],
                                   "headline": screening["headline"]},
            judgment=judgment, qc=qc_result, ctx=self.store._slim_ctx(ctx),
        )
        case = self.store.get_case(case["id"])
        case.setdefault("reports", []).append({"at": _now(), "kind": kind, "text": text})

        escalated = new_level < old_level
        if escalated:
            self.store.update_case(case["id"], level=new_level, level_prev=old_level,
                                   final_level=new_level,
                                   stage="处置中" if new_level <= 2 else "待处置")
            case = self.store.get_case(case["id"])
            self.store.raise_ticket(
                case, "escalation",
                f"舆情热点升级：{old_level} 级 → {new_level} 级",
                [f"市民/舆情上报：{report.get('label') or kind} {text}",
                 f"复评后触发：{screening['headline']}"],
                agent="Agent ⑤",
            )
            self.store.add_timeline(case["id"], f"舆情追踪触发升级：{old_level} 级 → {new_level} 级")
            message = f"【情况升级】已重新评估：你的诉求从 {old_level} 级升到 {new_level} 级，已转更高层级处置。"
        else:
            self.store.add_timeline(case["id"], f"舆情上报（{kind}）复评完成，维持 {old_level} 级")
            message = f"【情况已记录】复评完成，维持 {old_level} 级；如继续恶化或更多人同诉，请再次反馈。"

        watch = (case.get("watch") or {})
        watch["next_recheck_ts"] = time.time() + RECHECK_MINUTES.get(new_level, 30) * 60
        watch["position"] = self.store.position(case)
        self.store.update_case(case["id"], watch=watch)

        return {"ok": True, "escalated": escalated, "old_level": old_level, "new_level": new_level,
                "message": message, "screening": screening["headline"],
                "ticket": (case.get("hitl") or [None])[-1]}

    # ---------------------------------------------------------- 巡检
    def tick(self) -> list[str]:
        events: list[str] = []
        ts = time.time()
        for c in list(self.store.cases.values()):
            if c["stage"] != "待处置":
                continue
            watch = c.get("watch") or {}
            due = watch.get("next_recheck_ts")
            if not due or ts < due:
                continue
            watch["next_recheck_ts"] = ts + RECHECK_MINUTES.get(c.get("level") or 3, 30) * 60
            self.store.update_case(c["id"], watch=watch)
            open_tickets = [t for t in self.store.tickets.values()
                            if t["case_id"] == c["id"] and t["kind"] == "watch_overdue"
                            and t["status"] == "待处理"]
            if open_tickets:
                continue
            self.store.add_timeline(c["id"], f"Agent ⑤ 巡检：距上次复核已超时，提醒值班人员关注热度")
            self.store.raise_ticket(
                c, "watch_overdue", f"{c.get('level')} 级诉求超过 {(watch or {}).get('interval', 30)} 分钟未复核",
                [f"最后更新：{c['updated_at']}", "请值班人员复核该诉求热度是否变化"],
                agent="Agent ⑤",
            )
            events.append(f"{c['id']} {c['name']} 复核超时")
        return events


def _now() -> str:
    from .store import now_iso
    return now_iso()
