"""LLM client — 单 provider 直连方案,通过 LLM_PROVIDER env 切换.

设计:
- 默认走 GLM(智谱 AI),OpenAI 兼容端点 https://open.bigmodel.cn/api/paas/v4/.
- 切到其它后端只需 `export LLM_PROVIDER=deepseek` / `qwen` / `openai`,以及在 .env
  配相应 *_API_KEY.
- 不做 fallback / 兜底.失败抛原生 openai SDK 异常,上层(service.py 的 _wrap)
  统一包成 sentinel "failed" + error category.

为什么不用兜底:
- 兜底链路放大故障表面(GLM 限速 → OpenAI 网络 → Qwen 欠费,任一坏了都误导排障).
- 切 provider 是运维决策(账号充值 / 切换), runtime 不应该自作主张.
"""
from __future__ import annotations

import logging
import os
import random
import time
from pathlib import Path
from typing import Any

import httpx
import openai

log = logging.getLogger("sentinel.llm")

# 同 provider 内的 RateLimit 退避策略(免费档 RPM 限速很常见,GLM 1302 / DashScope
# Throttling 等都走这条路).不是跨 provider fallback — 单 provider 仍是单 provider.
_RATE_LIMIT_RETRIES = 5
_RATE_LIMIT_BASE_WAIT = 6.0  # 秒,首次等待;之后指数退避 + jitter


# ───────────────────── env bootstrap ─────────────────────
# 启动 sentinel-service 的 shell 可能没把仓库 .env 的 key 暴露到 env 里;
# 主动从仓库 root .env 读一份(只在 env 缺失时补,不覆盖外部已设值).
def _bootstrap_env_from_dotenv() -> None:
    try:
        from dotenv import dotenv_values
    except ImportError:
        return
    here = Path(__file__).resolve()
    for parent in here.parents:
        envf = parent / ".env"
        if not envf.exists():
            continue
        try:
            vals = dotenv_values(envf)
        except Exception:  # noqa: BLE001
            return
        for k in (
            "LLM_PROVIDER",
            "GLM_API_KEY", "GLM_BASE_URL",
            "QWEN_API_KEY", "QWEN_BASE_URL",
            "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL",
            "OPENAI_API_KEY", "OPENAI_BASE_URL",
            # 搜索相关 env(国内机房 fallback / cookie)
            "DDG_REMOTE_URL", "DDG_REMOTE_TOKEN",
            "DDGS_BACKENDS", "DDGS_TIMEOUT_S",
            "BAIDU_COOKIE",
            "SEARXNG_URL",
            "HTTP_PROXY", "HTTPS_PROXY",
        ):
            if not os.environ.get(k) and vals.get(k):
                os.environ[k] = vals[k]
        return


# ───────────────────── provider 配置 ─────────────────────
# 改默认 provider:export LLM_PROVIDER=deepseek (或 qwen / openai)
# 改默认模型:export <PROVIDER>_MODEL=xxx 例如 GLM_MODEL=glm-4-plus
_PROVIDERS: dict[str, dict[str, Any]] = {
    "glm": {
        "key_env":    "GLM_API_KEY",
        "base_url":   "https://open.bigmodel.cn/api/paas/v4/",
        "model_env":  "GLM_MODEL",
        "default_model": "glm-4.5-flash",
        "use_proxy":  False,
    },
    "deepseek": {
        "key_env":    "DEEPSEEK_API_KEY",
        "base_url":   "https://api.deepseek.com/v1",
        "model_env":  "DEEPSEEK_MODEL",
        "default_model": "deepseek-chat",
        "use_proxy":  False,
    },
    "qwen": {
        "key_env":    "QWEN_API_KEY",
        "base_url":   "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model_env":  "QWEN_MODEL",
        "default_model": "qwen-plus",
        "use_proxy":  False,
    },
    "openai": {
        "key_env":    "OPENAI_API_KEY",
        "base_url":   None,  # SDK 默认 https://api.openai.com/v1
        "model_env":  "OPENAI_MODEL",
        "default_model": "gpt-4o-mini",
        "use_proxy":  True,   # 国内直连不通,必须走 HTTPS_PROXY
    },
}


