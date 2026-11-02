"""SQLAlchemy ORM 模型 + Pydantic schemas — 舆情账号 / 知识库 / 任务日志.

数据库:走 GEO 主 SQLAlchemy DB(geo_checker.db).
yuqin 自己的表(posts/analyses/briefs/drafts)由 sentinel-service 微服务管理,
不在这里建模 — 前端取数走 sentinel-service GET 接口.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from geo.database import Base


KeywordKind = Literal["entity", "legal", "exec", "project", "competitor", "custom"]


class KeywordItem(BaseModel):
    term: str = Field(..., min_length=1)
    is_new: Optional[bool] = None
    enabled: Optional[bool] = None
    note: Optional[str] = None


class KeywordGroup(BaseModel):
    name: str = Field(..., min_length=1)
    kind: KeywordKind
    items: list[KeywordItem] = Field(default_factory=list)


def flatten_keyword_groups(groups: list[KeywordGroup]) -> list[str]:
    """把分组展开成扁平 keyword 列表(发给 sentinel-service 用),enabled=False 的跳过."""
    seen: set[str] = set()
    out: list[str] = []
    for g in groups:
        for it in g.items:
            if it.enabled is False:
                continue
            t = it.term.strip()
            if t and t not in seen:
                seen.add(t)
                out.append(t)
    return out


# ─────────────────────────── ORM ──────────────────────────────


class SentimentAccountORM(Base):
    """用户的舆情监测账号(配置 + 状态机)."""
    __tablename__ = "sentiment_accounts"
    __table_args__ = (UniqueConstraint("user_id", "ticker", name="uq_user_ticker"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    target = Column(String, nullable=False)             # 品牌名
    ticker = Column(String, nullable=False)             # = sentinel-service 的 symbol
    aliases_json = Column(Text, default="[]")
    intent = Column(Text, nullable=True)
    keywords_json = Column(Text, default="[]")
    # 结构化分组:list[KeywordGroup],用于 UI 分类管理 + 从 Excel 导入.
    # 旧字段 keywords_json 保留为扁平回退;pipeline 优先用 keyword_groups_json 展平后的结果.
    keyword_groups_json = Column(Text, default="[]")
    excludes_json = Column(Text, default="[]")
    # 媒体白名单(平台 code 列表,例:["xueqiu","weibo"]).空 list = 全 15 个平台都跑.
    # 与 services/sentinel-service/search/plan.py 的 PLATFORM_CATALOG 对齐.
    media_allowlist_json = Column(Text, default="[]")
    notify_emails_json = Column(Text, default="[]")

    # 微信公众号合集 URL 列表 — 周级别盯防 KOL/竞品官号,getalbum 接口枚举.
    # 空 list = 不启用 weixin_album crawler.
    weixin_album_urls_json = Column(Text, nullable=False, default="[]", server_default="[]")
    # newsnow source id 列表(如 ['weibo','zhihu','v2ex','toutiao'])— 走自托管
    # newsnow 容器拉热榜,本地按 aliases+keywords 过滤标题.空 list = 不启用.
    newsnow_sources_json = Column(Text, nullable=False, default="[]", server_default="[]")

    active = Column(Boolean, nullable=False, default=True)

    # 任务状态机
    last_run_at = Column(DateTime, nullable=True)
    last_run_status = Column(String, nullable=True)     # pending / running / success / failed
    last_run_error = Column(Text, nullable=True)
    last_run_stats = Column(Text, nullable=True)        # JSON: {monitor:{...}, analyze:{...}, brief:{...}}

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    knowledge = relationship("SentimentKnowledgeORM", back_populates="account",
                             cascade="all, delete-orphan")
    run_logs = relationship("SentimentRunLogORM", back_populates="account",
                            cascade="all, delete-orphan")


class SentimentKnowledgeORM(Base):
    """知识库 3 文档(brand_voice / legal_redlines / response_playbook)."""
    __tablename__ = "sentiment_knowledge"
    __table_args__ = (UniqueConstraint("account_id", "key", name="uq_account_key"),)

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("sentiment_accounts.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    key = Column(String, nullable=False)                # brand_voice / legal_redlines / response_playbook
    body = Column(Text, nullable=False, default="")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    account = relationship("SentimentAccountORM", back_populates="knowledge")


class SentimentRunLogORM(Base):
    """任务执行日志(用于排障 + 历史展示)."""
    __tablename__ = "sentiment_run_logs"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("sentiment_accounts.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    trigger = Column(String, nullable=False)            # first_run / cron / manual
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    status = Column(String, nullable=False)             # running / success / failed
    error = Column(Text, nullable=True)
    stats_json = Column(Text, nullable=True)            # 同 last_run_stats 形态
    duration_s = Column(Integer, nullable=True)

    account = relationship("SentimentAccountORM", back_populates="run_logs")


class SentimentPlatformORM(Base):
    """媒体平台目录(全局配置,非用户私有).
    取代之前散落在 3 处的硬编码:
      - frontend/src/constants/sentimentPlatforms.ts
      - services/sentinel-service/search/plan.py PLATFORM_CATALOG
      - backend/geo/services/sentinel_client.py _PLATFORM_CODE_TO_DOMAIN
    新增平台 / 改 domain / 调地区分类只需 INSERT/UPDATE 此表 — 不用改代码、不用重启。
    Seed 由 migrations/010_sentiment_platforms.py 注入。"""
    __tablename__ = "sentiment_platforms"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, nullable=False, unique=True, index=True)  # 'xueqiu', 'eastmoney' …
    domain = Column(String, nullable=False)                          # 'xueqiu.com',传给 sentinel `site:` 用
    # category 是 010 的 legacy 单轴(finance/social/forum/video/news/overseas),
    # 011 起拆为正交两维 media_type + industry — UI 只读后两个,category 仅作为
    # legacy 列存在以避免破坏既有 INSERT 行;新代码不要依赖。
    category = Column(String, nullable=False)
    media_type = Column(String, nullable=False, default="")          # web/weibo/wechat/app/forum/short_video/long_video/...
    industry = Column(String, nullable=False, default="")            # finance/general/tech/science/party_media/health/overseas_en
    region = Column(String, nullable=False)                          # mainland / hk / overseas
    name_zh = Column(String, nullable=False, default="")
    name_en = Column(String, nullable=False, default="")
    sort_order = Column(Integer, nullable=False, default=0)          # 同分类内排序
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


# ─────────────────────────── Pydantic ─────────────────────────


class SentimentAccountCreate(BaseModel):
    target: str = Field(..., min_length=1)
    ticker: str = Field(..., min_length=1)
    aliases: list[str] = Field(default_factory=list)
    intent: Optional[str] = None
    keywords: list[str] = Field(default_factory=list)
    keyword_groups: list[KeywordGroup] = Field(default_factory=list)
    excludes: list[str] = Field(default_factory=list)
    media_allowlist: list[str] = Field(default_factory=list)
    notify_emails: list[EmailStr] = Field(default_factory=list, max_length=10)
    weixin_album_urls: list[str] = Field(default_factory=list)
    newsnow_sources: list[str] = Field(default_factory=list)
    run_now: bool = True


class SentimentAccountUpdate(BaseModel):
    target: Optional[str] = None
    ticker: Optional[str] = None
    aliases: Optional[list[str]] = None
    intent: Optional[str] = None
    keywords: Optional[list[str]] = None
    keyword_groups: Optional[list[KeywordGroup]] = None
    excludes: Optional[list[str]] = None
    media_allowlist: Optional[list[str]] = None
    notify_emails: Optional[list[EmailStr]] = None
    weixin_album_urls: Optional[list[str]] = None
    newsnow_sources: Optional[list[str]] = None
    active: Optional[bool] = None


class SentimentAccountOut(BaseModel):
    id: int
    user_id: int
    target: str
    ticker: str
    aliases: list[str]
    intent: Optional[str]
    keywords: list[str]
    keyword_groups: list[KeywordGroup] = Field(default_factory=list)
    excludes: list[str]
    media_allowlist: list[str]
    notify_emails: list[str]
    weixin_album_urls: list[str] = Field(default_factory=list)
    newsnow_sources: list[str] = Field(default_factory=list)
    active: bool
    last_run_at: Optional[datetime]
    last_run_status: Optional[str]
    last_run_error: Optional[str]
    created_at: datetime

    @classmethod
    def from_orm_row(cls, row: SentimentAccountORM) -> "SentimentAccountOut":
        groups_raw = json.loads(row.keyword_groups_json or "[]")
        groups = [KeywordGroup.model_validate(g) for g in groups_raw]
        return cls(
            id=row.id, user_id=row.user_id,
            target=row.target, ticker=row.ticker,
            aliases=json.loads(row.aliases_json or "[]"),
            intent=row.intent,
            keywords=json.loads(row.keywords_json or "[]"),
            keyword_groups=groups,
            excludes=json.loads(row.excludes_json or "[]"),
            media_allowlist=json.loads(row.media_allowlist_json or "[]"),
            notify_emails=json.loads(row.notify_emails_json or "[]"),
            weixin_album_urls=json.loads(row.weixin_album_urls_json or "[]"),
            newsnow_sources=json.loads(row.newsnow_sources_json or "[]"),
            active=row.active,
            last_run_at=_as_utc(row.last_run_at),
            last_run_status=row.last_run_status,
            last_run_error=row.last_run_error,
            created_at=_as_utc(row.created_at),
        )


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """把 SQLite 读出的 naive datetime(实际是 UTC,因 pipeline 用 datetime.utcnow()
    写入)显式标注为 UTC tz-aware,这样 Pydantic 序列化时会输出 ISO 8601 带
    '+00:00' 后缀,前端 new Date() 才能正确解析为 UTC.

    否则前端 timeAgo() 会把无 tz 字符串当成本地时间(UTC+8),显示成"8 小时前"."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class RunStatusOut(BaseModel):
    status: Optional[str]
    last_run_at: Optional[datetime]
    error: Optional[str]


class KnowledgeOut(BaseModel):
    key: str
    body: str
    updated_at: datetime


class SentimentPlatformOut(BaseModel):
    code: str
    domain: str
    # category 是 legacy 单轴,前端不再消费;保留输出供调试 / 旧客户端兼容。
    category: str
    # 011 起的正交两维 — UI 渲染 filter 用这两个。空字符串表示后端未跑 011。
    media_type: str = ""
    industry: str = ""
    region: str
    name_zh: str
    name_en: str

    @classmethod
    def from_orm_row(cls, row: SentimentPlatformORM) -> "SentimentPlatformOut":
        return cls(
            code=row.code, domain=row.domain,
            category=row.category,
            media_type=row.media_type or "",
            industry=row.industry or "",
            region=row.region,
            name_zh=row.name_zh or "", name_en=row.name_en or "",
        )
