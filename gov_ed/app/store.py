"""底座二：诉求 / 工单 / 审计的线程安全存储，JSON 原子落盘。"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from . import config

PRIORITY = {
    "danger": ("P0", 5),
    "conflict": ("P0", 5),
    "escalation": ("P0", 5),
    "missing_info": ("P1", 15),
    "duty_call": ("P1", 10),
    "watch_overdue": ("P2", 30),
    "comms_risk": ("P1", 10),
}


def now_iso() -> str:
    return datetime.now().strftime("%m-%d %H:%M:%S")


def now_ts() -> float:
    return time.time()


class Store:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config.DATA_FILE
        self.lock = threading.RLock()
        self.cases: dict[str, dict[str, Any]] = {}
        self.tickets: dict[str, dict[str, Any]] = {}
        self.audit: list[dict[str, Any]] = []
        self.seq = 0
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        self.cases = data.get("cases", {})
        self.tickets = data.get("tickets", {})
        self.audit = data.get("audit", [])[-300:]
        self.seq = data.get("seq", 0)

    def save(self) -> None:
        with self.lock:
            payload = {
                "cases": self.cases, "tickets": self.tickets,
                "audit": self.audit[-300:], "seq": self.seq, "saved_at": now_iso(),
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)

    def next_seq(self) -> int:
        with self.lock:
            self.seq += 1
            return self.seq

    # ------------------------------------------------------------ 诉求
    def create_case(self, ctx: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            n = self.next_seq()
            case = {
                "id": f"G-{n:04d}",
                "token": secrets.token_urlsafe(8),
                "name": ctx["name"],
                "phone": ctx["phone"],
                "location": ctx["location"],
                "source": ctx["source"],
                "crowd": ctx["crowd"],
                "text": ctx["text"],
                "stage": "研判中",
                "level": None,
                "level_prev": None,
                "final_level": None,
                "created_at": now_iso(),
                "created_ts": now_ts(),
                "updated_at": now_iso(),
                "reports": [],
                "timeline": [{"at": now_iso(), "text": "诉求受理，开始研判"}],
                "hitl": [],
                "agents": {},
                "screening": {},
                "judgment": {},
                "qc": {},
                "comms": {},
                "watch": {},
                "ctx": self._slim_ctx(ctx),
                "source2": payload.get("source2", "manual"),
            }
            self.cases[case["id"]] = case
            self.save()
            return case

    @staticmethod
    def _slim_ctx(ctx: dict[str, Any]) -> dict[str, Any]:
        return {
            "terms": sorted(ctx["terms"]),
            "emotions": sorted(ctx["emotions"]),
            "crowd": ctx["crowd"],
            "findings": ctx["findings"],
            "translation": ctx["translation"],
            "location_bits": ctx["location_bits"],
            "summary": ctx.get("summary", ""),
        }

    def get_case(self, cid: str) -> dict[str, Any] | None:
        return self.cases.get(cid)

    def get_by_token(self, token: str) -> dict[str, Any] | None:
        for c in self.cases.values():
            if c["token"] == token:
                return c
        return None

    def update_case(self, cid: str, **fields: Any) -> dict[str, Any] | None:
        with self.lock:
            case = self.cases.get(cid)
            if not case:
                return None
            case.update(fields)
            case["updated_at"] = now_iso()
            self.save()
            return case

    def add_timeline(self, cid: str, text: str) -> None:
        with self.lock:
            case = self.cases.get(cid)
            if not case:
                return
            case.setdefault("timeline", []).append({"at": now_iso(), "text": text})
            case["updated_at"] = now_iso()
            self.save()

    # ------------------------------------------------------------ 队列
    @staticmethod
    def _sort_key(c: dict[str, Any]) -> tuple:
        return (c.get("level") or 9, -(c.get("crowd") or 0), c.get("created_ts") or 0)

    def window(self) -> list[dict[str, Any]]:
        return sorted([c for c in self.cases.values() if c["stage"] in ("待处置", "处置中")],
                      key=self._sort_key)

    def position(self, case: dict[str, Any]) -> int:
        for i, c in enumerate(self.window(), start=1):
            if c["id"] == case["id"]:
                return i
        return 0

    def queue_snapshot(self, for_case: dict[str, Any] | None = None) -> dict[str, Any]:
        window = self.window()
        critical = [c for c in window if (c.get("level") or 9) <= 2]
        ahead = 0
        if for_case:
            for c in window:
                if c["id"] == for_case["id"]:
                    break
                ahead += 1
        names = []
        for c in critical:
            if for_case and c["id"] == for_case["id"]:
                continue
            risks = (c.get("screening") or {}).get("risks") or []
            names.append(risks[0]["name"] if risks else (c.get("text") or "急难事项")[:12])
        return {
            "total": max(0, len(window) - (1 if for_case else 0)),
            "critical": names[:5],
            "ahead_of": ahead,
            "waiting": len([c for c in window if c["stage"] == "待处置"]),
        }

    # ------------------------------------------------------------ 工单
    def raise_ticket(self, case: dict[str, Any], kind: str, reason: str,
                     evidence: list[str], options: list[str] | None = None,
                     agent: str = "") -> dict[str, Any]:
        priority, sla = PRIORITY.get(kind, ("P1", 15))
        with self.lock:
            n = self.next_seq()
            ticket = {
                "id": f"H-{n:04d}",
                "case_id": case["id"],
                "subject": case["name"],
                "location": case.get("location"),
                "text": case.get("text"),
                "level": case.get("level"),
                "kind": kind, "priority": priority, "sla_minutes": sla,
                "reason": reason, "evidence": evidence,
                "options": options or ["同意定级", "升级为一级", "升级为二级", "降级", "要求补充信息", "值班人员接管"],
                "agent": agent, "status": "待处理", "assignee": "", "decision": "", "note": "",
                "created_at": now_iso(), "created_ts": now_ts(), "due_ts": now_ts() + sla * 60,
                "closed_at": "",
                "timeline": [{"at": now_iso(), "text": f"Agent 发起工单（{priority}，SLA {sla} 分钟）：{reason}"}],
            }
            self.tickets[ticket["id"]] = ticket
            case.setdefault("hitl", []).append(ticket["id"])
            self.save()
            self.log("hitl_raise", ticket["id"], case["id"], reason)
            return ticket

    def pending_tickets(self) -> list[dict[str, Any]]:
        order = {"P0": 0, "P1": 1, "P2": 2}
        return sorted([t for t in self.tickets.values() if t["status"] == "待处理"],
                      key=lambda t: (order.get(t["priority"], 9), t["created_ts"]))

    def ticket_action(self, tid: str, action: str, duty: str = "值班人员",
                      note: str = "", level: int | None = None) -> dict[str, Any] | None:
        with self.lock:
            t = self.tickets.get(tid)
            if not t:
                return None
            t["status"] = "已接管" if action == "accept" else "已办结"
            t["assignee"] = duty
            t["decision"] = action
            t["note"] = note
            t["closed_at"] = now_iso()
            t["timeline"].append({"at": now_iso(), "text": f"{duty} 执行：{action} {note}".strip()})
            case = self.cases.get(t["case_id"])
            if case:
                if action == "accept":
                    case["stage"] = "已接管"
                    case["timeline"].append({"at": now_iso(), "text": f"{duty} 已接管该事项，Agent 决策冻结"})
                elif level is not None:
                    case["level_prev"] = case.get("level")
                    case["level"] = level
                    case["final_level"] = level
                    case["stage"] = "处置中" if level <= 2 else case.get("stage", "待处置")
                    case["timeline"].append({"at": now_iso(), "text": f"{duty} 人工改判为 {level} 级响应"})

            subsumed = {"watch_overdue", "missing_info", "duty_call", "comms_risk"}
            for other in self.tickets.values():
                if other["id"] == tid or other["status"] != "待处理" or other["case_id"] != t["case_id"]:
                    continue
                if other["kind"] in subsumed or action == "accept":
                    other["status"] = "已办结"
                    other["assignee"] = duty
                    other["decision"] = other["decision"] or "auto_close"
                    other["note"] = ((other["note"] + " ") if other["note"] else "") + "（值班人员处理该事项，自动关闭）"
                    other["closed_at"] = now_iso()
                    other["timeline"].append({"at": now_iso(), "text": f"{duty} 处理该事项，本工单自动关闭"})

            self.save()
            self.log(f"hitl_{action}", tid, t["case_id"], note or action)
            return t

    def overdue_tickets(self) -> list[dict[str, Any]]:
        ts = now_ts()
        return [t for t in self.tickets.values() if t["status"] == "待处理" and ts > t["due_ts"]]

    # ------------------------------------------------------------ 审计 / 统计
    def log(self, action: str, ticket: str, case_id: str, detail: str = "") -> None:
        with self.lock:
            self.audit.append({
                "at": now_iso(), "ts": now_ts(), "action": action,
                "ticket": ticket, "case": case_id, "detail": detail[:200],
            })
            self.audit = self.audit[-300:]

    def stats(self) -> dict[str, Any]:
        cases = list(self.cases.values())
        return {
            "total": len(cases),
            "waiting": len([c for c in cases if c["stage"] == "待处置"]),
            "critical": len([c for c in cases if (c.get("level") or 9) == 1]),
            "pending": len(self.pending_tickets()),
            "taken_over": len([c for c in cases if c["stage"] == "已接管"]),
        }

    def reset(self) -> None:
        with self.lock:
            self.cases.clear()
            self.tickets.clear()
            self.audit.clear()
            self.seq = 0
            self.save()
