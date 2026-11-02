"""Report writers: JSON + HTML output.

Migrated from /geo_checker.py lines 7175-7899.

Consumed by the CLI `--report` and `--html-report` flags; the backend API
path does not use these (it parses stdout directly via parse_geo_output).
"""

import json
import os
import re
import sys
from datetime import datetime

from .state import _scores, get_ai_visibility_score, get_grade
from .output import print

def _scores_snapshot():
    """Return a serializable copy of the current score state."""
    total_earned = sum(v["earned"] for v in _scores.values())
    total_max = sum(v["max"] for v in _scores.values())
    overall = round((total_earned / total_max) * 100) if total_max > 0 else 0
    return {
        "overall_score": overall,
        "grade": get_grade(overall),
        "total_earned": round(total_earned, 1),
        "total_max": round(total_max, 1),
        "categories": {
            cat: {
                "earned": round(vals["earned"], 2),
                "max": round(vals["max"], 2),
                "percent": round((vals["earned"] / vals["max"]) * 100, 1) if vals["max"] > 0 else 0,
            }
            for cat, vals in sorted(_scores.items())
        },
    }


def _write_json_report(path, args, timestamp):
    """Write a machine-readable JSON report."""
    import os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "schema_version": 1,
        "generated_at": timestamp,
        "tool": "geo_checker",
        "mode": _active_mode(args),
        "target": _active_target(args),
        "fix_mode": bool(args.fix),
        "score": _scores_snapshot(),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=False)


def _active_mode(args):
    if args.entity:
        return "entity"
    if args.compare:
        return "compare"
    if args.ai_visibility:
        return "ai-visibility"
    if args.citation_check:
        return "citation-check"
    if args.authority_audit:
        return "authority-audit"
    if args.crawl_test:
        return "crawl-test"
    if args.crawl_check:
        return "crawl-check"
    return "default"


def _active_target(args):
    return (
        args.entity or args.ai_visibility or args.citation_check or args.authority_audit
        or args.crawl_test or args.url or (args.compare[0] if args.compare else None)
    )


def _write_html_report(path, terminal_text, args, timestamp):
    """Write a styled HTML report with scores and captured terminal output."""
    import html as html_mod
    import os
    os.makedirs(os.path.dirname(path), exist_ok=True)

    snap = _scores_snapshot()
    target = _active_target(args) or ""
    mode = _active_mode(args)
    cleaned_text = _strip_ansi(terminal_text or "")

    def grade_color(grade):
        return {
            "A+": "#16a34a", "A": "#22c55e",
            "B": "#84cc16", "C": "#eab308",
            "D": "#f97316", "F": "#ef4444",
        }.get(grade, "#64748b")

    overall = snap["overall_score"]
    grade = snap["grade"]

    rows = []
    for cat, vals in snap["categories"].items():
        pct = vals["percent"]
        bar_color = "#22c55e" if pct >= 70 else "#eab308" if pct >= 40 else "#ef4444"
        rows.append(f"""
      <tr>
        <td>{html_mod.escape(cat)}</td>
        <td class="num">{vals['earned']}/{vals['max']}</td>
        <td class="bar-cell"><div class="bar"><div class="bar-fill" style="width:{pct}%;background:{bar_color}"></div></div></td>
        <td class="num">{pct:.0f}%</td>
      </tr>""")

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>GEO Readiness Report — {html_mod.escape(target)}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: -apple-system, system-ui, sans-serif; max-width: 960px; margin: 2rem auto; padding: 0 1rem; color: #0f172a; background: #f8fafc; }}
  header {{ display: flex; align-items: center; gap: 1.5rem; padding: 1.5rem; background: #fff; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
  .score {{ font-size: 3rem; font-weight: 700; color: {grade_color(grade)}; line-height: 1; }}
  .grade {{ font-size: 2rem; font-weight: 700; color: {grade_color(grade)}; }}
  h1 {{ margin: 0 0 0.25rem; font-size: 1.25rem; }}
  .meta {{ color: #64748b; font-size: 0.9rem; }}
  section {{ margin-top: 2rem; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
  th, td {{ padding: 0.6rem 0.8rem; text-align: left; border-bottom: 1px solid #e2e8f0; }}
  th {{ background: #f1f5f9; font-weight: 600; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.03em; color: #475569; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
  td.bar-cell {{ width: 40%; }}
  .bar {{ background: #e2e8f0; height: 10px; border-radius: 5px; overflow: hidden; }}
  .bar-fill {{ height: 100%; border-radius: 5px; }}
  pre {{ background: #0f172a; color: #e2e8f0; padding: 1rem; border-radius: 8px; overflow-x: auto; font-size: 0.8rem; line-height: 1.4; white-space: pre-wrap; word-break: break-word; }}
  footer {{ margin-top: 2rem; color: #94a3b8; font-size: 0.8rem; text-align: center; }}
</style>
</head>
<body>
<header>
  <div class="score">{overall}<span style="font-size:1.5rem;color:#94a3b8;">/100</span></div>
  <div class="grade">{grade}</div>
  <div>
    <h1>GEO Readiness Report</h1>
    <div class="meta">{html_mod.escape(target)} &middot; mode: {mode} &middot; generated {timestamp}</div>
  </div>
</header>

<section>
  <h2>Category Breakdown</h2>
  <table>
    <thead><tr><th>Category</th><th class="num">Score</th><th>Progress</th><th class="num">%</th></tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
</section>

<section>
  <h2>Run Output</h2>
  <pre>{html_mod.escape(cleaned_text)}</pre>
</section>

<footer>Generated by geo_checker &middot; <a href="https://github.com/anthropics/claude-code">geo</a></footer>
</body>
</html>
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html_doc)


# ---------------------------------------------------------------------------
# Chinese translation table  (populated here, used by _tr() at module top)
# ---------------------------------------------------------------------------
