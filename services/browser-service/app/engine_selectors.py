"""引擎选择器/参数配置(外置)—— browser-agent 自愈 Phase 1。

各引擎的 input/send/answer 选择器、completion API、首页 URL 都从这里取,不再硬编码,
这样引擎改版时改配置即可(可经 ENGINE_SELECTORS_FILE 覆盖、运行时热更),不用改代码
重部署 5 台;也是 Phase 2(LLM 自愈)的写入目标。

读取顺序:内置默认 ← ENGINE_SELECTORS_FILE(JSON,按引擎合并覆盖)。
"""
from __future__ import annotations

import json
import os

_DEFAULTS: dict = {
    "qwen": {
        "url": "https://www.qianwen.com/",
        "input_sels": [
            "div[contenteditable='true'][role='textbox']",
            "div[contenteditable='true']",
            "textarea",
        ],
        "send_sels": [
            "button[aria-label*='发送']",
            "button[aria-label*='Send']",
            "button[class*='send']",
        ],
        "answer_sels": [
            "[data-chat-answers-wrap]",
            ".chat-answers-card-wrap",
            ".answer-common-card",
            "[class*='answer']",
            "[class*='markdown']",
        ],
        # 联网引用所在 completion SSE API(子串匹配 response.url)
        "chat_api": "chat2.qianwen.com/api/v2/chat",
    },
}

_OVERRIDE_PATH = os.environ.get("ENGINE_SELECTORS_FILE", "").strip()
# 中心配置(后端服务):自愈 apply 写到后端,各 worker 据此 URL 拉取 → 改版修复自动覆盖全队。
_CENTRAL_URL = os.environ.get("ENGINE_SELECTORS_URL", "").strip()


def _fetch_central() -> dict:
    if not _CENTRAL_URL:
        return {}
    try:
        import urllib.request
        with urllib.request.urlopen(_CENTRAL_URL, timeout=5) as r:
            return json.loads(r.read().decode("utf-8")) or {}
    except Exception:  # noqa: BLE001
        return {}


def get(engine: str) -> dict:
    """取某引擎的选择器配置:内置默认 ← 本地覆盖文件 ← 中心配置(后端,自愈写入)。"""
    cfg = {k: (list(v) if isinstance(v, list) else v)
           for k, v in _DEFAULTS.get(engine, {}).items()}
    if _OVERRIDE_PATH and os.path.exists(_OVERRIDE_PATH):
        try:
            with open(_OVERRIDE_PATH, encoding="utf-8") as f:
                ov = json.load(f)
            if isinstance(ov.get(engine), dict):
                cfg.update(ov[engine])
        except Exception:  # noqa: BLE001
            pass
    central = _fetch_central()
    if isinstance(central.get(engine), dict):
        cfg.update(central[engine])
    return cfg
