"""Agent ②：社会高危风险预警 —— 懂"社会风险"的研判员。

平移自急诊版"红旗排雷"：急诊抓"漏诊会死的病"，这里抓"漏判会炸锅的事"。
每条规则同样给四样东西：
  1. 为什么高危（risky）与时效（window）；
  2. 命中证据（hits）——让处置人员知道不是机器瞎猜；
  3. 还缺什么（missing/ask）——补问清单；
  4. 处置动作（action）——转给哪个口、先做什么。

tier：0 = 一级响应级（生命/安全/重大群体），1 = 二级响应级（舆情/恐慌/群体苗头）。
"""
from __future__ import annotations

from typing import Any


def _t(ctx: dict[str, Any], *ids: str) -> bool:
    return any(i in ctx["terms"] for i in ids)


def _emo(ctx: dict[str, Any], *ids: str) -> bool:
    return any(i in ctx["emotions"] for i in ids)


def _crowd(ctx: dict[str, Any]) -> int:
    return ctx.get("crowd") or 0


RULES: list[dict[str, Any]] = [
    {
        "id": "life_danger", "name": "危及生命/安全的紧急救助", "tier": 0, "weight": 99,
        "dept": "120 / 110 / 119 + 属地",
        "risky": "断氧、重症、火灾燃气、坍塌、中毒等若不立即处置，随时可能造成人员死亡",
        "window": "分钟级，先救人再走流程",
        "test": lambda c: _life_danger(c),
        "ask": ["具体地址和联系电话？", "患者/被困人员年龄、人数？", "是否有基础病、孕妇、儿童？",
                "是否已经拨打了 120/110/119？"],
        "action": "立即转 120/110/119，同步属地街道社区到场，全程跟进到闭环",
    },
    {
        "id": "infectious_cluster", "name": "传染病聚集性爆发线索", "tier": 0, "weight": 96,
        "dept": "卫健委 / 疾控中心",
        "risky": "同一区域多人发热/咳嗽可能是聚集性疫情早期信号，处置滞后会放大扩散",
        "window": "小时级流调与采样",
        "test": lambda c: _infectious(c),
        "ask": ["多少人？是否同一小区/学校/单位？", "是否有共同接触史（聚餐、班车、宿舍）？",
                "最早什么时间开始的？", "有没有住院或重症？"],
        "action": "转卫健委/疾控，属地核实点位与人数，必要时采样流调，同步网信关注舆情",
    },
    {
        "id": "food_poison", "name": "群体食物中毒", "tier": 0, "weight": 95,
        "dept": "市场监管局 / 卫健委",
        "risky": "群体性食物中毒可能涉及同一食品源头，迟报会扩大中毒人群",
        "window": "小时级溯源与封存",
        "test": lambda c: _food(c),
        "ask": ["多少人出现症状？", "共同进食了什么、在哪个食堂/餐馆？", "症状是呕吐腹泻还是发热？"],
        "action": "转市场监管局+卫健委，封存可疑食品溯源，医院开通绿色通道",
    },
    {
        "id": "campus_safety", "name": "校园安全隐患/涉恐涉暴线索", "tier": 0, "weight": 94,
        "dept": "教育局 / 公安",
        "risky": "涉及未成年人的欺凌、持械、扬言报复等线索，处置不当会酿成恶性事件",
        "window": "当日落地核查",
        "test": lambda c: _campus(c),
        "ask": ["学校名称与年级？", "是否有人持械、扬言伤人？", "是家长、学生还是教师举报？"],
        "action": "转教育+公安核查，护校安园机制响应，全程保护举报人信息",
    },
    {
        "id": "mass_incident", "name": "群体性事件苗头", "tier": 1, "weight": 92,
        "dept": "政法 / 信访 / 属地",
        "risky": "聚集、讨薪、征地、维权若处置失当，极易演变为围堵、冲突等群体性事件",
        "window": "当日稳控，属地约访",
        "test": lambda c: _mass(c),
        "ask": ["多少人、在什么地点、什么时间？", "诉求主体是什么（讨薪/征地/物业）？",
                "是否有牵头人、是否已与属地沟通？"],
        "action": "转政法+信访+属地，先稳控再分流，诉求合理的部分当场接单、限期答复",
    },
    {
        "id": "rumor_panic", "name": "谣言/恐慌传播", "tier": 1, "weight": 88,
        "dept": "网信办 / 宣传部",
        "risky": "恐慌信息与抢购潮会自我强化，次生舆情比原始事件更难收拾",
        "window": "小时级核实辟谣",
        "test": lambda c: _rumor(c),
        "ask": ["信息源头是什么平台、谁发的？", "是否核实过真实性？", "是否已出现抢购/囤积？"],
        "action": "转网信办核实，属实的处置+权威发布，属谣言的联动辟谣并溯源",
    },
    {
        "id": "elderly_emergency", "name": "独居老人急难", "tier": 1, "weight": 86,
        "dept": "民政 / 街道社区",
        "risky": "独居/空巢老人无人照护，急病、摔倒、断药都可能造成不可逆后果",
        "window": "当日上门",
        "test": lambda c: _elderly(c),
        "ask": ["老人年龄、有无基础病？", "子女能否联系上？", "是否已跌倒、发烧、断药？"],
        "action": "转民政+街道，网格员当日上门，必要时协助送医、代购药品",
    },
    {
        "id": "supply_shortage", "name": "物资/药品短缺（可能引发抢购）", "tier": 1, "weight": 82,
        "dept": "商务局 / 市场监管局 / 发改委",
        "risky": "药品、生活物资短缺叠加恐慌情绪，容易演变为抢购与舆情",
        "window": "当日调度保供",
        "test": lambda c: _shortage(c),
        "ask": ["缺什么、缺多久了？", "是单个门店还是普遍缺货？", "周边是否已出现囤积？"],
        "action": "转商务/市场监管/发改，启动保供调度，同步发布供应信息平抑恐慌",
    },
    {
        "id": "wage_collective", "name": "欠薪聚集讨薪", "tier": 1, "weight": 84,
        "dept": "人社 / 住建",
        "risky": "欠薪叠加聚集，极易由经济诉求升级为群体性事件",
        "window": "当日前置调解",
        "test": lambda c: _wage(c),
        "ask": ["拖欠多少人、金额多少？", "企业名称与项目？", "是否已约定再次发放时间？"],
        "action": "转人社+住建，约谈用人单位，农民工工资专户核查，防止聚集升级",
    },
    {
        "id": "secondary_public_opinion", "name": "次生舆情风险", "tier": 1, "weight": 80, "soft": True,
        "dept": "宣传部 / 网信办",
        "risky": "诉求带有强烈情绪（愤怒/绝望/恐慌），若只做机械回复，一句话就能上热搜",
        "window": "小时级温和回应",
        "test": lambda c: _secondary(c),
        "ask": ["诉求背后是否有执法争议、处置不当？", "是否已在网上发酵？"],
        "action": "转宣传部/网信办，生成温和回应话术，避免机械、冷漠措辞",
    },
]


