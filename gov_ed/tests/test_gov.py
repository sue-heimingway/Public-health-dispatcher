"""GovOS 规则层 + 端到端测试。

运行：python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import os
import sys
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

# 测试环境强制纯规则，避免意外触发真实大模型调用
os.environ["LLM_ENABLED"] = "0"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import demo_cases, grade, lexicon as L, llm, qc, risks as R  # noqa: E402
from app.pipeline import Pipeline  # noqa: E402
from app.store import Store  # noqa: E402


def ctx(**kw):
    p = {"name": "测试", "phone": "", "source": "12345 热线", "location": "", "crowd": 0, "text": ""}
    p.update(kw)
    return L.build_context(p)


class TestLexicon(unittest.TestCase):
    def test_appeal_translation(self):
        r = L.normalize_text("我公公发烧喘不上气，救命")
        self.assertIn("medical_critical", {f["id"] for f in r["findings"]})

    def test_location_extract(self):
        r = L.normalize_text("阳光花园小区 3 栋 201 的老人发烧了")
        self.assertTrue(any("阳光花园" in b or "小区" in b for b in r["location_bits"]))

    def test_crowd_extract(self):
        r = L.normalize_text("好几十个人都在闹")
        self.assertGreaterEqual(r["crowd"], 10)

    def test_emotion(self):
        r = L.normalize_text("我真的很害怕，会不会耽误")
        self.assertIn("panic", {e["id"] for e in r["emotions"]})

    def test_policy_match(self):
        r = L.normalize_text("异地医保住院怎么报销，需要什么材料")
        self.assertIn("policy", {f["id"] for f in r["findings"]})


class TestRisks(unittest.TestCase):
    def test_life_danger(self):
        s = R.screen(ctx(text="老人发烧喘不上气，氧气用完了，救命"))
        self.assertIn("life_danger", [r["id"] for r in s["risks"]])
        self.assertEqual(s["max_tier"], 0)

    def test_infectious(self):
        s = R.screen(ctx(text="我们小区好多人发烧咳嗽", crowd=20, location="幸福社区"))
        self.assertIn("infectious_cluster", [r["id"] for r in s["risks"]])

    def test_rumor(self):
        s = R.screen(ctx(text="群里都在传退烧药断供，大家都去抢购，好慌"))
        self.assertIn("rumor_panic", [r["id"] for r in s["risks"]])

    def test_plain_shortage_not_risky(self):
        s = R.screen(ctx(text="附近药店退烧药都卖完了，家里老人断药了"))
        self.assertNotIn("supply_shortage", [r["id"] for r in s["hard_risks"]])

    def test_wage_gather(self):
        s = R.screen(ctx(text="拖欠三十多人三个月工资，明天去政府门口拉横幅", crowd=30))
        self.assertIn("mass_incident", [r["id"] for r in s["risks"]])


class TestGradeQC(unittest.TestCase):
    def test_level1(self):
        s = R.screen(ctx(text="老人发烧喘不上气，救命"))
        self.assertEqual(grade.evaluate(ctx(text="老人发烧喘不上气，救命"), s)["level"], 1)

    def test_level4_policy(self):
        c = ctx(text="医保怎么报销")
        s = R.screen(c)
        self.assertEqual(grade.evaluate(c, s)["level"], 4)

    def test_panic_cold_reply_upgrades(self):
        c = ctx(text="我真的很害怕，医保怎么报销，会不会耽误我")
        s = R.screen(c)
        j = grade.evaluate(c, s)
        verdict = qc.verify(c, s, j)
        self.assertTrue(verdict["conflict"])
        self.assertLessEqual(verdict["final_level"], 2)
        self.assertIn("panic_cold_reply", [x["id"] for x in verdict["checks"]])

    def test_location_gap_critical(self):
        c = ctx(text="老人发烧喘不上气，救命", location="")
        s = R.screen(c)
        j = grade.evaluate(c, s)
        verdict = qc.verify(c, s, j)
        self.assertIn("location_gap", [x["id"] for x in verdict["checks"]])

    def test_over_response(self):
        c = ctx(text="医保怎么报销")
        s = R.screen(c)
        inflated = {"level": 2, "summary": "被判二级", "reasons": [], "route": "", "sla_minutes": 10, "path": "step2", "confidence": 0.9, "color": "", "label": ""}
        verdict = qc.verify(c, s, inflated)
        self.assertIn("over_response", [x["id"] for x in verdict["checks"]])


class TestPipeline(unittest.TestCase):
    def setUp(self):
        self.store = Store(ROOT / ".test-tmp" / "gov.json")
        self.store.reset()
        self.p = Pipeline(self.store)

    def test_demo_cases_levels(self):
        expected = {"critical": 1, "infectious": 1, "rumor": 2, "wage": 2, "panic_policy": 2, "shortage": 3, "policy": 4}
        for c in demo_cases.CASES:
            case = self.p.intake(dict(c["payload"]))
            self.assertEqual(case["level"], expected[c["key"]], c["key"])

    def test_spread_escalates(self):
        case = self.p.intake(dict(next(c for c in demo_cases.CASES if c["key"] == "shortage")["payload"]))
        self.assertEqual(case["level"], 3)
        r = self.p.recheck(case, {"kind": "spread", "label": "多人跟帖同诉"})
        self.assertTrue(r["escalated"])
        self.assertLess(r["new_level"], r["old_level"])

    def test_takeover_freezes(self):
        case = self.p.intake(dict(next(c for c in demo_cases.CASES if c["key"] == "critical")["payload"]))
        t = next(t for t in self.store.tickets.values() if t["case_id"] == case["id"])
        self.store.ticket_action(t["id"], "accept", "值班人员", "已到场")
        r = self.p.recheck(self.store.get_case(case["id"]), {"kind": "worse"})
        self.assertFalse(r["ok"])
        self.assertIn("接管", r["message"])


class TestHTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app.server as server
        cls.tmpdir = ROOT / ".test-tmp-http"
        cls.tmpdir.mkdir(exist_ok=True)
        server.STORE = Store(cls.tmpdir / "state.json")
        server.PIPELINE = Pipeline(server.STORE)
        server.STORE.reset()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown(); cls.httpd.server_close()

    def call(self, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data,
                                     method="POST" if body is not None else "GET",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, json.loads(raw.decode()) if "json" in r.headers.get("Content-Type", "") else raw.decode()

    def test_pages(self):
        for p in ("/", "/report?t=none", "/duty", "/static/style.css", "/static/app.js"):
            self.assertEqual(self.call(p)[0], 200, p)

    def test_intake_and_report(self):
        case = next(c for c in demo_cases.CASES if c["key"] == "critical")["payload"]
        st, c = self.call("/api/intake", case)
        self.assertEqual(st, 200)
        self.assertEqual(c["level"], 1)
        self.assertEqual(set(c["agents"]), {"intake", "risk", "grade", "qc", "watch", "comms"})
        st, view = self.call(f"/api/report/{c['token']}")
        self.assertEqual(st, 200)
        st, r = self.call("/api/report", {"token": c["token"], "kind": "worse", "label": "更紧急"})
        self.assertTrue(r["ok"])


class TestLLM(unittest.TestCase):
    def test_parse_json_robust(self):
        self.assertEqual(llm._parse_json('```json\n{"a": 1}\n```')["a"], 1)
        self.assertEqual(llm._parse_json('前缀 {"b": 2} 后缀')["b"], 2)
        self.assertIsNone(llm._parse_json("没有任何 JSON"))

    def test_merge_extraction(self):
        c = {"terms": set(), "emotions": set(), "crowd": 0, "has_location": False,
             "location": "未明确"}
        c2, changed = llm.merge_extraction(c, {
            "types": ["gas_fire", "不存在的类型"], "emotions": ["panic"],
            "crowd": 8, "location": "测试路 1 号", "summary": "疑似燃气泄漏",
        })
        self.assertTrue(changed)
        self.assertIn("gas_fire", c2["terms"])
        self.assertNotIn("不存在的类型", c2["terms"])
        self.assertIn("panic", c2["emotions"])
        self.assertEqual(c2["crowd"], 8)
        self.assertTrue(c2["has_location"])
        self.assertEqual(c2["summary"], "疑似燃气泄漏")

    def test_merge_ignores_none(self):
        c = {"terms": set(), "emotions": set(), "crowd": 0, "has_location": False, "location": ""}
        c2, changed = llm.merge_extraction(c, None)
        self.assertFalse(changed)


class TestLLMHybrid(unittest.TestCase):
    def setUp(self):
        self.store = Store(ROOT / ".test-tmp" / "hybrid.json")
        self.store.reset()
        self.p = Pipeline(self.store)
        import app.pipeline as P
        self._P = P
        self._old = (llm.available, llm.extract_appeal, llm.compose_reply)
        llm.available = lambda: True
        llm.extract_appeal = lambda text: {
            "types": ["gas_fire"], "emotions": ["panic"],
            "location": "测试路 1 号", "crowd": 5,
            "summary": "疑似燃气泄漏", "urgent": True,
        }
        llm.compose_reply = lambda case, level, tone: "【大模型版】已受理，请保持电话畅通。"

    def tearDown(self):
        llm.available, llm.extract_appeal, llm.compose_reply = self._old

    def test_hybrid_merges_llm_into_pipeline(self):
        case = self.p.intake({"name": "张三", "phone": "1", "source": "12345 热线",
                              "location": "", "crowd": 0, "text": "随便说点什么"})
        self.assertEqual(case["agents"]["intake"]["engine"], "llm")
        self.assertIn("gas_fire", case["ctx"]["terms"])
        self.assertEqual(case["agents"]["comms"]["engine"], "llm")
        self.assertIn("大模型", case["agents"]["comms"]["extra"]["comms"]["primary"])
        self.assertTrue(case["agents"]["comms"]["extra"]["comms"].get("llm"))


if __name__ == "__main__":
    unittest.main()
