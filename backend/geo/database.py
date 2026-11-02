from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./data/geo_checker.db"
    GOOGLE_CLIENT_ID: str = "test-google-client-id"
    SECRET_KEY: str

    # Resend transactional email (password reset, consultation ack, etc.)
    RESEND_API_KEY: str = ""
    FROM_EMAIL: str = "GEO Readiness Checker <noreply@vigilath.com>"
    FRONTEND_URL: str = "https://www.vigilath.com"
    # Inbox that receives /contact + /contact-sales submission notifications.
    SALES_NOTIFY_EMAIL: str = "support@zen7.com"

    # Stripe (used for overseas / English-locale credit card subscriptions)
    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_SUCCESS_URL: str = "http://localhost:5173/checkout/success"
    STRIPE_CANCEL_URL: str = "http://localhost:5173/checkout/cancel"
    STRIPE_TEST_MODE: bool = False

    # MoltsPay (USDC via x402 protocol)
    MOLTSPAY_ENABLED: bool = False
    MOLTSPAY_WALLET_ADDRESS: str = ""
    MOLTSPAY_CHAIN: str = "base"
    MOLTSPAY_SERVER_URL: str = "http://127.0.0.1:3010"

    # WeChat Pay (微信支付 Native Pay 扫码支付)
    WECHAT_PAY_ENABLED: bool = False
    WECHAT_PAY_APP_ID: str = ""             # 公众号/小程序 AppID
    WECHAT_PAY_MCH_ID: str = ""             # 商户号
    WECHAT_PAY_API_KEY_V3: str = ""         # APIv3 密钥 (32 字节)
    WECHAT_PAY_CERT_SERIAL: str = ""        # 商户证书序列号
    WECHAT_PAY_PRIVATE_KEY_PATH: str = ""   # 商户私钥 apiclient_key.pem 路径
    WECHAT_PAY_NOTIFY_URL: str = ""         # 支付结果回调通知 URL

    # AI engine keys (paid detection modes — entity / ai-visibility / citation-check).
    # Read by both the backend `geo` package and the standalone CLI tool spawned
    # as a subprocess; declared here so pydantic-settings won't drop them as
    # `extra` and so callers can use either `settings.OPENAI_API_KEY` or
    # `os.environ.get('OPENAI_API_KEY')` (systemd EnvironmentFile injects them
    # into the process environment).
    OPENAI_API_KEY: str = ""
    PERPLEXITY_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""

    # Mediumsly internal publish API. See backend/.env.example for the full
    # writeup. Empty token disables the publisher (publish flow degrades
    # gracefully — doc.mediumsly_last_error gets the reason).
    MEDIUMSLY_API_URL: str = "https://www.mediumsly.com"
    MEDIUMSLY_INTERNAL_API_TOKEN: str = ""
    MEDIUMSLY_EMAIL_DOMAIN_ALLOWLIST: str = ""  # comma-separated

    # 媒介星代理商发稿 API(docs/媒体API/产品文档-媒介星发文对接.md)。
    # 密钥为空 = 渠道未开通,client 拒绝发任何请求。
    MJX_API_BASE: str = "https://www.2016ruanwen.com"
    MJX_SECRET_ID: str = ""
    MJX_SECRET_KEY: str = ""
    MJX_PUBLISH_ENABLED: bool = False  # 真实下单独立闸,与 AGENT_ALLOW_EXTERNAL_PUBLISH 双闸

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()

_is_sqlite = "sqlite" in settings.DATABASE_URL
# 连接池按 env 配(geo-agent 多 worker 时每 worker 小池,避免撑爆 PG max_connections=100):
#   DB_POOL_SIZE / DB_MAX_OVERFLOW 默认 5 / 10(主后端不设 env → 维持原行为)。
#   geo-agent.service 设 DB_POOL_SIZE=3 / DB_MAX_OVERFLOW=5 → 每 worker 上限 8,8 worker 共 64。
if _is_sqlite:
    engine = create_engine(
        settings.DATABASE_URL,
        connect_args={"check_same_thread": False},
    )
else:
    engine = create_engine(
        settings.DATABASE_URL,
        pool_size=int(os.environ.get("DB_POOL_SIZE", "5")),
        max_overflow=int(os.environ.get("DB_MAX_OVERFLOW", "10")),
        pool_pre_ping=True,
        pool_recycle=1800,
    )


# ---------------------------------------------------------------------------
# SQLite pragma tuning
# ---------------------------------------------------------------------------
# Applied to every new connection opened by the engine. No-op for non-SQLite
# backends. The targets:
#
#   journal_mode=WAL      — readers don't block writers and vice versa;
#                           journal_mode is persistent (written once into
#                           the DB file), setting on every open is idempotent
#   synchronous=NORMAL    — fsync on transaction boundary instead of every
#                           write; 2-3x faster writes. A power cut may lose
#                           the last few milliseconds of uncommitted data —
#                           acceptable for this workload (auth / quota /
#                           payment sessions are re-submitted client-side).
#   cache_size=-64000     — 64 MB page cache (default 2 MB). The whole DB
#                           (~1.6 MB) fits here; every subsequent query is
#                           RAM-speed.
#   temp_store=MEMORY     — sort / group-by / view materialization uses RAM
#                           instead of /tmp files.
#   mmap_size=256MB       — read path uses memory-mapped I/O, skipping one
#                           kernel → userland copy per page read.
if "sqlite" in settings.DATABASE_URL:
    @event.listens_for(Engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _connection_record):
        # Only touch real SQLite connections — this listener fires for every
        # Engine in the process, so guard by class name to avoid clobbering
        # a future mixed setup.
        if type(dbapi_conn).__module__ != "sqlite3":
            return
        cur = dbapi_conn.cursor()
        try:
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA cache_size=-64000")
            cur.execute("PRAGMA temp_store=MEMORY")
            cur.execute("PRAGMA mmap_size=268435456")
        finally:
            cur.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()