def _life_danger(c: dict[str, Any]) -> tuple[bool, list[str], list[str], float]:
    hits = []
    for tid, label in (("medical_critical", "重症就医求助"), ("gas_fire", "燃气泄漏/火灾"),
                       ("collapse", "房屋坍塌/地质灾害"), ("hazmat", "危化品泄漏/爆炸"),
                       ("food_poison", "群体食物中毒"), ("extreme_weather", "极端天气被困")):
        if _t(c, tid):
            hits.append(label)
    if not hits:
        return False, [], [], 0.0
    score = len(hits) * 3
    if _emo(c, "panic", "despair", "urgent"):
        hits.append("伴随强烈情绪")
        score += 2
    return True, hits, ["具体地址", "联系电话"], min(0.99, 0.6 + score * 0.05)


def _infectious(c: dict[str, Any]) -> tuple[bool, list[str], list[str], float]:
    if not _t(c, "infectious_cluster"):
        return False, [], [], 0.0
    hits = ["多人发热/咳嗽聚集性线索"]
    score = 4
    if _crowd(c) >= 5:
        hits.append(f"涉及 {_crowd(c)} 人")
        score += 2
    if c.get("has_location"):
        hits.append("有明确点位")
        score += 1
    return True, hits, ["确切人数与共同接触史"], min(0.97, 0.5 + score * 0.06)


def _food(c: dict[str, Any]) -> tuple[bool, list[str], list[str], float]:
    if not _t(c, "food_poison"):
        return False, [], [], 0.0
    return True, ["群体性食物中毒线索"], ["共同进食地点与食品"], 0.9


def _campus(c: dict[str, Any]) -> tuple[bool, list[str], list[str], float]:
    if not _t(c, "campus_risk"):
        return False, [], [], 0.0
    return True, ["校园安全隐患线索"], ["学校名称", "是否涉暴恐"], 0.9


def _mass(c: dict[str, Any]) -> tuple[bool, list[str], list[str], float]:
    if not _t(c, "gather"):
        return False, [], [], 0.0
    hits = ["聚集/维权/群体性苗头"]
    score = 3
    if _crowd(c) >= 10:
        hits.append(f"涉及 {_crowd(c)} 人")
        score += 2
    if _t(c, "wage_dispute", "demolition"):
        hits.append("敏感诉求（讨薪/征地）")
        score += 2
    if _emo(c, "angry", "despair"):
        hits.append("伴随愤怒/绝望情绪")
        score += 2
    return True, hits, ["人数与地点", "是否有牵头人"], min(0.96, 0.45 + score * 0.06)


