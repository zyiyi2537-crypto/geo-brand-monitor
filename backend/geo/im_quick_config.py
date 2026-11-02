"""IM 快捷菜单/按钮的默认值 + connector.config_json 解析。

**无 pydantic-ai / agent 依赖**,主后端(geo.api.account)与 agent 服务(geo.agent.embed.*)都可 import。
config_json 结构:{"agentid": "...", "quick_actions": [["标签","问句"],...], "menu_map": {"event_key":"问句"}}
"""
from __future__ import annotations

import json

# 回复底部快捷按钮默认值(label, 点击发送的问句)
DEFAULT_QUICK_ACTIONS: list[list[str]] = [
    ["📈 投放进展", "今日投放进展和效果如何?"],
    ["📰 今日舆情", "今天舆情怎么样?"],
    ["🔍 舆情分析", "最近有哪些负面舆情?帮我分析一下趋势"],
    ["🎯 GEO 检测", "我最新的 GEO 诊断报告结果如何?"],
]

# 飞书机器人底部菜单 event_key → 问句 默认值("__help__" = 弹全部功能清单)
DEFAULT_MENU_MAP: dict[str, str] = {
    "today": "今日投放效果如何?",
    "coverage": "我累计被搜到几个问题?",
    "unhit": "哪些 query 没命中?",
    "sentiment": "今天舆情怎么样?",
    "articles": "文章发布进度如何?",
    "help": "__help__",
    "menu": "__help__",
}

MAX_QUICK_ACTIONS = 6


def parse_config(config_json) -> dict:
    """把 config_json(str 或 dict 或 None)解析成 dict;坏数据返回 {}。"""
    if isinstance(config_json, dict):
        return config_json
    try:
        cfg = json.loads(config_json) if config_json else {}
    except (ValueError, TypeError):
        cfg = {}
    return cfg if isinstance(cfg, dict) else {}


def quick_actions(config_json) -> list[tuple[str, str]]:
    """取该连接器的快捷按钮 [(label, query), ...];未配则返回默认。"""
    cfg = parse_config(config_json)
    raw = cfg.get("quick_actions")
    out: list[tuple[str, str]] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                label, q = str(item[0]).strip(), str(item[1]).strip()
                if label and q:
                    out.append((label, q))
    out = out[:MAX_QUICK_ACTIONS]
    return out or [(l, q) for l, q in DEFAULT_QUICK_ACTIONS]


def menu_map(config_json) -> dict[str, str]:
    """取该连接器的飞书菜单映射 {event_key: query};未配则返回默认。"""
    cfg = parse_config(config_json)
    raw = cfg.get("menu_map")
    out: dict[str, str] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            if str(k).strip() and str(v).strip():
                out[str(k).strip()] = str(v).strip()
    return out or dict(DEFAULT_MENU_MAP)
