"""底座一：政务诉求语义库 —— 把市民的"大白话"翻成标准的诉求类型与风险标签。

与急诊版同构：词典数据 + 抽取算法分离；长词优先；同时抓三样关键信息：
  1. 诉求类型（求助 / 投诉 / 咨询 / 风险线索）；
  2. 情绪（恐慌 / 愤怒 / 绝望 / 焦急）；
  3. 位置与涉及人数（这是政务版比临床版多出来的"地址"能力）。

注：仅用于流程演示，不构成真实政务处置依据。
"""
from __future__ import annotations

import re
from typing import Any

# ======================================================================
# 一、诉求类型词典
#   id     : 内部主键
#   name   : 标准诉求名
#   lay    : 市民可能说的口语
#   cat    : 求助 / 投诉 / 咨询 / 风险
#   urgent : 0 一般 / 1 需关注 / 2 紧急 / 3 极紧急（兜底排序用）
# ======================================================================
APPEAL_TYPES: list[dict[str, Any]] = [
    # ---------------- 求助：生命与安全 ----------------
    {"id": "medical_critical", "name": "重症就医求助", "cat": "求助", "urgent": 3,
     "lay": ["老人发烧喘不上气", "老人喘不上气", "发烧喘不上气", "断氧", "氧气没了", "呼吸机坏了",
             "重症挂不上号", "挂不上号", "孕妇要生了", "快生了", "孩子高烧抽搐", "小孩抽搐",
             "老人心脏病犯了", "晕倒", "昏迷不醒", "出血不止", "救命", "快不行了"]},
    {"id": "gas_fire", "name": "燃气泄漏/火灾隐患", "cat": "求助", "urgent": 3,
     "lay": ["燃气味", "煤气味", "漏气", "闻到煤气", "着火了", "起火了", "冒烟", "烧起来了",
             "电线打火", "电表冒火花"]},
    {"id": "collapse", "name": "房屋坍塌/地质灾害隐患", "cat": "求助", "urgent": 3,
     "lay": ["墙裂了", "房子要塌", "房塌了", "塌方", "地陷", "山体滑坡", "危房", "裂缝越来越大"]},
    {"id": "hazmat", "name": "危化品泄漏/爆炸", "cat": "求助", "urgent": 3,
     "lay": ["化工泄漏", "化学品泄漏", "毒气", "刺鼻气味", "爆炸了", "油罐车翻了", "氯气味"]},
    {"id": "food_poison", "name": "群体食物中毒", "cat": "求助", "urgent": 3,
     "lay": ["一群人拉肚子", "好多人拉肚子", "集体拉肚子", "吃了都吐", "食堂吃坏肚子", "集体食物中毒"]},
    {"id": "missing_person", "name": "走失/失联求助", "cat": "求助", "urgent": 2,
     "lay": ["老人走丢", "老人走失", "孩子找不到了", "老人找不到了", "失联", "联系不上",
             "两天没回家了", "孩子没回来"]},
    {"id": "extreme_weather", "name": "极端天气被困", "cat": "求助", "urgent": 2,
     "lay": ["暴雨被困", "被水困住", "积水到腰", "家里进水了", "车被淹了", "山洪", "道路塌方被困"]},
    {"id": "medical_shortage", "name": "药品/物资短缺", "cat": "求助", "urgent": 2,
     "lay": ["买不到退烧药", "退烧药", "买不到药", "缺药", "断药", "退烧药断货", "买不到口罩", "药房没货",
             "药都卖完", "卖完了", "慢性病药断了", "胰岛素买不到"]},
    {"id": "supply_shortage", "name": "生活物资/水电短缺", "cat": "求助", "urgent": 1,
     "lay": ["买不到菜", "断粮", "没菜了", "停水了", "停电了", "没水没电", "好几天没电"]},
    {"id": "elderly_lonely", "name": "独居老人急难", "cat": "求助", "urgent": 2,
     "lay": ["独居老人", "老人一个人在家", "空巢老人", "老人没人管", "老人摔倒了", "老人发烧没人照顾"]},
    # ---------------- 风险线索 ----------------
    {"id": "infectious_cluster", "name": "传染病聚集性线索", "cat": "风险", "urgent": 3,
     "lay": ["好多人发烧", "小区很多人发烧", "好多人咳嗽", "集体发热", "一片人感冒", "都开始发烧了",
             "班里一半人请假", "厂里好多人发热"]},
    {"id": "rumor_panic", "name": "谣言/恐慌信息", "cat": "风险", "urgent": 2,
     "lay": ["谣言", "造谣", "传谣", "听人说", "网上说", "都在传", "是不是真的", "抢购", "恐慌",
             "大家都去买", "快囤", "煽动", "带节奏", "别有用心"]},
    {"id": "gather", "name": "聚集维权/群体事件苗头", "cat": "风险", "urgent": 2,
     "lay": ["上访", "聚集", "维权", "讨说法", "讨薪", "堵门", "拉横幅", "罢工", "抗议",
             "集体", "一群人要去", "集合", "静坐", "围堵"]},
    {"id": "campus_risk", "name": "校园安全隐患", "cat": "风险", "urgent": 2,
     "lay": ["校园欺凌", "校园霸凌", "学生打架", "学校门口", "带刀", "扬言报复", "涉恐涉暴"]},
    {"id": "safety_hazard", "name": "安全生产隐患", "cat": "风险", "urgent": 2,
     "lay": ["脚手架", "安全隐患", "特种设备", "电梯困人", "消防通道堵", "灭火器过期", "高空坠物"]},
    # ---------------- 投诉举报 ----------------
    {"id": "price_gouging", "name": "哄抬物价投诉", "cat": "投诉", "urgent": 1,
     "lay": ["涨价", "天价", "哄抬物价", "坐地起价", "贵得离谱", "翻倍卖", "发国难财"]},
    {"id": "wage_dispute", "name": "欠薪/劳资纠纷", "cat": "投诉", "urgent": 1,
     "lay": ["拖欠工资", "欠薪", "不发工资", "讨要工钱", "干了活不给钱", "农民工工资"]},
    {"id": "demolition", "name": "征地拆迁诉求", "cat": "投诉", "urgent": 1,
     "lay": ["强拆", "征地", "拆迁补偿", "补偿太低", "拆迁款", "钉子户"]},
    {"id": "environment", "name": "环境污染投诉", "cat": "投诉", "urgent": 1,
     "lay": ["噪音", "太吵", "噪声扰民", "排污", "污水", "臭气", "异味", "烟囱冒黑烟", "扬尘"]},
    {"id": "property", "name": "物业管理诉求", "cat": "投诉", "urgent": 0,
     "lay": ["物业不作为", "物业不管", "电梯坏了", "垃圾没人清", "楼道堆物", "停车位", "漏水没人修"]},
    {"id": "traffic", "name": "市政设施诉求", "cat": "投诉", "urgent": 0,
     "lay": ["路灯坏了", "井盖没了", "道路积水", "路面坑", "红绿灯不亮", "断头路"]},
    # ---------------- 咨询 ----------------
    {"id": "policy", "name": "政策咨询", "cat": "咨询", "urgent": 0,
     "lay": ["医保怎么报", "医保报销", "医保", "报销", "怎么报销", "报销流程", "报销材料", "需要什么材料",
             "异地医保", "异地报销", "补贴怎么领", "落户", "入学政策", "公积金", "养老", "办证",
             "怎么办手续", "政策", "规定是什么", "能报销吗", "有哪些补贴"]},
]

