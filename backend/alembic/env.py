"""Alembic environment.

Pulls DATABASE_URL from `geo.database.settings` so migrations always target
the same DB the app reads. `target_metadata = Base.metadata` makes
`alembic revision --autogenerate -m "..."` work for future schema changes.
"""
from logging.config import fileConfig
import sys
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Import the package so every ORM model registers itself on Base.metadata.
# geo/__init__.py used to call Base.metadata.create_all() as an import side
# effect, which clashed with alembic — that has been removed; importing geo
# is now pure metadata registration.
import geo  # noqa: F401
from geo.database import Base, settings

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _compare_type(_ctx, _col, _meta_col, inspected_type, metadata_type):
    """Skip noise from SQLite's lack of a VARCHAR/TEXT distinction.

    SQLite stores both as TEXT affinity, so an ORM `Column(String)` reading
    back from a column that was historically created via raw `ALTER TABLE …
    ADD COLUMN x TEXT` will always look like a type change to alembic.
    Returning False suppresses that one case; returning None falls back to
    alembic's default comparison so genuine type changes (e.g. Integer ↔
    String, JSON ↔ Text) still surface.
    """
    import sqlalchemy as sa
    str_like = (sa.String, sa.VARCHAR, sa.Text, sa.TEXT)
    if isinstance(inspected_type, str_like) and isinstance(metadata_type, str_like):
        return False
    return None


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=url.startswith("sqlite"),
        compare_type=_compare_type,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=settings.DATABASE_URL.startswith("sqlite"),
            compare_type=_compare_type,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
