"""媒介星代理商 API 客户端(签名 + HTTP + 错误分类)。

接口文档:docs/媒体API/媒介星API接口(1).pdf,产品方案:docs/媒体API/产品文档-媒介星发文对接.md。

协议要点:
  - 全部 HTTP POST,application/x-www-form-urlencoded,utf-8
  - 公共参数 secret_id / timestamp(10 位秒)/ signature
  - 签名:除 signature 外的参数按参数名 ASCII 升序拼成 a=2&b=3,
    尾部拼 &key=<secret_key>,MD5 后转大写
  - 返回 {code, msg, data},code "200" 成功 / "201" 失败(实测 code 可能是 int 或 str,
    统一转 str 比较)
  - 下单 title 需在签名前单独 urlencode(对方按收到的字面值验签)

控制(在 client 层落地的部分):
  - 密钥未配置直接抛 MjxConfigError,不发请求
  - create_*_order 是付费动作,额外受 settings.MJX_PUBLISH_ENABLED 闸控;
    查询类接口(余额/媒体库/订单状态)不受闸,随时可调
  - 全局并发 Semaphore(2) + 超时 15s
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from typing import Any
from urllib.parse import quote

import httpx

from geo.database import settings

log = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15.0  # 对方为 PHP 老站,留足余量
_CONCURRENCY = asyncio.Semaphore(2)

# 订单状态码(query_*_order 返回的 status)
ORDER_STATUS = {
    "-2": "deleted",      # 已删除
    "-1": "rejected",     # 已拒稿
    "0": "pending",       # 未处理
    "1": "publishing",    # 发布中
    "2": "published",     # 已完成
}


class MjxError(Exception):
    """媒介星调用失败统一基类;msg 保留对方原文。"""

    def __init__(self, message: str, *, code: str | None = None, raw: Any = None):
        super().__init__(message)
        self.code = code
        self.raw = raw


class MjxConfigError(MjxError):
    """本地配置问题(密钥缺失 / 下单闸未开),不应重试。"""


class MjxApiError(MjxError):
    """对方返回 code=201 的业务失败(签名错/重复单/余额不足/媒体失效等)。"""


def _sign(params: dict[str, Any], secret_key: str) -> str:
    """ASCII 升序 → a=2&b=3 → 拼 &key= → MD5 大写。跳过空值与 signature 本身。"""
    parts = [
        f"{k}={v}"
        for k, v in sorted(params.items())
        if k != "signature" and v is not None and v != ""
    ]
    raw = "&".join(parts) + f"&key={secret_key}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()


class MjxClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        secret_id: str | None = None,
        secret_key: str | None = None,
    ):
        self.base_url = (base_url or settings.MJX_API_BASE).rstrip("/")
        self.secret_id = secret_id if secret_id is not None else settings.MJX_SECRET_ID
        self.secret_key = secret_key if secret_key is not None else settings.MJX_SECRET_KEY
        if not self.secret_id or not self.secret_key:
            raise MjxConfigError("MJX_SECRET_ID / MJX_SECRET_KEY 未配置,媒介星渠道未开通")

    # ---------- 底层 ----------

    async def _post(self, path: str, params: dict[str, Any] | None = None) -> Any:
        body: dict[str, Any] = dict(params or {})
        body["secret_id"] = self.secret_id
        body["timestamp"] = int(time.time())
        body["signature"] = _sign(body, self.secret_key)
        url = f"{self.base_url}{path}"
        async with _CONCURRENCY:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                resp = await client.post(url, data=body)
        try:
            payload = resp.json()
        except ValueError as e:
            # 对方 ThinkPHP 错误页时尽量提取 <h1> 异常摘要,方便定位
            import re

            m = re.search(r"<h1[^>]*>(.*?)</h1>", resp.text, re.S)
            detail = re.sub(r"\s+", " ", m.group(1)).strip() if m else resp.text[:300]
            raise MjxError(
                f"媒介星返回非 JSON(HTTP {resp.status_code}): {detail[:300]}"
            ) from e
        code = str(payload.get("code", ""))
        if code != "200":
            raise MjxApiError(str(payload.get("msg", "未知错误")), code=code, raw=payload)
        return payload.get("data")

    # ---------- 查询类(不受下单闸) ----------

    async def user_info(self) -> dict:
        """余额查询 → {money, username, level}。"""
        return await self._post("/meijieapi/daili3/userInfo")

    async def media_list(
        self,
        *,
        page: int = 1,
        limit: int = 200,
        media_id: int | None = None,
        uptime: int | None = None,
    ) -> Any:
        """新闻媒体列表;media_id 单条,uptime 秒级时间戳增量。limit 范围 200~1000。"""
        params: dict[str, Any] = {"page": page, "limit": limit}
        if media_id is not None:
            params["id"] = media_id
        if uptime is not None:
            params["uptime"] = uptime
        return await self._post("/meijieapi/daili3/media_lst", params)

    async def wmedia_list(self, *, page: int = 1, limit: int = 200) -> Any:
        """自媒体列表。"""
        return await self._post("/meijieapi/daili3/wmedia_lst", {"page": page, "limit": limit})

    async def get_ids(self, *, type_: int, status: int = 1) -> list:
        """上架资源 id 合集(对账用)。type: 1 媒体 / 2 自媒体 / 6 短视频。"""
        return await self._post("/meijieapi/daili3/get_ids", {"status": status, "type": type_})

    async def query_media_order(self, nos: list[str]) -> Any:
        """新闻媒体订单状态,nos 为我方订单号列表(单批建议 ≤50)。"""
        return await self._post("/meijieapi/daili3/query_media_order", {"nostr": ",".join(nos)})

    async def query_wmedia_order(self, nos: list[str]) -> Any:
        """自媒体订单状态。注意:此接口基址路径与其他不同(对方文档如此)。"""
        return await self._post("/api/wemedia/query_wmedia_order", {"nostr": ",".join(nos)})

    # ---------- 下单类(付费,受 MJX_PUBLISH_ENABLED 闸) ----------

    def _order_params(
        self,
        *,
        title: str,
        preview_url: str,
        mid: int,
        no: str,
        remark: str,
        saling_price: str,
        media_name: str = "",
    ) -> dict[str, Any]:
        if not settings.MJX_PUBLISH_ENABLED:
            raise MjxConfigError("MJX_PUBLISH_ENABLED 未开启,拒绝真实下单(付费动作)")
        return {
            # 文档要求 title 单独 urlencode(签名按 encode 后的字面值算)
            "title": quote(title, safe=""),
            "content": f'<a href="{preview_url}">{preview_url}</a>',
            "mid": mid,
            # PDF 未写但对方服务端必读,缺了直接 500"未定义数组索引: media_name"。
            # 传媒体列表里的 media_name / wemedia_name 原文。
            "media_name": media_name,
            "no": no,
            "remark": remark,
            "saling_price": saling_price,
        }

    async def create_media_order(
        self, *, title: str, preview_url: str, mid: int, no: str, remark: str,
        saling_price: str, media_name: str = "",
    ) -> Any:
        """新闻媒体下单。no 是幂等键,重试必须复用同一个 no。"""
        return await self._post(
            "/meijieapi/daili3/create_media_order",
            self._order_params(
                title=title, preview_url=preview_url, mid=mid, no=no,
                remark=remark, saling_price=saling_price, media_name=media_name,
            ),
        )

    async def create_wmedia_order(
        self, *, title: str, preview_url: str, mid: int, no: str, remark: str,
        saling_price: str, media_name: str = "",
    ) -> Any:
        """自媒体下单。"""
        return await self._post(
            "/meijieapi/daili3/create_wmedia_order",
            self._order_params(
                title=title, preview_url=preview_url, mid=mid, no=no,
                remark=remark, saling_price=saling_price, media_name=media_name,
            ),
        )