def _provider() -> str:
    name = (os.environ.get("LLM_PROVIDER") or "glm").lower()
    if name not in _PROVIDERS:
        raise RuntimeError(
            f"unknown LLM_PROVIDER={name!r}. valid: {sorted(_PROVIDERS)}"
        )
    return name


def _provider_cfg() -> dict[str, Any]:
    return _PROVIDERS[_provider()]


# ───────────────────── http client(代理策略) ─────────────────────
# 仓库环境 ALL_PROXY=socks5://...(httpx 默认会读)需要 socksio 包,我们不装;
# 所以全部 trust_env=False.OpenAI 在国内连不通,因此 use_proxy=True 时显式
# 注入 HTTP(S)_PROXY 给底层 httpx.
def _http_client(use_proxy: bool) -> httpx.Client:
    timeout = httpx.Timeout(60.0, connect=10.0)
    if not use_proxy:
        return httpx.Client(trust_env=False, timeout=timeout)
    proxy = (
        os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        or os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
        or os.environ.get("PROXY_URL")
    )
    if proxy and proxy.startswith(("http://", "https://")):
        return httpx.Client(trust_env=False, proxy=proxy, timeout=timeout)
    return httpx.Client(trust_env=False, timeout=timeout)


# ───────────────────── client 构造 ─────────────────────
def make_client() -> openai.OpenAI:
    cfg = _provider_cfg()
    api_key = os.environ.get(cfg["key_env"])
    if not api_key:
        raise RuntimeError(
            f"LLM_PROVIDER={_provider()} but {cfg['key_env']} is not set"
        )
    kwargs: dict[str, Any] = {"api_key": api_key, "http_client": _http_client(cfg["use_proxy"])}
    if cfg.get("base_url"):
        kwargs["base_url"] = cfg["base_url"]
    return openai.OpenAI(**kwargs)


def _model() -> str:
    cfg = _provider_cfg()
    return os.environ.get(cfg["model_env"]) or cfg["default_model"]


# ───────────────────── 对外 API ─────────────────────
def chat_create(_legacy_default_model: str = "", **kwargs: Any):
    """chat.completions.create 的 thin wrapper.

    _legacy_default_model 仅为兼容现有调用点签名(plan / analyze / brief / draft
    内部传的 'gpt-4o-mini' 之类),实际 model 由 LLM_PROVIDER + *_MODEL env 决定.
    其余参数(messages / response_format / max_completion_tokens / ...) 透传.

    撞 RateLimit 时做有限次指数退避重试,再抛.batch 调用方(analyze 循环 N 篇)
    应该额外在外层加节流,避免 burst 把每分钟 RPM 全打光.
    """
    kwargs.pop("model", None)
    client = make_client()
    last_exc: openai.RateLimitError | None = None
    for attempt in range(_RATE_LIMIT_RETRIES + 1):
        try:
            return client.chat.completions.create(model=_model(), **kwargs)
        except openai.RateLimitError as e:
            last_exc = e
            if attempt == _RATE_LIMIT_RETRIES:
                break
            wait = _RATE_LIMIT_BASE_WAIT * (2 ** attempt) + random.uniform(0, 1.0)
            log.warning(
                "%s/%s rate-limited (%s) — backoff %.1fs (attempt %d/%d)",
                _provider(), _model(), e, wait, attempt + 1, _RATE_LIMIT_RETRIES,
            )
            time.sleep(wait)
    assert last_exc is not None
    raise last_exc


# 兼容性 — 现有调用点之前用 has_openai/has_qwen 做"key 是否就绪"判断,
# 现在改成"当前选中的 provider 是否可用".
def has_llm() -> bool:
    try:
        cfg = _provider_cfg()
    except RuntimeError:
        return False
    return bool(os.environ.get(cfg["key_env"]))


# 为兼容 search/plan.py 等地的 has_openai / has_qwen 调用,保留这两个名:
# 二者现在都等价 has_llm()(单 provider 模式不区分).
has_openai = has_llm
has_qwen = has_llm


_bootstrap_env_from_dotenv()