# 情绪词典
EMOTIONS: list[dict[str, Any]] = [
    {"id": "panic", "name": "恐慌", "lay": ["吓死了", "恐慌", "害怕", "要命了", "怎么办啊", "慌了",
                                        "天塌了", "人心惶惶", "太可怕了", "会不会死"]},
    {"id": "angry", "name": "愤怒", "lay": ["投诉", "举报", "气死", "骗人", "混蛋", "讨说法", "凭什么",
                                        "太过分", "坑人", "不作为", "糊弄", "糊弄人"]},
    {"id": "despair", "name": "绝望", "lay": ["活不下去", "没希望", "绝望", "轻生", "不想活", "走投无路",
                                         "没活路", "活不了了"]},
    {"id": "urgent", "name": "焦急", "lay": ["急", "快点", "救命", "立刻", "马上", "等不及", "火烧眉毛",
                                        "十万火急"]},
]

# 地址/位置抽取
LOCATION_RE = re.compile(
    r"([\u4e00-\u9fa5]{1,12}?(?:小区|花园|苑|家园|社区|街道|镇|乡|村|路|街|号楼|号楼栋|栋|单元|组团|广场|大厦|工业园|产业园|组|弄|里))"
    r"|([\u4e00-\u9fa5]{1,8}[区县])"
)

