"""全局配置：路径、端口、政务响应等级标签。"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = BASE_DIR / "app"
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
DATA_FILE = DATA_DIR / "state.json"

VERSION = "1.0.0"
SYSTEM_NAME = "GovOS"
SYSTEM_SUB = "社会治理诉求分流中枢"
DISCLAIMER = "演示原型：仅用于流程演练，不构成真实政务处置依据，不替代人工审批。"

HOST = os.environ.get("GOV_HOST", "127.0.0.1")
PORT = int(os.environ.get("GOV_PORT", "8780"))

MONITOR_TICK = float(os.environ.get("GOV_TICK", "3"))

# 政务响应等级（1 最紧急）
LEVEL_LABEL = {
    1: "一级响应 · 立即处置",
    2: "二级响应 · 快速响应",
    3: "三级响应 · 工单派发",
    4: "四级响应 · 自动答复",
}
LEVEL_COLOR = {1: "#b91c1c", 2: "#ea580c", 3: "#ca8a04", 4: "#2563eb"}
LEVEL_ROUTE = {
    1: "转 120 / 110 / 119 + 属地立即到场",
    2: "转 宣传部 / 网信办 / 政法（含属地）",
    3: "派发责任部门工单，限时办理",
    4: "自动答复闭环，可自助查询",
}
LEVEL_SLA = {1: 0, 2: 10, 3: 30, 4: 120}

# 大模型（混合架构）——不配置也能跑，纯规则兜底
LLM_API_KEY = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
