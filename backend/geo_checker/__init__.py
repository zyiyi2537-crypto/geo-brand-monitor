"""GEO Readiness Checker — Check a website's Generative Engine Optimization readiness.

This package re-exports the public API so backend callers and external users
can `from geo_checker import generate_score, ai_visibility, ...` without
knowing the internal module layout.

Internal structure:
    constants.py     — AI bot lists, ANSI color tags
    state.py         — SHOW_FIX / _scores / _page_cache / reset_state
    io.py            — fetch / get_soup / get_text_content
    output.py        — emit_check / emit_fix / print shim / _ZH i18n table
    checks.py        — 25 check_* functions (core inspection logic)
    orchestrate.py   — CHECK_REGISTRY / generate_score / run_silent
    modes/*.py       — compare, crawl_check, crawl_test, aeo, authority_audit,
                       citation, visibility, entity (one mode per file)
    ai.py            — _query_* engines + response analyzers
    reports.py       — JSON / HTML report writers (CLI-only)
    __main__.py      — argparse CLI entry (`geo-checker ...`)
"""

__version__ = "2.1.0"  # 2.0.0: package refactor | 2.1.0: top-level concurrency (baidu 124s → 37s)

# State + low-level utilities
from .state import (
    SHOW_FIX,
    _scores,
    _page_cache,
    reset_state,
    track_score,
    get_ai_visibility_score,
    get_grade,
)
from .io import fetch, get_soup, get_text_content, flesch_kincaid_grade
from .output import (
    emit_check,
    emit_fix,
    fix,
    LANG,
    _ZH,
    _tr,
)
from .constants import (
    AI_BOTS,
    AI_CRAWLERS,
    PASS,
    WARN,
    FAIL,
    INFO,
    FIX,
)

# Core checks
from . import checks as _checks_module
from .checks import (
    check_https,
    check_robots_txt,
    check_llms_txt,
    check_well_known,
    check_sitemap,
    check_search_engine_registration,
    check_structured_data,
    check_meta_tags,
    check_content_accessibility,
    check_ai_crawl_readiness,
    check_content_quality,
    check_technical_crawlability,
    check_authority_trust,
    check_brand_entity_kg,
    check_trust_safety,
    check_ai_optimization,
    check_social_signals,
    check_ai_answer_formats,
    check_schema_knowledge,
    check_mobile_and_weight,
    check_url_normalization,
    check_outbound_and_media,
    check_multilingual_depth,
    check_cross_platform,
    check_multi_page,
)

# Orchestration
from .orchestrate import (
    CHECK_REGISTRY,
    ALL_CATEGORIES,
    FREE_CATEGORIES,
    generate_score,
    run_silent,
    _run_checks,
)

# Advanced modes (each `return_data=True` path used by the FastAPI
# backend — see backend/geo/services/advanced_runners.py)
from .modes.compare import compare_urls
from .modes.crawl_check import (
    crawl_check,
    crawl_check_files,
    resolve_log_paths,
    open_log_file,
    parse_log_line,
    parse_timestamp,
)
from .modes.crawl_test import crawl_test
from .modes.authority_audit import authority_audit
from .modes.aeo import aeo_visibility
from .modes.citation import citation_check
from .modes.visibility import ai_visibility
from .modes.entity import (
    entity_audit,
    _check_knowledge_graph,
    _check_cross_platform_footprint,
)

# AI query helpers (used by modes; exported for advanced integrations)
from .ai import (
    _query_perplexity,
    _query_openai,
    _query_anthropic,
    _query_deepseek,
    _query_doubao,
    _check_brand_in_result,
    _extract_competitors,
    _classify_framing,
)

# Note: deliberately NOT importing .__main__ here — Python's `python -m geo_checker`
# complains with a RuntimeWarning when __main__ is imported indirectly via
# __init__.py before being run. Users who want `main` can do:
#   from geo_checker.__main__ import main


__all__ = [
    # Public API
    "generate_score",
    "run_silent",
    "compare_urls",
    "crawl_check",
    "crawl_test",
    "authority_audit",
    "aeo_visibility",
    "citation_check",
    "ai_visibility",
    "entity_audit",
    # Constants
    "CHECK_REGISTRY",
    "ALL_CATEGORIES",
    "FREE_CATEGORIES",
    "AI_BOTS",
    "AI_CRAWLERS",
    "PASS",
    "WARN",
    "FAIL",
    "INFO",
    "FIX",
    # State / utilities
    "SHOW_FIX",
    "reset_state",
    "track_score",
    "fetch",
    "get_soup",
    "emit_check",
    "emit_fix",
    "fix",
]
