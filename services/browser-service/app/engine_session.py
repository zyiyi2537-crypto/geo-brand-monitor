"""EngineSession — D4 hot browser model.

每个 EngineSession 持有一对长期(page, ctx) + 一条 pool session 的绑定关系.
query() 在已加载好的 page 上跑 (reset chat → input → wait → extract),
不再每次 launch + goto + setup,节省 ~10-15s per query.

Lifecycle:
  worker startup → instantiate EngineSession 给每个 engine → init() 检出 session
                                                             + launch browser
                                                             + 跑准备步骤
  per query     → query(text) 复用 hot (page, ctx),返回 EngineResult
  session 翻车  → rotate(reason: FailureType) close + check-in 老 + check-out 新 + 重 init
  worker shutdown → close() 关 browser + check-in session

并发安全:每个 EngineSession 内部有 asyncio.Lock,同一 instance 同一时刻只跑 1 个
query.要并发需要 M 个 instance 组成 pool(D7 P3 = C 阶段).

适配协议:engine adapter 要提供两个新方法:
  - _prepare_page(page, ctx) → None  (goto, banner, smart search toggle 等"准备好"工作)
  - _query_with_page(page, ctx, query) → EngineResult  (reset + input + wait + extract)
若 adapter 没实现,EngineSession.init() 会 raise NotImplementedError.

D4 POC 只接 deepseek,其他 4 个 engine 沿用旧的 search() 一次性流程.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Optional

from .browser import create_stealth_page
from .engines.base import EngineAdapter, EngineResult
from .session_store import (
    report_session_outcome, get_local_account_count, has_local_accounts,
    get_last_local_account_id, is_local_account_available,
)


_log = logging.getLogger(__name__)

# 登录态失效 / DOM 失效时,自动 rotate(换号)并重试的次数。设 0 关闭"失败即换"。
# 默认 1:坏掉的 hot session 自动 check-in + 换一条新 session 重试一次。
AUTO_ROTATE_RETRY = int(os.environ.get("BROWSER_AUTO_ROTATE_RETRY", "1"))
# 定期轮换:每成功跑 N 条 query 就主动 rotate 一次,让池里账号轮流上、单号不过劳
# (单号被打几百次最容易触发风控 / 登录态失效)。设 0 关闭定期轮换。
ROTATE_EVERY_N = int(os.environ.get("BROWSER_ROTATE_EVERY_N", "30"))
# IP 熔断:连续换了这么多个"新号还是立刻失败"→ 判定不是账号问题(多半 IP 被封 /
# 引擎挂了),停止换号(避免把所有账号一起喂进黑名单),进入退避只用当前号低频探活。
IP_BAN_ROTATE_FAILS = int(os.environ.get("BROWSER_IP_BAN_ROTATE_FAILS", "3"))
# 熔断后退避秒数;期间不 rotate,仍用当前 session 探活,成功即恢复。默认 15 分钟。
BREAKER_COOLDOWN_SEC = float(os.environ.get("BROWSER_BREAKER_COOLDOWN_SEC", "900"))
# 哪些失败类型触发自动 rotate —— 只对"换个账号就可能好"的失败自愈;
# captcha / timeout / crash 换号大概率也救不了,不浪费额度,留给隔离策略处理。
_ROTATE_ON = {"login_lost", "dom_not_found", "captcha", "rate_limited", "timeout", "empty_answer"}


class EngineSession:
    def __init__(self, engine_name: str, adapter: EngineAdapter):
        self.engine_name = engine_name
        self.adapter = adapter
        self.page = None
        self.ctx = None
        self.query_count = 0
        self.last_used_at: Optional[float] = None
        self._lock = asyncio.Lock()
        self._initialized = False
        # 距上次 rotate 已成功跑的 query 数(到 ROTATE_EVERY_N 触发定期轮换)
        self._queries_since_rotate = 0
        # 连续"换了新号还是立刻失败"的次数(到 IP_BAN_ROTATE_FAILS 触发 IP 熔断)
        self._rotate_fail_streak = 0
        # IP 熔断退避截止(epoch 秒);> now 时只探活不换号
        self._breaker_until = 0.0
        self._local_account_id: Optional[str] = None

    # ── Adapter capability check ─────────────────────────────────
    def _has_hot_protocol(self) -> bool:
        return (
            hasattr(self.adapter, "_prepare_page")
            and hasattr(self.adapter, "_query_with_page")
        )

    # ── Lifecycle ────────────────────────────────────────────────
    async def init(self) -> None:
        """Launch browser + load session + adapter._prepare_page.

        Adapter 可选实现 _create_hot_page(返回 (page, ctx))覆盖默认的
        create_stealth_page 调用 — 豆包必须用,因为它走 cloakbrowser + headed.
        """
        if not self._has_hot_protocol():
            raise NotImplementedError(
                f"engine {self.engine_name} 没实现 hot protocol "
                "(_prepare_page + _query_with_page)."
            )
        async with self._lock:
            if self._initialized:
                return
            if has_local_accounts(self.engine_name) and get_local_account_count(self.engine_name) <= 0:
                raise RuntimeError(f"{self.engine_name} 的所有本地账号都在冷却或需要重新登录")
            t0 = time.time()
            if hasattr(self.adapter, "_create_hot_page"):
                self.page, self.ctx = await self.adapter._create_hot_page()
            else:
                self.page, self.ctx = await create_stealth_page(self.engine_name)
            self._local_account_id = get_last_local_account_id(self.engine_name)
            await self.adapter._prepare_page(self.page, self.ctx)
            self._initialized = True
            _log.info("[hot-session] %s init OK in %.1fs", self.engine_name, time.time() - t0)

    async def query(self, query_text: str) -> EngineResult:
        """Reuse hot page to run one query.

        并发请求会串行化(_lock).调用前 init() 必须已完成,否则 raise.

        三层换号策略:
        1. 定期轮换(ROTATE_EVERY_N):每成功 N 条主动 rotate,让池里账号轮流上,
           单号不过劳——单号被打几百次最容易触发风控 / 登录态失效。
        2. 失败即换(AUTO_ROTATE_RETRY):login_lost / dom_not_found 时换一条新号重试,
           解决 hot session 登录态一死就干坐着每条都失败、永不自动换号的问题。
        3. IP 熔断(IP_BAN_ROTATE_FAILS):连续换了多个新号还是立刻失败 → 判定不是
           账号问题(多半 IP 被封 / 引擎挂了),停止换号(否则会把所有账号一起喂进
           黑名单),退避 BREAKER_COOLDOWN_SEC,期间只用当前号低频探活,成功即恢复。
        """
        if not self._initialized:
            await self.init()

        now = time.time()
        breaker_open = now < self._breaker_until
        if breaker_open:
            return EngineResult(
                engine=self.adapter.name, query=query_text,
                error="平台连续在多个账号上失败，已暂停请求以避免扩大风控；请稍后重试",
            )

        if (has_local_accounts(self.engine_name) and self._local_account_id
                and not is_local_account_available(self.engine_name, self._local_account_id)):
            if get_local_account_count(self.engine_name) <= 0:
                return EngineResult(
                    engine=self.adapter.name, query=query_text,
                    error="该平台账号均需重新登录或处于冷却，请在账号管理中检查状态",
                )
            await self.rotate(reason="account_unavailable")

        # 1) 定期轮换 —— 仅在健康(未熔断)时做
        local_pool_size = get_local_account_count(self.engine_name)
        rotate_every = 1 if local_pool_size > 1 else ROTATE_EVERY_N
        if rotate_every > 0 and self._queries_since_rotate >= rotate_every and not breaker_open:
            _log.info("[hot-session] %s periodic rotate after %d queries",
                      self.engine_name, self._queries_since_rotate)
            try:
                await self.rotate(reason="periodic")
                self._queries_since_rotate = 0
            except Exception as e:  # noqa: BLE001
                _log.warning("[hot-session] %s periodic rotate failed: %s", self.engine_name, e)

        attempts = AUTO_ROTATE_RETRY + 1
        result: Optional[EngineResult] = None
        rotated = False                                  # 本次调用是否真的换过号
        for attempt in range(attempts):
            result, fail_type = await self._query_once(query_text)
            if fail_type is None:                        # 成功
                self._queries_since_rotate += 1
                self._rotate_fail_streak = 0
                self._breaker_until = 0.0                # 探活成功 → 解除熔断
                return result
            if fail_type in {"captcha", "rate_limited", "timeout", "empty_answer"}:
                self._rotate_fail_streak += 1
                if self._rotate_fail_streak >= IP_BAN_ROTATE_FAILS:
                    self._breaker_until = time.time() + BREAKER_COOLDOWN_SEC
                    self._rotate_fail_streak = 0
                    _log.error(
                        "[hot-session] %s: 多个账号连续触发验证或限流，暂停请求 %.0f 秒",
                        self.engine_name, BREAKER_COOLDOWN_SEC,
                    )
                    return result
                if has_local_accounts(self.engine_name) and get_local_account_count(self.engine_name) > 0:
                    try:
                        await self.rotate(reason=fail_type)
                        self._queries_since_rotate = 0
                    except Exception as e:  # noqa: BLE001
                        _log.warning("[hot-session] %s cooldown rotate failed: %s", self.engine_name, e)
                return result
            if fail_type not in _ROTATE_ON:
                return result                            # 换号也救不了的失败 → 直接返回
            if attempt + 1 >= attempts:
                break                                    # 重试次数用尽
            _log.warning("[hot-session] %s %s on query, auto-rotating (attempt %d/%d)",
                         self.engine_name, fail_type, attempt + 1, attempts - 1)
            try:
                await self.rotate(reason=fail_type)
                self._queries_since_rotate = 0
                rotated = True
            except Exception as e:                       # noqa: BLE001
                _log.warning("[hot-session] %s auto-rotate failed: %s", self.engine_name, e)
                self._note_rotate_didnt_help()           # 换不出新号(池空/全死)
                return result
        # 换了号重试仍失败 → 这次换号没救活,累计;够多就熔断 IP
        if rotated:
            self._note_rotate_didnt_help()
        return result

    def _note_rotate_didnt_help(self) -> None:
        """记一次"换号也没救活";连续够 IP_BAN_ROTATE_FAILS 次 → 触发 IP 熔断."""
        self._rotate_fail_streak += 1
        if self._rotate_fail_streak >= IP_BAN_ROTATE_FAILS:
            self._breaker_until = time.time() + BREAKER_COOLDOWN_SEC
            self._rotate_fail_streak = 0
            _log.error(
                "[hot-session] %s: 连续 %d 次换号仍失败 —— 疑似 IP 被封 / 引擎挂了,"
                "熔断 %.0fs 停止换号(避免把所有账号一起喂进黑名单),期间仅探活.",
                self.engine_name, IP_BAN_ROTATE_FAILS, BREAKER_COOLDOWN_SEC,
            )

    async def _query_once(self, query_text: str) -> tuple[EngineResult, Optional[str]]:
        """跑一次 query(持 _lock).返回 (result, failure_type);成功时 failure_type=None.

        失败信号上报给 pool(check-in 记账,驱动 quarantine 策略)——保持原有口径:
        两条路径(result.error / 异常)都按 _classify_error 的类型上报池子,
        并把分类后的 failure_type 返给上层,供自动 rotate 判定.
        """
        async with self._lock:
            t0 = time.time()
            try:
                result = await self.adapter._query_with_page(self.page, self.ctx, query_text)
                self.query_count += 1
                self.last_used_at = time.time()
                _log.info(
                    "[hot-session] %s query #%d in %.1fs ans_len=%d err=%s",
                    self.engine_name, self.query_count, time.time() - t0,
                    len(result.answer or ""), result.error,
                )
                if result.error:
                    ft = _classify_error(result.error)
                    report_session_outcome(self.engine_name, result=ft)
                    return result, ft
                return result, None
            except Exception as e:
                _log.exception("[hot-session] %s query crashed: %s", self.engine_name, e)
                # 按异常消息分类上报(而非一律 'crash'),否则 adapter 抛的 login_lost /
                # dom_not_found 等信号丢失,池子无法按类型隔离(掉登录的坏会话会被重复抽到)。
                ft = _classify_error(str(e))
                report_session_outcome(self.engine_name, result=ft, error_msg=str(e))
                err = EngineResult(engine=self.adapter.name, query=query_text, error=str(e))
                return err, ft

    async def rotate(self, reason: str = "manual") -> None:
        """Close current ctx + check-in session + re-init with fresh session."""
        async with self._lock:
            _log.info("[hot-session] %s rotate reason=%s", self.engine_name, reason)
            await self._close_inner(check_in_result=reason)
            self._initialized = False
        # 退出 lock 再调 init(init 自己取 lock,避免死锁)
        await self.init()

    async def close(self) -> None:
        """Worker shutdown: close ctx + check-in session as SUCCESS."""
        async with self._lock:
            await self._close_inner(check_in_result="success")
            self._initialized = False

    async def _close_inner(self, check_in_result: str) -> None:
        if self.ctx is not None:
            try:
                # Adapter 可选实现 _close_hot_page(page, ctx) 处理 cloakbrowser 等
                # 特殊清理(豆包有 headed_browser + headed_pw 要 close).
                if hasattr(self.adapter, "_close_hot_page"):
                    await self.adapter._close_hot_page(self.page, self.ctx)
                else:
                    await self.ctx.close()
            except Exception:
                pass
            self.ctx = None
            self.page = None
        report_session_outcome(self.engine_name, result=check_in_result)


def _classify_error(err_msg: str) -> str:
    """Best-effort 把 adapter 报的 error 字符串映射到 FailureType."""
    e = (err_msg or "").lower()
    if "textarea not visible" in e or "input not visible" in e or "login may have expired" in e:
        return "login_lost"
    if "captcha" in e or "验证" in e:
        return "captcha"
    if any(token in e for token in ("rate limit", "rate_limit", "too many requests", "限流", "频率")):
        return "rate_limited"
    if "timeout" in e or "超时" in e:
        return "timeout"
    if "not found" in e or "selector" in e:
        return "dom_not_found"
    return "crash"