def _rumor(c: dict[str, Any]) -> tuple[bool, list[str], list[str], float]:
    if not _t(c, "rumor_panic"):
        return False, [], [], 0.0
    hits = ["谣言/恐慌信息"]
    score = 2
    if _emo(c, "panic"):
        hits.append("情绪恐慌")
        score += 2
    if any(k in c["text"] for k in ("抢购", "囤", "赶紧去买")):
        hits.append("出现抢购/囤积信号")
        score += 2
    if c.get("crowd"):
        hits.append(f"涉及 {c['crowd']} 人")
        score += 1
    return True, hits, ["信息来源平台与账号"], min(0.94, 0.4 + score * 0.07)


def _elderly(c: dict[str, Any]) -> tuple[bool, list[str], list[str], float]:
    if not _t(c, "elderly_lonely"):
        return False, [], [], 0.0
    hits = ["独居/空巢老人急难"]
    score = 2
    if _t(c, "medical_critical", "medical_shortage"):
        hits.append("涉医/涉药")
        score += 2
    if _emo(c, "urgent", "despair"):
        hits.append("情绪急迫")
        score += 1
    return True, hits, ["老人年龄与基础病"], min(0.92, 0.4 + score * 0.07)


def _shortage(c: dict[str, Any]) -> tuple[bool, list[str], list[str], float]:
    if not _t(c, "medical_shortage", "supply_shortage"):
        return False, [], [], 0.0
    # 普通"买不到"只是三级工单；只有叠加恐慌/抢购信号才算舆情风险（二级）
    if not (_emo(c, "panic", "urgent") or any(k in c["text"] for k in ("抢购", "囤", "断货", "疯抢"))):
        return False, [], [], 0.0
    hits = ["物资/药品短缺"]
    score = 2
    if _emo(c, "panic", "urgent"):
        hits.append("情绪急迫/恐慌")
        score += 2
    return True, hits, ["短缺范围与时长"], min(0.9, 0.4 + score * 0.07)


def _wage(c: dict[str, Any]) -> tuple[bool, list[str], list[str], float]:
    if not _t(c, "wage_dispute"):
        return False, [], [], 0.0
    # 单个欠薪诉求走三级工单；只有叠加聚集/多人/愤怒情绪才算群体风险（二级）
    if not (_t(c, "gather") or _crowd(c) >= 10 or _emo(c, "angry", "despair")):
        return False, [], [], 0.0
    hits = ["欠薪诉求"]
    score = 2
    if _t(c, "gather"):
        hits.append("有聚集倾向")
        score += 2
    if _crowd(c) >= 10:
        hits.append(f"涉及 {_crowd(c)} 人")
        score += 2
    return True, hits, ["企业名称与项目"], min(0.92, 0.4 + score * 0.06)


def _secondary(c: dict[str, Any]) -> tuple[bool, list[str], list[str], float]:
    # 情绪强烈 + 诉求本身非紧急 → 有次生舆情风险
    strong = _emo(c, "angry", "despair", "panic")
    if not strong:
        return False, [], [], 0.0
    if _t(c, "life_danger", "medical_critical", "gas_fire", "collapse", "hazmat", "food_poison"):
        return False, [], [], 0.0
    return (True,
            [f"强烈情绪（{'/'.join(k for k in ('angry', 'despair', 'panic') if k in c['emotions'])}）"],
            ["诉求背后是否涉及处置不当"], 0.7)


def screen(ctx: dict[str, Any]) -> dict[str, Any]:
    risks: list[dict[str, Any]] = []
    partial: list[dict[str, Any]] = []
    cleared: list[str] = []
    for rule in RULES:
        try:
            hit, hits, missing, conf = rule["test"](ctx)
        except Exception:
            hit, hits, missing, conf = False, [], [], 0.0
        if hit:
            risks.append({
                "id": rule["id"], "name": rule["name"], "tier": rule["tier"],
                "weight": rule["weight"], "dept": rule["dept"],
                "risky": rule["risky"], "window": rule["window"],
                "hits": hits, "ask": rule["ask"], "action": rule["action"],
                "confidence": round(conf, 2), "soft": rule.get("soft", False),
                "missing": missing,
            })
            if missing:
                partial.append({"id": rule["id"], "name": rule["name"],
                                "missing": missing, "confidence": round(conf, 2)})
        else:
            cleared.append(rule["name"])

    risks.sort(key=lambda r: (1 if r["soft"] else 0, r["tier"], -r["weight"]))
    hard = [r for r in risks if not r["soft"]]

    if hard and any(r["weight"] >= 95 for r in hard):
        headline = f"红色警报：触发 {len(hard)} 项高危风险，最高「{hard[0]['name']}」，立即处置"
    elif hard:
        headline = f"橙色预警：触发 {len(hard)} 项风险（{hard[0]['name']}），快速响应"
    else:
        soft = [r for r in risks if r["soft"]]
        if soft:
            headline = f"未见高危风险：{len(soft)} 项次生舆情提示待关注"
        else:
            headline = f"未见高危风险：已排查 {len(RULES)} 类社会风险"

    return {
        "risks": risks,
        "hard_risks": hard,
        "partial": partial,
        "screened": len(RULES),
        "cleared": cleared,
        "max_tier": min((r["tier"] for r in hard), default=9),
        "headline": headline,
    }
