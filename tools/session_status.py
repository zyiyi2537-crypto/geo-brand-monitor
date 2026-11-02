"""Login-check presentation and readiness rules shared by the GUI and runner."""
from __future__ import annotations


def session_ready(item: dict) -> bool:
    return (item.get("status") == "ok" and item.get("logged_in") is True
            and item.get("ready", True) is True)


def session_label(item: dict) -> str:
    if session_ready(item):
        return "对话页面可用" if item.get("verification_method") == "page_input" else "已确认登录"
    return {
        "missing": "未保存登录态", "invalid_file": "登录态文件无效",
        "expired": "未登录／已失效", "challenge": "需要安全验证",
        "unavailable": "已登录·页面未就绪", "timeout": "检测超时·请重试",
        "error": "检测失败·请重试",
    }.get(item.get("status"), "无法确认·请重试")


def complete_session_results(payload: list, engines) -> dict[str, dict]:
    by_engine = {item.get("engine"): item for item in payload if isinstance(item, dict)
                 and isinstance(item.get("engine"), str)}
    return {engine: by_engine.get(engine, {
        "engine": engine, "status": "unknown", "logged_in": None,
        "detail": "服务未返回该平台的登录检查结果，请重试检查",
    }) for engine in engines}
