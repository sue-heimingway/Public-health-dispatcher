"""民声先知 · 词元引擎 —— Streamlit 界面（工作台 + 值班处置台）。

侧边栏切换两个页面，共用同一个持久化 Store（data/state.json），
所以工作台生成的工单，值班处置台能立刻看到并处理。

运行：
    pip install streamlit
    streamlit run streamlit_app.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st  # noqa: E402
import streamlit.components.v1 as components  # noqa: E402
from app import demo_cases  # noqa: E402
from app.pipeline import Pipeline  # noqa: E402
from app.store import Store  # noqa: E402

st.set_page_config(page_title="民声先知 · 词元引擎", page_icon="🏛️", layout="wide")

LV = {
    1: ("#b91c1c", "一级响应 · 转 120/110/119 + 属地"),
    2: ("#ea580c", "二级响应 · 转 宣传部/网信办/政法"),
    3: ("#ca8a04", "三级响应 · 派发责任部门工单"),
    4: ("#2563eb", "四级响应 · 自动答复闭环"),
}
STATUS_ZH = {"done": "完成", "warn": "需注意", "critical": "高危", "watching": "追踪中"}
SOURCES = ["12345 热线", "微信", "微博", "抖音", "社区网格", "现场"]


# ---------------------------------------------------------------- 外观：对齐 GovOS 设计系统
def _inject_style() -> None:
    st.markdown(
        """
        <style>
        html, body { font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; }
        [data-testid="stAppViewContainer"] {
          background:
            radial-gradient(1200px 600px at 15% -10%, #ffffff 0%, rgba(255,255,255,0) 60%),
            radial-gradient(900px 500px at 110% 0%, #e3f0ff 0%, rgba(227,240,255,0) 55%),
            #eef2f6;
        }
        [data-testid="stSidebar"] { background: #ffffff; border-right: 1px solid #e2e8f0; }
        .block-container { padding-top: 0.9rem; max-width: 1320px; }
        [data-testid="stExpander"] {
          border: 1px solid #e2e8f0 !important; border-radius: 14px !important;
          background: #fff; box-shadow: 0 10px 30px -20px rgba(15, 23, 42, .35);
          margin-bottom: 9px;
        }
        [data-testid="stExpander"] details > summary { font-weight: 600; }
        [data-testid="stBaseButton-primary"] {
          background: linear-gradient(180deg, #1f2937, #0f172a) !important;
          border-color: #0f172a !important; color: #fff !important; border-radius: 9px !important;
        }
        [data-testid="stBaseButton-secondary"] { border-radius: 9px !important; }
        [data-testid="stDataFrame"] { border: 1px solid #e2e8f0; border-radius: 10px; }
        [data-testid="stTextInput"] input,
        [data-testid="stTextArea"] textarea { border-radius: 9px; }
        h1, h2, h3 { color: #0f172a !important; letter-spacing: -.2px; }
        #MainMenu { visibility: hidden; }
        [data-testid="stToolbar"] { display: none; }
        footer { visibility: hidden; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _brand_bar(store: Store) -> None:
    """顶部品牌条，尽量贴近网页版 topbar 的观感。"""
    s = store.stats()
    pending = len(store.pending_tickets())
    st.markdown(
        f"""
        <div style="display:flex;align-items:center;gap:12px;padding:13px 18px;background:#fff;
             border:1px solid #e2e8f0;border-radius:14px;
             box-shadow:0 10px 30px -20px rgba(15,23,42,.35);margin-bottom:16px">
          <div style="width:36px;height:36px;border-radius:10px;display:grid;place-items:center;
               background:linear-gradient(145deg,#e11d48,#b91c1c);color:#fff;font-weight:800">G</div>
          <div>
            <div style="font-weight:750;font-size:15px;color:#0f172a">GovOS 诉求分流台</div>
            <div style="font-size:11px;color:#8595ad">社会治理诉求分流中枢 · 6 Agent</div>
          </div>
          <div style="margin-left:auto;display:flex;gap:20px;font-size:12px;color:#41506b">
            <span><b>6/6</b> 在线</span>
            <span><b>10</b> 风险规则</span>
            <span><b style="color:{'#b91c1c' if pending else '#067647'}">{pending}</b> 待处理工单</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


_inject_style()


# ---------------------------------------------------------------- 渲染：工作台
def render_verdict(case: dict) -> None:
    lvl = case.get("level") or 3
    color, route = LV.get(lvl, LV[3])
    qc = case.get("qc", {})
    vc = "red" if qc.get("conflict") else "green"
    st.markdown(
        f"""
        <div style="background:{color}11;border-left:6px solid {color};border-radius:10px;
             padding:16px 20px;margin-bottom:6px">
          <div style="font-size:30px;font-weight:800;color:{color}">{lvl} 级响应</div>
          <div style="font-size:15px;color:#333;margin:4px 0">{route}</div>
          <div style="font-size:13px;color:#666">
            诉求人：{case.get('name')}　·　{case.get('location') or '未明确地址'}　·　
            涉及 {case.get('crowd') or 0} 人　·　质控：<b style="color:{vc}">{qc.get('verdict')}</b>
          </div>
          <div style="font-size:13px;color:#555;margin-top:4px">诉求原文：{case.get('text')}</div>
        </div>""",
        unsafe_allow_html=True,
    )


def render_agent(a: dict, case: dict) -> None:
    engine = " ⚡大模型" if a.get("engine") == "llm" else ""
    label = f"【{a['no']}】{a['name']} · {STATUS_ZH.get(a['status'], a['status'])}{engine}"
    with st.expander(label, expanded=a["status"] in ("critical", "warn")):
        st.caption(f"{a['role']} · 置信度 {a['confidence']} · {a['elapsed_ms']}ms")
        st.markdown(f"**{a['headline']}**")
        for p in a.get("points", []):
            st.markdown(f"- {p}")
        render_extra(a["key"], a.get("extra", {}), case)


def render_extra(key: str, e: dict, case: dict) -> None:
    if key == "intake" and e.get("translation"):
        st.dataframe(
            [{"市民原话": t["lay"], "标准诉求": t["term"]} for t in e["translation"]],
            hide_index=True,
        )
    elif key == "risk":
        for r in e.get("risks", []):
            tier = "一级" if r["tier"] == 0 else "二级"
            st.markdown(f"##### {r['name']}　`{tier}`　置信度 {r['confidence']}　→ {r['dept']}")
            st.markdown(f"**为什么高危**：{r['risky']}")
            st.markdown(f"**时效**：{r['window']}　·　**处置**：{r['action']}")
            if r.get("hits"):
                st.markdown("命中证据：" + "、".join(r["hits"]))
            if r.get("ask"):
                st.markdown("补问清单：" + "；".join(r["ask"]))
        if e.get("cleared"):
            st.caption(f"已排查 {e['screened']} 类社会风险；未触发：{'、'.join(e['cleared'][:8])} 等")
    elif key == "grade":
        j = e.get("judgment", {})
        for r in j.get("reasons", []):
            st.markdown(f"- **{r['k']}**｜{r['v']}")
        st.info(f"处置通道：{j.get('route', '')}　·　响应时限 {j.get('sla_minutes', 0) or '立即'} 分钟")
    elif key == "qc":
        checks = e.get("qc", {}).get("checks", [])
        for c in checks:
            icon = {"critical": "🔴", "major": "🟠", "minor": "⚪"}.get(c["level"], "⚪")
            st.markdown(f"{icon} **{c['name']}**：{c['detail']}")
        if not checks:
            st.success("交叉核验全部通过。")
    elif key == "comms":
        comms = e.get("comms", {})
        variants = comms.get("variants", [])
        if variants:
            labels = [v["label"] for v in variants]
            pick = st.selectbox("通报语气", range(len(labels)), format_func=lambda i: labels[i],
                                key=f"tone_{case['id']}")
            st.markdown(
                f"<div style='white-space:pre-wrap;background:#f7f9fc;border-radius:8px;"
                f"padding:12px'>{variants[pick]['text']}</div>", unsafe_allow_html=True)
        if comms.get("taboos"):
            with st.expander("措辞禁忌"):
                for t in comms["taboos"]:
                    st.markdown(f"- {t}")


# ---------------------------------------------------------------- 渲染：值班处置台
def render_workbench(store: Store) -> None:
    _brand_bar(store)
    left, right = st.columns([1, 1.6])

    with left:
        st.subheader("市民求助录入")
        demo_map = {c["key"]: c for c in demo_cases.CASES}
        demo = st.selectbox("载入演示诉求", ["手动输入"] + list(demo_map),
                            format_func=lambda k: demo_map[k]["title"] if k != "手动输入" else "（手动输入）")
        base = demo_map[demo]["payload"] if demo != "手动输入" else {}

        payload = {
            "name": st.text_input("诉求人", value=base.get("name", "王女士"), key=f"name_{demo}"),
            "phone": st.text_input("联系电话", value=base.get("phone", "13800000000"), key=f"phone_{demo}"),
            "source": st.selectbox("来源渠道", SOURCES,
                                   index=SOURCES.index(base.get("source", "12345 热线")), key=f"src_{demo}"),
            "crowd": st.number_input("涉及人数", min_value=0, value=int(base.get("crowd", 1)), key=f"crowd_{demo}"),
            "location": st.text_input("地址（留空自动抓取）", value=base.get("location", ""), key=f"loc_{demo}"),
            "text": st.text_area("诉求内容", value=base.get("text", ""), height=140, key=f"text_{demo}",
                                 placeholder="例：老人发烧喘不上气，氧气用完了，救命"),
        }

        if st.button("接入并跑完 6 个 Agent", type="primary", use_container_width=True):
            if not payload["text"].strip():
                st.error("诉求内容不能为空")
            else:
                with st.spinner("6 个 Agent 研判中…"):
                    st.session_state["case"] = Pipeline(store).intake(payload)
                st.success("研判完成，工单已进入「值班处置台」")

    with right:
        st.subheader("六 Agent 流转")
        case = st.session_state.get("case")
        if not case:
            st.info("左侧录入诉求后点「接入并跑完 6 个 Agent」，这里会展示流转结果。")
        else:
            render_verdict(case)
            for key in ("intake", "risk", "grade", "qc", "watch", "comms"):
                a = case.get("agents", {}).get(key)
                if a:
                    render_agent(a, case)


def render_duty(store: Store) -> None:
    tickets = store.pending_tickets()
    if not tickets:
        st.success("✅ 当前没有待处理工单。")
        _render_audit(store)
        return

    label_map = {t["id"]: f"{t['priority']} · {t['subject']} — {t['reason'][:32]}" for t in tickets}
    sel_id = st.selectbox("选择工单", [t["id"] for t in tickets],
                          format_func=lambda tid: label_map[tid], key="duty_sel")
    t = next(x for x in tickets if x["id"] == sel_id)
    case = store.get_case(t["case_id"])
    j = case["judgment"] if case else {}
    qc = case["qc"] if case else {}

    overdue = time.time() > t["due_ts"]
    if overdue:
        st.error("⏰ 该工单已超 SLA")

    st.markdown(f"#### {t['priority']} 工单 · {t['subject']}　`{t['location']}`")
    st.markdown(f"**{t['reason']}**")
    st.markdown("诉求：" + (case.get("text") if case else t.get("text", "")))

    with st.expander("Agent 给的证据"):
        for e in t["evidence"]:
            st.markdown(f"- {e}")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**分级裁判 Agent ③**：`{j.get('level', '—')} 级`")
        st.caption(j.get("summary", ""))
    with c2:
        st.markdown(f"**交叉核验 Agent ④**：`{qc.get('final_level', '—')} 级`　{'(冲突)' if qc.get('conflict') else ''}")
        st.caption(qc.get("verdict", ""))

    note = st.text_input("处置备注（进审计日志）", key=f"note_{t['id']}")
    cols = st.columns(6)
    if cols[0].button("同意定级", key=f"a_{t['id']}"):
        _do(store, t, "agree", note)
    if cols[1].button("升级一级", key=f"b_{t['id']}"):
        _do(store, t, "upgrade", note, 1)
    if cols[2].button("升级二级", key=f"c_{t['id']}"):
        _do(store, t, "upgrade", note, 2)
    if cols[3].button("降级", key=f"d_{t['id']}"):
        _do(store, t, "downgrade", note, max(3, (t.get("level") or 4) + 1))
    if cols[4].button("要求补信息", key=f"e_{t['id']}"):
        _do(store, t, "missing", note)
    if cols[5].button("接管该事项", key=f"f_{t['id']}"):
        _do(store, t, "accept", note)

    _render_audit(store)


def _do(store: Store, t: dict, action: str, note: str, level: int | None = None) -> None:
    if action == "downgrade" and not note.strip():
        st.warning("降级必须写理由，否则不允许降级")
        return
    store.ticket_action(t["id"], action, "值班人员", note.strip(), level)
    st.success("已执行，审计已留痕")
    st.rerun()


def _render_audit(store: Store) -> None:
    with st.expander("审计日志"):
        rows = store.audit[-20:][::-1]
        if not rows:
            st.caption("暂无记录")
        for e in rows:
            st.markdown(f"- {e['at']} `{e['action']}` {e['ticket']}　{e['detail'][:60]}")


# ---------------------------------------------------------------- 渲染：市民上报
def render_report(store: Store) -> None:
    msg = st.session_state.get("report_msg")
    if msg:
        del st.session_state["report_msg"]
        if msg.get("ok"):
            if msg.get("escalated"):
                st.success(msg.get("message", ""))
            else:
                st.info(msg.get("message", ""))
        else:
            st.warning(msg.get("message", ""))

    cases = list(store.cases.values())
    if not cases:
        st.info("还没有诉求，先去「诉求工作台」录一条。")
        return

    label_map = {c["id"]: f"{c['id']} · {c['name']} · {(c.get('text') or '')[:22]}" for c in cases}
    cid = st.selectbox("选择要反馈的诉求", list(label_map),
                       format_func=lambda i: label_map[i], key="report_case")
    case = store.get_case(cid)
    lvl = case.get("level")
    st.markdown(f"当前你是 **{lvl} 级响应**（{case.get('stage')}），如果情况有变化，点下面按钮：")

    cols = st.columns(3)
    if cols[0].button("🆘 情况更紧急了", key=f"w_{cid}"):
        _report(store, case, "worse", "情况更紧急")
    if cols[1].button("👥 很多人跟帖也说这样", key=f"s_{cid}"):
        _report(store, case, "spread", "多人跟帖同诉")
    if cols[2].button("📣 有人开始传谣了", key=f"r_{cid}"):
        _report(store, case, "rumor", "出现传谣")

    st.caption("提示：点一下会立刻重新评估，不是普通留言；值班人员会同时收到提醒。")


def _report(store: Store, case: dict, kind: str, label: str) -> None:
    result = Pipeline(store).recheck(case, {"kind": kind, "label": label, "text": label})
    st.session_state["report_msg"] = result
    st.rerun()


# ---------------------------------------------------------------- 入口
store = Store()  # 持久化 Store，与网页版共用 data/state.json

page = st.sidebar.radio("页面", ["诉求工作台", "值班处置台", "市民上报"])

with st.sidebar:
    st.divider()
    pending = len(store.pending_tickets())
    st.markdown(f"待处理工单：**{pending}**")
    if st.button("清空全部数据", use_container_width=True):
        store.reset()
        st.rerun()
    st.divider()
    embed = st.checkbox("内嵌网页版（像素级一致）", value=False,
                        help="勾选后用 iframe 直接内嵌 http://127.0.0.1:8780 的网页版页面，需要网页版服务在运行")

if embed:
    st.info("正在内嵌网页版 http://127.0.0.1:8780 —— 需要网页版服务（run.py）同时在运行。")
    components.iframe("http://127.0.0.1:8780", height=1500, scrolling=True)
    st.stop()

if page == "诉求工作台":
    render_workbench(store)
elif page == "值班处置台":
    _brand_bar(store)
    st.subheader("🛡️ 值班处置台")
    render_duty(store)
else:
    _brand_bar(store)
    st.subheader("📱 市民上报")
    render_report(store)