# 涉及人数
CROWD_RE = re.compile(r"(\d+|[一二三四五六七八九十百]+)\s*(?:人|个|户|名|口子)")
CROWD_LOOSE = [("一群人", 10), ("几十人", 30), ("上百人", 100), ("好多人", 20), ("很多人", 20), ("几百人", 300)]


def clean(text: str) -> str:
    if not text:
        return ""
    table = str.maketrans("０１２３４５６７８９．，：；／％", "0123456789.,:;/%")
    return text.translate(table).replace("\u3000", " ").strip()


def _crowd_value(s: str) -> int:
    digits = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
              "十": 10, "百": 100}
    if s.isdigit():
        return int(s)
    val = 0
    for ch in s:
        if ch in digits:
            val += digits[ch]
    return max(1, val)


def normalize_text(text: str) -> dict[str, Any]:
    """市民原话 → 诉求类型 + 情绪 + 位置/人数。"""
    text = clean(text)
    findings: list[dict[str, Any]] = []
    translation: list[dict[str, str]] = []
    emotions: list[dict[str, str]] = []
    if not text:
        return {"findings": findings, "translation": translation, "emotions": emotions,
                "location_bits": [], "crowd": 0}

    clauses = [c for c in re.split(r"[，,。.;；!！?？\n\r、]+", text) if c.strip()]
    seen_types: set[str] = set()
    for clause in clauses:
        for entry in sorted(APPEAL_TYPES, key=lambda e: max(len(x) for x in e["lay"]), reverse=True):
            for phrase in sorted(entry["lay"], key=len, reverse=True):
                idx = clause.find(phrase)
                if idx < 0 or entry["id"] in seen_types:
                    continue
                seen_types.add(entry["id"])
                findings.append({
                    "id": entry["id"], "name": entry["name"], "cat": entry["cat"],
                    "urgent": entry["urgent"], "phrase": phrase, "clause": clause[:40],
                })
                translation.append({"lay": clause[:24] + ("…" if len(clause) > 24 else ""), "term": entry["name"]})
                break

    for e in EMOTIONS:
        if any(k in text for k in e["lay"]):
            emotions.append({"id": e["id"], "name": e["name"]})

    # 位置
    location_bits: list[str] = []
    for m in LOCATION_RE.finditer(text):
        bit = m.group(1) or m.group(2)
        if bit and bit not in location_bits:
            location_bits.append(bit)

    # 人数
    crowd = 0
    for phrase, n in CROWD_LOOSE:
        if phrase in text:
            crowd = max(crowd, n)
    m = CROWD_RE.search(text)
    if m:
        crowd = max(crowd, _crowd_value(m.group(1)))

    return {
        "findings": findings, "translation": translation, "emotions": emotions,
        "location_bits": location_bits, "crowd": crowd,
    }


def build_context(payload: dict[str, Any]) -> dict[str, Any]:
    text = clean(str(payload.get("text") or ""))
    analyzed = normalize_text(text)
    location = clean(str(payload.get("location") or ""))
    crowd_form = payload.get("crowd")
    try:
        crowd_form = int(crowd_form) if crowd_form not in (None, "") else 0
    except (TypeError, ValueError):
        crowd_form = 0

    return {
        "name": (payload.get("name") or "匿名市民").strip()[:20],
        "phone": clean(str(payload.get("phone") or ""))[:20],
        "location": location or ("、".join(analyzed["location_bits"]) or "未明确"),
        "source": payload.get("source") or "12345 热线",
        "crowd": crowd_form or analyzed["crowd"],
        "text": text,
        "terms": {f["id"] for f in analyzed["findings"]},
        "emotions": {e["id"] for e in analyzed["emotions"]},
        "findings": analyzed["findings"],
        "translation": analyzed["translation"],
        "emotion_list": analyzed["emotions"],
        "location_bits": analyzed["location_bits"],
        "has_location": bool(location or analyzed["location_bits"]),
        "has_phone": bool(payload.get("phone")),
    }
