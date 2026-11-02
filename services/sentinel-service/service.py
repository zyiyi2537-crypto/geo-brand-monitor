"""Sentinel(yuqin)微服务 — FastAPI 包装.

GEO backend 通过 HTTP 调本服务,本服务再调 yuqin 的 4 个核心函数.

设计要点:
- 多租户隔离:每个 account_id 对应一个 PG schema(`tenant_{N}`),通过
  `SET search_path` 路由,storage 包的 contextvar `current_account` 在请求
  入口绑定.原历史方案是每账户一个独立 SQLite 文件(2026-05-21 切到 PG).
- API key 注入:client 在 header 里传 X-OpenAI-Key,本服务设到 env 后透传.
- 异常包成 dict 返回,不抛给 client(yuqin 内部用 sys.exit 的地方在主入口拦截).

环境变量:
- SENTINEL_DATA_DIR    数据目录(默认 ./data)
- SENTINEL_PORT        端口(默认 8090)
- OPENAI_API_KEY       平台 fallback(client 没传时用)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

# 把当前目录加到 sys.path,这样 yuqin 模块可以直接 import
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# ── 数据目录(副产物落盘:briefs / knowledge / 等)──────────────
# 主数据(posts / analyses / briefs / drafts / query_runs)已迁到 PG schema,
# 这个目录只保留落盘类副产物.
DATA_DIR = Path(os.environ.get("SENTINEL_DATA_DIR", str(ROOT / "data"))).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 展示新鲜度窗口(天):today 聚合 / Top5 / 风险分布 / 简报只露最近 N 天的"内容"
# (按 publish_time,不是入库时间),把"今天爬到但发布于 2024 年"的旧帖挡在展示外。
# 抓取仍全量增量入库,只在展示层收口。默认 3 天;要"最近 24 小时"设为 1。
DISPLAY_MAX_AGE_DAYS = int(os.environ.get("SENTINEL_DISPLAY_MAX_AGE_DAYS", "3"))


def _account_db_path(account_id: int) -> Path:
    """历史名:返回 `account_{N}/yuqing.db` 路径,**主库已切 PG**,这里只是
    给老 caller 借用 `.parent` 拿账户的落盘子目录(briefs / knowledge 等).
    """
    p = DATA_DIR / f"account_{account_id}" / "yuqing.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# 多租户 contextvar(由 storage 包统一定义,service.py 只 set/reset)
# 这取代了历史的 6 层 monkey-patch:storage 包级 wrapper 在每次 connect()
# 调用时动态读 contextvar,所以子模块 `from storage import connect` 拷贝
# 函数引用的快照问题不再存在.
from storage import current_account              # type: ignore  # noqa: E402

# yuqin 业务入口
from search import (                              # type: ignore  # noqa: E402
    generate_monitoring_plan, run_plan,
)
from analyzer import analyze_symbol               # type: ignore  # noqa: E402
from brief import generate_brief                  # type: ignore  # noqa: E402
from response import generate_drafts              # type: ignore  # noqa: E402
from response import draft as _draft_module       # type: ignore  # noqa: E402
from crawler.eastmoney import EastmoneyGubaClient # type: ignore  # noqa: E402
from crawler.xueqiu import XueqiuClient          # type: ignore  # noqa: E402
from crawler.sina_finance import SinaFinanceClient # type: ignore  # noqa: E402
from crawler.eastmoney_news import EastmoneyNewsClient # type: ignore  # noqa: E402
from crawler.baidu_tieba import BaiduTiebaClient     # type: ignore  # noqa: E402
from crawler.cls_finance import ClsFinanceClient      # type: ignore  # noqa: E402
from crawler.gelonghui import GelonghuiClient         # type: ignore  # noqa: E402
from crawler.wallstreetcn import WallstreetcnClient   # type: ignore  # noqa: E402
from crawler.yicai import YicaiClient                 # type: ignore  # noqa: E402
from crawler.kr36 import Kr36Client                   # type: ignore  # noqa: E402
from crawler.eastmoney_announcement import EastmoneyAnnouncementClient  # type: ignore  # noqa: E402
from crawler.eastmoney_research import EastmoneyResearchClient          # type: ignore  # noqa: E402
from crawler.eastmoney_industry import EastmoneyIndustryClient          # type: ignore  # noqa: E402
from crawler.sina_stock_news import SinaStockNewsClient                  # type: ignore  # noqa: E402
from crawler.weixin_album import WeixinAlbumClient                       # type: ignore  # noqa: E402
from crawler.newsnow_hub import NewsnowHubClient                         # type: ignore  # noqa: E402
from storage import connect as _yuqin_connect, init_schema, upsert_post  # type: ignore  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sentinel")


# ── 工具:运行环境 + 异常包装 ──────────────────────────────────
def _is_plausible_openai_key(key: Optional[str]) -> bool:
    """合法 OpenAI key 一定 'sk-' 前缀.过滤上游 backend 传过来的占位垃圾
    (例如 'api-key-...-duze' 这种内部 token 被错配到 OPENAI_API_KEY 上,
    会覆盖 sentinel-service 自己 env 里的真 key 导致 401)."""
    return bool(key) and key.startswith("sk-")


@asynccontextmanager
async def _account_context(account_id: int, api_key: Optional[str]):
    """设当前账号 + OpenAI API Key,函数返回时清理.

    只接受看起来像合法 OpenAI key 的值;空 / 占位垃圾被忽略,从而保留
    sentinel-service 进程自己 env 的 OPENAI_API_KEY,让 llm_client 走
    OpenAI → Qwen fallback 链.
    """
    token = current_account.set(account_id)
    prev_key = os.environ.get("OPENAI_API_KEY")
    overrode = False
    if _is_plausible_openai_key(api_key):
        os.environ["OPENAI_API_KEY"] = api_key  # type: ignore[assignment]
        overrode = True
    elif api_key:
        log.warning(
            "ignoring upstream X-OpenAI-Key (not 'sk-' prefixed); "
            "falling back to service-local key chain",
        )
    try:
        yield
    finally:
        current_account.reset(token)
        if overrode:
            if prev_key is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = prev_key


def _wrap(fn, *args, **kwargs) -> dict:
    """yuqin 函数有用 sys.exit 的地方,这里不能让进程退出.
    把 SystemExit 也包成 failed."""
    try:
        result = fn(*args, **kwargs)
        return {"status": "success", "data": result}
    except SystemExit as e:
        log.warning("sentinel SystemExit: %s", e)
        return {"status": "failed", "error": str(e), "category": "business"}
    except RuntimeError as e:
        log.warning("sentinel RuntimeError: %s", e)
        return {"status": "failed", "error": str(e), "category": "business"}
    except Exception as e:
        log.exception("sentinel crashed: %s", e)
        return {"status": "failed", "error": str(e), "category": "system"}


# ── Pydantic 请求模型 ──────────────────────────────────────────
class MonitorRequest(BaseModel):
    account_id: int
    target: str = Field(..., description="品牌名,例:世纪互联")
    ticker: Optional[str] = None
    intent: Optional[str] = None
    aliases: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list, description="AND 修饰词")
    excludes: list[str] = Field(default_factory=list, description="预留,目前 yuqin 未直接支持")
    media_allowlist: list[str] = Field(default_factory=list, description="域名白名单")
    force_all: bool = False
    max_results_per_query: int = 10
    timelimit: Optional[str] = "d"
    auto_widen: bool = True
    region: str = "wt-wt"
    engines: list[str] = Field(default_factory=lambda: ["searxng"])
    # 默认走 SearXNG:server 端聚合多上游引擎 + 反爬/IP 池统一处理。
    # 自带引擎 cnbing/baidu/sogou/ddg 仍保留,显式传 engines 即可回退。


class AnalyzeRequest(BaseModel):
    account_id: int
    ticker: str
    limit: Optional[int] = None
    sleep_s: float = 0.0


class BriefRequest(BaseModel):
    account_id: int
    ticker: str
    date: Optional[str] = None
    batch_size: int = 20
    top_noteworthy: int = 5


class RespondRequest(BaseModel):
    account_id: int
    ticker: str
    source: Optional[str] = None
    post_id: Optional[str] = None
    topic: Optional[str] = None
    situation: Optional[str] = None
    knowledge: Optional[dict[str, str]] = Field(
        default=None,
        description="{'brand_voice': str, 'legal_redlines': str, 'response_playbook': str}.None=用容器内默认文件",
    )


class CrawlEastmoneyRequest(BaseModel):
    account_id: int
    symbol: str
    pages: int = 2


class CrawlXueqiuRequest(BaseModel):
    account_id: int
    symbol: str
    pages: int = 3
    count: int = 50


class CrawlSinaRequest(BaseModel):
    account_id: int
    keyword: str
    pages: int = 3


class CrawlEastmoneyNewsRequest(BaseModel):
    account_id: int
    keyword: str
    pages: int = 3


class CrawlTiebaRequest(BaseModel):
    account_id: int
    keyword: str
    pages: int = 3


class CrawlClsRequest(BaseModel):
    account_id: int
    keyword: str
    pages: int = 3


class CrawlGenericRequest(BaseModel):
    """通用搜索型爬虫请求."""
    account_id: int
    keyword: str
    pages: int = 3


class CrawlWeixinAlbumRequest(BaseModel):
    """微信公众号合集抓取请求."""
    account_id: int
    album_urls: list[str] = Field(default_factory=list,
                                  description="合集 URL 列表(__biz + album_id 完整 URL)")
    hydrate_body: bool = Field(False,
                               description="是否额外抓 mp.weixin 正文(每篇 +1-2s)")
    max_articles_per_album: Optional[int] = Field(
        None, description="单合集上限保护;None=全量")


class CrawlNewsnowRequest(BaseModel):
    """NewsNow 热榜聚合抓取请求."""
    account_id: int
    source_ids: list[str] = Field(
        default_factory=list,
        description="newsnow source 列表,如 ['weibo','zhihu','v2ex','toutiao']")
    keywords: list[str] = Field(
        default_factory=list,
        description="标题子串过滤;空 list = 全量入库不过滤")
    symbol: str = Field(..., description="入库 symbol(通常 = account.ticker)")
    base_url: Optional[str] = Field(
        None, description="覆盖 NEWSNOW_BASE_URL env;None=用容器默认")


# ── FastAPI app ────────────────────────────────────────────────
app = FastAPI(
    title="Sentinel (yuqin) Service",
    description="LLM-native sentiment monitoring microservice",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "data_dir": str(DATA_DIR)}


@app.post("/run-monitor")
async def run_monitor(
    req: MonitorRequest,
    x_openai_key: Optional[str] = Header(None, alias="X-OpenAI-Key"),
) -> dict:
    """生成 plan + 多引擎抓取 + 写 posts.

    返回:{"status": "success"|"failed", "data": stats, "error": "..."}
    stats: {"queries": N, "inserted": N, "total": N, "by_source": {...}, "by_engine": {...}}
    """
    async with _account_context(req.account_id, x_openai_key):
        targets = [req.target] + req.aliases
        targets = [t for t in targets if t]

        def _do() -> dict:
            plan = generate_monitoring_plan(
                target=targets,
                ticker=req.ticker,
                intent=req.intent,
                media=req.media_allowlist or None,
                keywords=req.keywords or None,
                force_all=req.force_all,
            )
            symbol = req.ticker or req.target
            stats = run_plan(
                plan, symbol,
                max_results_per_query=req.max_results_per_query,
                timelimit=req.timelimit,
                auto_widen=req.auto_widen,
                region=req.region,
                engines=req.engines or None,
                verbose=False,
            )
            return {"plan_summary": _summarize_plan(plan), "stats": stats}

        return await asyncio.to_thread(_wrap, _do)


@app.post("/run-analyze")
async def run_analyze(
    req: AnalyzeRequest,
    x_openai_key: Optional[str] = Header(None, alias="X-OpenAI-Key"),
) -> dict:
    """对未分析帖子做 LLM 分析,写 analyses."""
    async with _account_context(req.account_id, x_openai_key):
        def _do():
            return analyze_symbol(req.ticker, limit=req.limit, sleep_s=req.sleep_s)
        return await asyncio.to_thread(_wrap, _do)


@app.post("/run-brief")
async def run_brief(
    req: BriefRequest,
    x_openai_key: Optional[str] = Header(None, alias="X-OpenAI-Key"),
) -> dict:
    """生成日度简报 Markdown 入库,返回 brief 内容."""
    async with _account_context(req.account_id, x_openai_key):
        # brief/generate.py 把 MD 写到 data/brief_*.md;我们让它输出到账号目录
        out_dir = _account_db_path(req.account_id).parent / "briefs"

        def _do():
            path = generate_brief(
                req.ticker,
                date=req.date,
                out_dir=out_dir,
                batch_size=req.batch_size,
                top_noteworthy=req.top_noteworthy,
            )
            body = Path(path).read_text(encoding="utf-8")
            return {"path": str(path), "body": body, "date": req.date}
        return await asyncio.to_thread(_wrap, _do)


@app.post("/run-respond")
async def run_respond(
    req: RespondRequest,
    x_openai_key: Optional[str] = Header(None, alias="X-OpenAI-Key"),
) -> dict:
    """生成三档草稿,写 drafts."""
    if not (req.post_id or req.topic):
        raise HTTPException(400, "post_id 或 topic 至少传一个")

    async with _account_context(req.account_id, x_openai_key):
        # 临时覆盖 KNOWLEDGE_DIR 让 yuqin _load_knowledge() 读账号知识库
        # MVP:如果 client 传了 knowledge,落到临时目录;否则用容器默认 knowledge/
        original_dir = _draft_module.KNOWLEDGE_DIR
        if req.knowledge:
            kdir = _account_db_path(req.account_id).parent / "knowledge"
            kdir.mkdir(parents=True, exist_ok=True)
            for key, body in req.knowledge.items():
                if key in ("brand_voice", "legal_redlines", "response_playbook"):
                    (kdir / f"{key}.md").write_text(body, encoding="utf-8")
            _draft_module.KNOWLEDGE_DIR = kdir

        def _do():
            return generate_drafts(
                req.ticker,
                source=req.source,
                post_id=req.post_id,
                topic=req.topic,
                situation=req.situation,
            )
        try:
            return await asyncio.to_thread(_wrap, _do)
        finally:
            _draft_module.KNOWLEDGE_DIR = original_dir


@app.post("/run-crawl-eastmoney")
async def run_crawl_eastmoney(req: CrawlEastmoneyRequest) -> dict:
    """直接抓东财股吧(无需 OpenAI)."""
    async with _account_context(req.account_id, None):
        def _do():
            client = EastmoneyGubaClient()
            conn = _yuqin_connect()
            init_schema(conn)
            total = inserted = 0
            for page in range(1, req.pages + 1):
                records = list(client.fetch_list(req.symbol, page=page))
                for r in records:
                    if upsert_post(conn, r):
                        inserted += 1
                    total += 1
            conn.commit()
            return {"total": total, "inserted": inserted}
        return await asyncio.to_thread(_wrap, _do)


@app.post("/run-crawl-xueqiu")
async def run_crawl_xueqiu(req: CrawlXueqiuRequest) -> dict:
    """直接抓雪球讨论帖(无需 OpenAI)."""
    async with _account_context(req.account_id, None):
        def _do():
            client = XueqiuClient()
            conn = _yuqin_connect()
            init_schema(conn)
            total = inserted = 0
            for rec in client.fetch_pages(req.symbol, pages=req.pages, count=req.count):
                if upsert_post(conn, rec):
                    inserted += 1
                total += 1
            conn.commit()
            return {"total": total, "inserted": inserted}
        return await asyncio.to_thread(_wrap, _do)


@app.post("/run-crawl-sina")
async def run_crawl_sina(req: CrawlSinaRequest) -> dict:
    """抓新浪财经搜索新闻."""
    async with _account_context(req.account_id, None):
        def _do():
            client = SinaFinanceClient()
            conn = _yuqin_connect()
            init_schema(conn)
            total = inserted = 0
            for rec in client.search_pages(req.keyword, pages=req.pages):
                if upsert_post(conn, rec):
                    inserted += 1
                total += 1
            conn.commit()
            return {"total": total, "inserted": inserted}
        return await asyncio.to_thread(_wrap, _do)


@app.post("/run-crawl-eastmoney-news")
async def run_crawl_eastmoney_news(req: CrawlEastmoneyNewsRequest) -> dict:
    """东财资讯搜索(新闻/研报/公告)."""
    async with _account_context(req.account_id, None):
        def _do():
            client = EastmoneyNewsClient()
            conn = _yuqin_connect()
            init_schema(conn)
            total = inserted = 0
            for rec in client.search_pages(req.keyword, pages=req.pages):
                if upsert_post(conn, rec):
                    inserted += 1
                total += 1
            conn.commit()
            return {"total": total, "inserted": inserted}
        return await asyncio.to_thread(_wrap, _do)


@app.post("/run-crawl-tieba")
async def run_crawl_tieba(req: CrawlTiebaRequest) -> dict:
    """百度贴吧搜索."""
    async with _account_context(req.account_id, None):
        def _do():
            client = BaiduTiebaClient()
            conn = _yuqin_connect()
            init_schema(conn)
            total = inserted = 0
            for rec in client.search_pages(req.keyword, pages=req.pages):
                if upsert_post(conn, rec):
                    inserted += 1
                total += 1
            conn.commit()
            return {"total": total, "inserted": inserted}
        return await asyncio.to_thread(_wrap, _do)


@app.post("/run-crawl-cls")
async def run_crawl_cls(req: CrawlClsRequest) -> dict:
    """财联社快讯+搜索."""
    async with _account_context(req.account_id, None):
        def _do():
            client = ClsFinanceClient()
            conn = _yuqin_connect()
            init_schema(conn)
            total = inserted = 0
            for rec in client.fetch_telegraph(keyword=req.keyword, count=100):
                if upsert_post(conn, rec):
                    inserted += 1
                total += 1
            for rec in client.search_pages(req.keyword, pages=req.pages):
                if upsert_post(conn, rec):
                    inserted += 1
                total += 1
            conn.commit()
            return {"total": total, "inserted": inserted}
        return await asyncio.to_thread(_wrap, _do)


def _generic_crawl_endpoint(client_cls, source_name: str):
    """工厂函数: 生成通用搜索型爬虫 endpoint."""
    async def handler(req: CrawlGenericRequest) -> dict:
        async with _account_context(req.account_id, None):
            def _do():
                client = client_cls()
                conn = _yuqin_connect()
                init_schema(conn)
                total = inserted = 0
                for rec in client.search_pages(req.keyword, pages=req.pages):
                    if upsert_post(conn, rec):
                        inserted += 1
                    total += 1
                conn.commit()
                return {"total": total, "inserted": inserted}
            return await asyncio.to_thread(_wrap, _do)
    handler.__name__ = f"run_crawl_{source_name}"
    handler.__doc__ = f"抓取{source_name}."
    return handler


app.post("/run-crawl-gelonghui")(_generic_crawl_endpoint(GelonghuiClient, "gelonghui"))
app.post("/run-crawl-wallstreetcn")(_generic_crawl_endpoint(WallstreetcnClient, "wallstreetcn"))
app.post("/run-crawl-yicai")(_generic_crawl_endpoint(YicaiClient, "yicai"))
app.post("/run-crawl-36kr")(_generic_crawl_endpoint(Kr36Client, "kr36"))

# 新增 EastMoney 系列(2026-05-08):公告 / 个股研报 / 行业研究
# 这些 endpoint 接收的 keyword 实际是 6 位 A 股代码(由 service 层透传)
app.post("/run-crawl-eastmoney-ann")(_generic_crawl_endpoint(EastmoneyAnnouncementClient, "eastmoney_ann"))
app.post("/run-crawl-eastmoney-research")(_generic_crawl_endpoint(EastmoneyResearchClient, "eastmoney_research"))
app.post("/run-crawl-eastmoney-industry")(_generic_crawl_endpoint(EastmoneyIndustryClient, "eastmoney_industry"))
app.post("/run-crawl-sina-stock")(_generic_crawl_endpoint(SinaStockNewsClient, "sina_stock"))


@app.post("/run-crawl-weixin-album")
async def run_crawl_weixin_album(req: CrawlWeixinAlbumRequest) -> dict:
    """按合集 URL 全量枚举微信公众号文章(无 cookie,无 LLM)."""
    async with _account_context(req.account_id, None):
        def _do():
            if not req.album_urls:
                return {"total": 0, "inserted": 0, "skipped": "no album_urls configured"}
            client = WeixinAlbumClient(hydrate_body=req.hydrate_body)
            conn = _yuqin_connect()
            init_schema(conn)
            total = inserted = 0
            for rec in client.fetch_albums(
                req.album_urls, max_articles_per_album=req.max_articles_per_album,
            ):
                if upsert_post(conn, rec):
                    inserted += 1
                total += 1
            conn.commit()
            return {"total": total, "inserted": inserted,
                    "albums": len(req.album_urls)}
        return await asyncio.to_thread(_wrap, _do)


@app.post("/run-crawl-newsnow")
async def run_crawl_newsnow(req: CrawlNewsnowRequest) -> dict:
    """轮询自托管 newsnow 热榜聚合(无 LLM)."""
    async with _account_context(req.account_id, None):
        def _do():
            if not req.source_ids:
                return {"total": 0, "inserted": 0, "skipped": "no source_ids configured"}
            client = NewsnowHubClient(base_url=req.base_url)
            conn = _yuqin_connect()
            init_schema(conn)
            total = inserted = 0
            for rec in client.fetch_sources(
                req.source_ids, keywords=req.keywords, symbol=req.symbol,
            ):
                if upsert_post(conn, rec):
                    inserted += 1
                total += 1
            conn.commit()
            return {"total": total, "inserted": inserted,
                    "sources": len(req.source_ids),
                    "filtered": bool(req.keywords)}
        return await asyncio.to_thread(_wrap, _do)


# ── newsnow 实时热点(只读 / 不绑 account / 不入库) ─────────────
# 用于前端"实时新闻 / 今日热点"面板:纯转发自托管 newsnow JSON,
# 不消费 keywords 也不落 posts 表,只展示给用户看。
# 与 /run-crawl-newsnow 互补:那条路径走 account.newsnow_sources +
# keywords 过滤,产物落 posts 进入分析管线;本路径是"裸热榜"。
_NEWSNOW_SOURCE_CATALOG: list[dict] = [
    # 推荐顺序 ≈ 国内可用 + 群众反应面优先
    {"id": "weibo",       "name_zh": "微博热搜",      "name_en": "Weibo",         "category": "social"},
    {"id": "zhihu",       "name_zh": "知乎热榜",      "name_en": "Zhihu",         "category": "social"},
    {"id": "douyin",      "name_zh": "抖音热榜",      "name_en": "Douyin",        "category": "social"},
    {"id": "kuaishou",    "name_zh": "快手热榜",      "name_en": "Kuaishou",      "category": "social"},
    {"id": "bilibili",    "name_zh": "B 站热搜",      "name_en": "Bilibili",      "category": "social"},
    {"id": "tieba",       "name_zh": "百度贴吧",      "name_en": "Tieba",         "category": "social"},
    {"id": "hupu",        "name_zh": "虎扑步行街",    "name_en": "Hupu",          "category": "social"},
    {"id": "douban",      "name_zh": "豆瓣热榜",      "name_en": "Douban",        "category": "social"},
    {"id": "toutiao",     "name_zh": "今日头条",      "name_en": "Toutiao",       "category": "news"},
    {"id": "baidu",       "name_zh": "百度热搜",      "name_en": "Baidu",         "category": "news"},
    {"id": "thepaper",    "name_zh": "澎湃新闻",      "name_en": "ThePaper",      "category": "news"},
    {"id": "ifeng",       "name_zh": "凤凰新闻",      "name_en": "iFeng",         "category": "news"},
    {"id": "ithome",      "name_zh": "IT 之家",       "name_en": "IThome",        "category": "tech"},
    {"id": "36kr",        "name_zh": "36 氪",         "name_en": "36Kr",          "category": "tech"},
    {"id": "huxiu",       "name_zh": "虎嗅",          "name_en": "Huxiu",         "category": "tech"},
    {"id": "juejin",      "name_zh": "掘金",          "name_en": "Juejin",        "category": "tech"},
    {"id": "ghxi",        "name_zh": "果核剥壳",      "name_en": "Ghxi",          "category": "tech"},
    {"id": "sspai",       "name_zh": "少数派",        "name_en": "Sspai",         "category": "tech"},
    {"id": "smzdm",       "name_zh": "什么值得买",    "name_en": "SMZDM",         "category": "tech"},
    {"id": "xueqiu",      "name_zh": "雪球热帖",      "name_en": "Xueqiu",        "category": "finance"},
    {"id": "gelonghui",   "name_zh": "格隆汇",        "name_en": "Gelonghui",     "category": "finance"},
    {"id": "wallstreetcn", "name_zh": "华尔街见闻",   "name_en": "WallstreetCN",  "category": "finance"},
    {"id": "cls",         "name_zh": "财联社",        "name_en": "CaiLianShe",    "category": "finance"},
    {"id": "jin10",       "name_zh": "金十数据",      "name_en": "Jin10",         "category": "finance"},
    {"id": "fastbull",    "name_zh": "法布财经",      "name_en": "FastBull",      "category": "finance"},
]


@app.get("/newsnow/sources")
def newsnow_sources() -> dict:
    """返回 newsnow 推荐源目录(静态)。前端用来渲染 tab 切换。"""
    return {"count": len(_NEWSNOW_SOURCE_CATALOG), "items": _NEWSNOW_SOURCE_CATALOG}


@app.get("/newsnow/hot")
async def newsnow_hot(source: str, limit: int = 30) -> dict:
    """拉指定 source 的当前热榜(实时新闻 / 今日热点用)。
    - 不落库、不分析、不过滤,纯转发 newsnow JSON
    - 当 newsnow 不可达时返回 items=[] + error,前端友好降级
    - limit 默认 30,上限 100
    """
    source = (source or "").strip().lower()
    if not source:
        raise HTTPException(400, "missing required query param: source")
    limit = max(1, min(int(limit), 100))

    def _do() -> dict:
        from datetime import datetime, timezone
        client = NewsnowHubClient()
        items = client.fetch_source(source)
        # 友好降级:newsnow 不返时间戳,前端展示用 fetched_at = 服务端时间
        return {
            "source": source,
            "items": items[:limit] if items else [],
            "count": min(len(items), limit) if items else 0,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

    return await asyncio.to_thread(_do)


# ── 数据查询 endpoints(给 GEO backend 取数渲染前端用)──────────
@app.get("/accounts/{account_id}/posts")
def list_posts(account_id: int, ticker: str, limit: int = 50,
               offset: int = 0, days: int = 1,
               start: str | None = None, end: str | None = None,
               sort_by: str = "newest") -> dict:
    """返回 posts JOIN analyses(给文章 Tab 用)。

    时间过滤(基于 ingested_at):
      - start/end (YYYY-MM-DD,闭区间) 优先;任一端可省。
      - 否则按 days:1=今日(默认), N>1=最近 N 天, 0=全部历史。

    排序 sort_by(默认 newest)— 支持:
      newest / oldest / engagement / replies / likes / shares / views /
      cluster / mediaAZ / mediaZA / scoreSentiment / scoreInfluence.
      未知值后端回退 newest。

    分页:limit + offset。返回:
      items[]、count(本页)、total(满足时间筛选的总条数)、offset、days、start、end、sort_by。
    """
    from storage import analyses_for_symbol, analyses_count_for_symbol  # type: ignore
    with _account_db_context(account_id):
        conn = _yuqin_connect()
        init_schema(conn)
        total = analyses_count_for_symbol(conn, ticker, days=days, start=start, end=end)
        rows = analyses_for_symbol(
            conn, ticker, days=days, start=start, end=end,
            limit=limit, offset=offset, sort_by=sort_by,
        )
        out = [_row_to_dict(r) for r in rows]
    return {
        "count": len(out), "items": out, "total": int(total),
        "offset": int(offset), "limit": int(limit),
        "days": days, "start": start, "end": end,
        "sort_by": sort_by,
    }


@app.get("/accounts/{account_id}/briefs")
def list_briefs(account_id: int, ticker: str) -> dict:
    """返回该 account 的所有简报(metadata only,body 由 /briefs/{id} 取)."""
    with _account_db_context(account_id):
        conn = _yuqin_connect()
        init_schema(conn)
        rows = list(conn.execute(
            "SELECT id, symbol, date, model, generated_at FROM briefs "
            "WHERE symbol = %s ORDER BY date DESC, id DESC", (ticker,),
        ))
        return {"count": len(rows), "items": [dict(r) for r in rows]}


@app.get("/accounts/{account_id}/briefs/{brief_id}")
def get_brief(account_id: int, brief_id: int) -> dict:
    with _account_db_context(account_id):
        conn = _yuqin_connect()
        row = conn.execute("SELECT * FROM briefs WHERE id = %s", (brief_id,)).fetchone()
        if not row:
            raise HTTPException(404, "brief not found")
        return dict(row)


@app.get("/accounts/{account_id}/drafts")
def list_drafts(account_id: int, ticker: str) -> dict:
    with _account_db_context(account_id):
        conn = _yuqin_connect()
        init_schema(conn)
        rows = list(conn.execute(
            "SELECT * FROM drafts WHERE symbol = %s ORDER BY id DESC", (ticker,),
        ))
        return {"count": len(rows), "items": [dict(r) for r in rows]}


@app.get("/accounts/{account_id}/today")
def today_aggregation(account_id: int, ticker: str, days: int = 7) -> dict:
    """Tab 1 数据聚合 — 一次请求拿到所有渲染所需:KPI / 7 天趋势 / 风险分布 / 最新简报 / 高风险 Top5.

    在 sentinel-service 里聚合,前端不必拉几百条 posts 自己算.
    """
    from collections import Counter
    from datetime import date, datetime, timedelta

    with _account_db_context(account_id):
        conn = _yuqin_connect()
        init_schema(conn)

        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        cutoff = (date.today() - timedelta(days=days - 1)).isoformat()
        # 内容新鲜度下限:发布日期(publish_time)早于此的旧帖,即便今天才爬到也不展示。
        recency_cutoff = (date.today() - timedelta(days=DISPLAY_MAX_AGE_DAYS - 1)).isoformat()

        # 当日 KPI:posts × analyses(仅 is_relevant=1,与下方趋势图/风险饼/文章列表保持一致)
        # 追加新鲜度闸门:COALESCE(publish_time, ingested_at) >= recency_cutoff —— publish_time
        # 已知且陈旧(如今天爬到的 2024 文章)被剔除;无日期的回退入库时间(都是今天入库,算新)。
        kpi_sql = """
            SELECT
                count(*) AS total,
                sum(CASE WHEN a.risk_level IN ('medium','high') THEN 1 ELSE 0 END) AS high_risk,
                avg(a.sentiment_score) AS avg_sentiment,
                count(DISTINCT p.source) AS active_sources
            FROM posts p JOIN analyses a
              ON p.source = a.source AND p.post_id = a.post_id
            WHERE p.symbol = %s
              AND a.is_relevant = 1
              AND substr(p.ingested_at, 1, 10) = %s
              AND COALESCE(p.publish_time, p.ingested_at) >= %s
        """
        kpi_row = conn.execute(kpi_sql, (ticker, today, recency_cutoff)).fetchone()
        prev_row = conn.execute(kpi_sql, (ticker, yesterday, recency_cutoff)).fetchone()

        # N 天情感堆叠柱:严格按 publish_time 分桶(NULL 的丢弃).
        # Why: 爬虫单次能拉回半年历史内容,若按 ingested_at 分桶,所有历史都
        # 堆到首次入库当天,左侧巨柱、中间空白.而 publish_time 为 NULL 的(主
        # 要是搜索引擎结果页未能解析发布日期)无法归到任一具体日期,如果回退
        # 到 ingested_at 又会重新制造首次入库当天的尖峰,所以直接丢弃.今日
        # KPI 仍按 ingested_at 统计,语义不同,允许不一致.
        trend_rows = list(conn.execute("""
            SELECT
                substr(p.publish_time, 1, 10) AS d,
                a.sentiment_label AS sl,
                count(*) AS c
            FROM posts p JOIN analyses a
              ON p.source = a.source AND p.post_id = a.post_id
            WHERE p.symbol = %s AND a.is_relevant = 1
              AND p.publish_time IS NOT NULL
              AND substr(p.publish_time, 1, 10) >= %s
            GROUP BY d, sl
            ORDER BY d ASC
        """, (ticker, cutoff)))

        trend_dict: dict[str, dict] = {}
        for r in trend_rows:
            d = r["d"]
            if not d:
                continue
            bucket = trend_dict.setdefault(d, {"date": d[5:], "bullish": 0, "neutral": 0, "bearish": 0, "mixed": 0})
            label = (r["sl"] or "").lower()
            if label in bucket:
                bucket[label] = (bucket[label] or 0) + r["c"]
            else:
                bucket["neutral"] += r["c"]

        # 补齐 N 天连续(没有数据的日期填 0)
        trend = []
        for i in range(days - 1, -1, -1):
            d = (date.today() - timedelta(days=i)).isoformat()
            if d in trend_dict:
                trend.append(trend_dict[d])
            else:
                trend.append({"date": d[5:], "bullish": 0, "neutral": 0, "bearish": 0, "mixed": 0})

        # 风险分布(新鲜度窗口内):用于饼图。同样按 publish_time 收口,不再算陈旧内容。
        risk_rows = list(conn.execute("""
            SELECT a.risk_level AS lvl, count(*) AS c
            FROM analyses a JOIN posts p
              ON a.source = p.source AND a.post_id = p.post_id
            WHERE a.symbol = %s AND a.is_relevant = 1
              AND COALESCE(p.publish_time, p.ingested_at) >= %s
            GROUP BY lvl
        """, (ticker, recency_cutoff)))
        RISK_COLORS = {"none": "#94a3b8", "low": "#fbbf24", "medium": "#fb923c", "high": "#ef4444"}
        risk_dist = []
        for lvl in ("none", "low", "medium", "high"):
            count = next((r["c"] for r in risk_rows if (r["lvl"] or "none") == lvl), 0)
            risk_dist.append({"level": lvl, "count": count, "color": RISK_COLORS[lvl]})

        # 最新简报
        brief = conn.execute(
            "SELECT * FROM briefs WHERE symbol = %s ORDER BY date DESC, id DESC LIMIT 1", (ticker,),
        ).fetchone()
        latest_brief = dict(brief) if brief else None

        # 高风险 Top 5(按 yuqin chat agent top_posts 同款公式)
        top_rows = list(conn.execute("""
            SELECT a.source, a.post_id, p.title, p.author, p.publish_time, p.url,
                   p.view_count, p.reply_count, p.content,
                   a.summary, a.sentiment_label, a.sentiment_score,
                   a.topics_json, a.entities_json, a.emotions_json,
                   a.stance, a.intent, a.factuality,
                   a.risk_level, a.risk_signals_json,
                   a.influence_potential, a.hidden_meaning, a.citations_json,
                   a.reasoning, a.is_relevant
            FROM analyses a JOIN posts p
              ON p.source = a.source AND p.post_id = a.post_id
            WHERE a.symbol = %s AND a.is_relevant = 1
              AND COALESCE(p.publish_time, p.ingested_at) >= %s
            ORDER BY (coalesce(a.influence_potential,0)
                     * abs(coalesce(a.sentiment_score,0)) + 0.01) DESC,
                     coalesce(p.view_count,0) DESC
            LIMIT 5
        """, (ticker, recency_cutoff)))
        top_posts = [_row_to_dict(r) for r in top_rows]

        total_today = kpi_row["total"] or 0
        high_risk_today = kpi_row["high_risk"] or 0
        avg_sentiment_today = float(kpi_row["avg_sentiment"]) if kpi_row["avg_sentiment"] is not None else 0.0
        total_prev = prev_row["total"] or 0
        high_risk_prev = prev_row["high_risk"] or 0
        avg_sentiment_prev = float(prev_row["avg_sentiment"]) if prev_row["avg_sentiment"] is not None else 0.0

        def _pct(curr: float, prev: float) -> int:
            if prev == 0:
                return 0
            return round((curr - prev) / abs(prev) * 100)

        return {
            "ticker": ticker,
            "kpi": {
                "total_today": total_today,
                "high_risk": high_risk_today,
                "avg_sentiment": avg_sentiment_today,
                "active_sources": kpi_row["active_sources"] or 0,
                "trend_total_pct": _pct(total_today, total_prev),
                "trend_risk_pct": _pct(high_risk_today, high_risk_prev),
                # 情感分数本身就在 -1..+1,差值 × 100 当百分点更直观
                "trend_sentiment_pct": round((avg_sentiment_today - avg_sentiment_prev) * 100),
            },
            "sentiment_trend": trend,
            "risk_dist": risk_dist,
            "latest_brief": latest_brief,
            "top_posts": top_posts,
        }


# ── helpers ────────────────────────────────────────────────────
from contextlib import contextmanager


@contextmanager
def _account_db_context(account_id: int):
    token = current_account.set(account_id)
    try:
        yield
    finally:
        current_account.reset(token)


def _summarize_plan(plan: dict) -> dict:
    """精简 plan 给客户端,避免传整个 LLM 输出."""
    return {
        "target": plan.get("target"),
        "ticker": plan.get("ticker"),
        "platforms_count": len(plan.get("platforms") or []),
        "queries_count": len(plan.get("queries") or []),
    }


def _row_to_dict(r) -> dict:
    """row(psycopg dict_row 已经是 dict)→ dict,JSON 字段反序列化."""
    d = dict(r)
    for k in ("emotions_json", "topics_json", "entities_json", "risk_signals_json", "citations_json"):
        if k in d and d[k]:
            try:
                d[k.replace("_json", "")] = json.loads(d[k])
            except Exception:
                pass
            del d[k]
    return d


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("SENTINEL_PORT", "8090"))
    uvicorn.run("service:app", host="0.0.0.0", port=port, log_level="info")
