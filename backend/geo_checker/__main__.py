#!/usr/bin/env python3
"""CLI entry point — argparse + dispatch to the appropriate mode.

Migrated from /geo_checker.py lines 7917-8065.

Usage (after `pip install -e .`):
    geo-checker https://example.com             # default: full GEO check
    geo-checker https://example.com --fix       # + fix recommendations
    geo-checker --compare url1 url2 url3        # side-by-side
    geo-checker --crawl-test https://ex.com     # AI crawler accessibility
    geo-checker --authority-audit https://ex.com
    geo-checker --aeo-visibility https://ex.com
    geo-checker --citation-check https://ex.com # paid, needs OPENROUTER_API_KEY
    geo-checker --ai-visibility https://ex.com  # paid
    geo-checker --entity "Brand Name"           # paid

Legacy `python geo_checker.py <url>` no longer works — the root file has
been deleted as part of the refactor. Use `python -m geo_checker` or the
installed `geo-checker` shim.

Note: --report pdf and --report html reference _TeeStream / _write_text_pdf
which are NOT defined in upstream. We preserve the buggy references for
parity; fixing requires a separate upstream PR.
"""

import argparse
import io
import os
import sys
from datetime import datetime

from . import state as _state
from .constants import FAIL
from .output import print
from .orchestrate import generate_score
from .modes.compare import compare_urls
from .modes.crawl_check import crawl_check_files, resolve_log_paths
from .modes.crawl_test import crawl_test
from .modes.authority_audit import authority_audit
from .modes.aeo import aeo_visibility
from .modes.citation import citation_check
from .modes.visibility import ai_visibility
from .modes.entity import entity_audit
from .reports import _write_json_report, _write_html_report


def main():
    parser = argparse.ArgumentParser(
        description="Check a website's GEO (Generative Engine Optimization) readiness."
    )
    parser.add_argument("url", nargs="?", help="The website URL to check (e.g. https://example.com)")
    parser.add_argument("--fix", action="store_true",
                        help="Show fix recommendations for each issue found")
    parser.add_argument("--compare", metavar="URL", nargs="+",
                        help="Compare GEO readiness across multiple URLs side-by-side. "
                             "Example: --compare https://site1.com https://site2.com")
    parser.add_argument("--crawl-check", metavar="LOG_PATTERN", nargs="+",
                        help="Analyze server access logs for AI/LLM crawler activity. "
                             "Accepts glob patterns (e.g. '/var/log/nginx/access*.log') "
                             "and .gz compressed files. Multiple patterns can be specified.")
    parser.add_argument("--crawl-test", metavar="URL",
                        help="Test if a site is accessible to AI crawlers without needing log files. "
                             "Checks robots.txt rules, simulates bot requests, and queries external indexes.")
    parser.add_argument("--authority-audit", metavar="URL",
                        help="Audit off-page authority signals: online reviews, awards/accreditations, "
                             "Google authority, and authoritative list mentions.")
    parser.add_argument("--citation-check", metavar="URL",
                        help="[PAID] Check if a site is being cited by AI engines. "
                             "Requires OPENROUTER_API_KEY environment variable.")
    parser.add_argument("--ai-visibility", metavar="URL",
                        help="[PAID] Comprehensive AI Visibility Audit. "
                             "Requires OPENROUTER_API_KEY environment variable.")
    parser.add_argument("--queries", metavar="QUERY", nargs="+",
                        help="Custom queries for --ai-visibility.")
    parser.add_argument("--aeo-visibility", metavar="URL",
                        help="AEO (Answer Engine Optimization) audit. Free — no API keys required.")
    parser.add_argument("--entity", metavar="NAME",
                        help="[PAID] Audit GEO readiness of a brand, product, or person by name. "
                             "Requires OPENROUTER_API_KEY environment variable.")
    parser.add_argument("--entity-type", metavar="TYPE", default="brand",
                        choices=["brand", "product", "person"],
                        help="Entity type for --entity audit: brand, product, or person (default: brand)")
    parser.add_argument("--report", nargs="?", const="pdf", default=None,
                        choices=["pdf", "json", "html"],
                        metavar="FORMAT",
                        help="Also save the run's output as a report at "
                             "~/geo_reports/<timestamp>/report.<ext>. "
                             "Default format is pdf. Pass 'json' for a machine-readable "
                             "score document or 'html' for a styled standalone page.")
    parser.add_argument("--lang", choices=["en", "zh"], default="en",
                        help="Output language: en (English) or zh (Chinese)")
    args = parser.parse_args()

    _state.SHOW_FIX = args.fix

    report_format = args.report  # None | "pdf" | "json" | "html"
    capture_output = report_format in ("pdf", "html")
    report_buffer = io.StringIO() if capture_output else None
    original_stdout = None
    if capture_output:
        original_stdout = sys.stdout
        sys.stdout = _TeeStream(original_stdout, report_buffer)  # noqa: F821 — upstream bug

    try:
        _dispatch(args, parser)
    finally:
        if capture_output:
            sys.stdout = original_stdout
        if report_format:
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            report_dir = os.path.expanduser(f"~/geo_reports/{timestamp}")
            text_output = report_buffer.getvalue() if report_buffer else ""

            if report_format == "pdf":
                report_path = os.path.join(report_dir, "report.pdf")
                try:
                    _write_text_pdf(report_path, text_output)  # noqa: F821 — upstream bug
                    print(f"\nPDF report saved to: {report_path}")
                except Exception as e:
                    print(f"\nFailed to write PDF report: {e}", file=sys.stderr)
            elif report_format == "json":
                json_path = os.path.join(report_dir, "report.json")
                try:
                    _write_json_report(json_path, args, timestamp)
                    print(f"\nJSON report saved to: {json_path}")
                except Exception as e:
                    print(f"\nFailed to write JSON report: {e}", file=sys.stderr)
            elif report_format == "html":
                html_path = os.path.join(report_dir, "report.html")
                try:
                    _write_html_report(html_path, text_output, args, timestamp)
                    print(f"\nHTML report saved to: {html_path}")
                except Exception as e:
                    print(f"\nFailed to write HTML report: {e}", file=sys.stderr)


def _dispatch(args, parser):
    if args.entity:
        entity_audit(args.entity, entity_type=args.entity_type)
    elif args.aeo_visibility:
        aeo_visibility(args.aeo_visibility)
    elif args.compare:
        compare_urls(args.compare)
    elif args.ai_visibility:
        ai_visibility(args.ai_visibility, custom_queries=args.queries)
    elif args.citation_check:
        citation_check(args.citation_check)
    elif args.authority_audit:
        authority_audit(args.authority_audit)
    elif args.crawl_test:
        crawl_test(args.crawl_test)
    elif args.crawl_check:
        all_files = []
        for pattern in args.crawl_check:
            resolved = resolve_log_paths(pattern)
            all_files.extend(resolved)
        seen = set()
        unique_files = []
        for f in all_files:
            real = os.path.realpath(f)
            if real not in seen:
                seen.add(real)
                unique_files.append(f)
        if not unique_files:
            print(f"  [{FAIL}] No log files matched the given pattern(s)")
        else:
            display = " ".join(args.crawl_check)
            crawl_check_files(unique_files, display)
    elif args.url:
        generate_score(args.url)
    else:
        parser.error("Provide a URL or a mode flag: --compare, --crawl-check, "
                     "--crawl-test, --citation-check, --ai-visibility, "
                     "--aeo-visibility, --entity")


if __name__ == "__main__":
    main()
