"""crawl_check — parse nginx/apache access logs for AI crawler activity.

Migrated from /geo_checker.py lines 3618-3829.
"""

import gzip
import glob
import os
import re
import sys
from collections import defaultdict
from datetime import datetime

from ..constants import AI_CRAWLERS, PASS, WARN, FAIL, INFO, FIX
from ..output import print, fix


def parse_log_line(line):
    """Parse a single access log line (Common Log Format or Combined).

    Tolerates an optional ``$host`` token between the timestamp and the request
    (nginx ``with_host`` log_format) and ignores any trailing fields such as
    ``rt=`` / ``uct=`` / ``urt=`` — re.match anchors at the start only.
    """
    # Combined/Common:  66.249.66.1 - - [ts] "GET /page HTTP/1.1" 200 1234 "-" "UA"
    # with_host (nginx): 1.2.3.4 - - [ts] www.example.com "GET /page HTTP/1.1" 200 1234 "-" "UA" rt=0.0
    pattern = (
        r'^(\S+)\s+'           # IP
        r'\S+\s+\S+\s+'       # ident, authuser
        r'\[([^\]]+)\]\s+'    # timestamp
        r'(?:[^"\s]+\s+)?'    # optional $host (with_host format) — non-capturing
        r'"(\S+)\s+(\S+)\s+[^"]*"\s+'  # method, path
        r'(\d{3})\s+'         # status
        r'(\S+)'              # size
        r'(?:\s+"([^"]*)"\s+"([^"]*)")?'  # referer, user-agent (optional)
    )
    m = re.match(pattern, line)
    if not m:
        return None
    return {
        "ip": m.group(1),
        "timestamp": m.group(2),
        "method": m.group(3),
        "path": m.group(4),
        "status": int(m.group(5)),
        "size": m.group(6),
        "referer": m.group(7) or "-",
        "user_agent": m.group(8) or "",
    }


def parse_timestamp(ts_str):
    """Parse log timestamp like '10/Apr/2026:12:34:56 +0000' into datetime."""
    from datetime import datetime
    try:
        return datetime.strptime(ts_str.split()[0], "%d/%b/%Y:%H:%M:%S")
    except (ValueError, IndexError):
        return None


def resolve_log_paths(log_pattern):
    """Resolve a log path or glob pattern into a sorted list of files.
    Supports glob wildcards (*, ?, []) and also handles .gz compressed logs.
    """
    import glob as glob_mod
    import os

    paths = sorted(glob_mod.glob(log_pattern))
    if not paths:
        # Maybe it's a literal path without wildcards
        if os.path.isfile(log_pattern):
            return [log_pattern]
        return []
    return [p for p in paths if os.path.isfile(p)]


def open_log_file(path):
    """Open a log file, handling .gz compression transparently."""
    import gzip
    if path.endswith(".gz"):
        return gzip.open(path, "rt", errors="replace")
    return open(path, "r", errors="replace")


def analyze_crawl_logs(log_files):
    """Analyze access logs and return AI/LLM crawler activity as a JSON-serializable dict.

    Same computation as ``crawl_check_files()`` but returns structured data instead
    of printing — used by the admin crawl-analysis API. ``first_seen`` / ``last_seen``
    are computed from parsed timestamps (min/max), not file order, so rotated/gzipped
    logs read out of chronological order still report correct bounds.
    """
    import os
    from collections import defaultdict

    bot_hits = defaultdict(list)      # bot_name -> list of {path, timestamp, ts, status, ip}
    bot_pages = defaultdict(set)
    bot_ips = defaultdict(set)
    total_lines = 0
    parsed_lines = 0
    first_ts = None
    last_ts = None

    readable_files = []
    for log_file in log_files:
        try:
            f = open_log_file(log_file)
        except OSError:
            continue  # 不可读(权限/损坏)的日志直接跳过,不让整个分析 500
        readable_files.append(log_file)
        with f:
            for line in f:
                total_lines += 1
                entry = parse_log_line(line.strip())
                if not entry:
                    continue
                parsed_lines += 1
                ua = entry["user_agent"]
                if not ua:
                    continue
                ts = parse_timestamp(entry["timestamp"])
                if ts:
                    if first_ts is None or ts < first_ts:
                        first_ts = ts
                    if last_ts is None or ts > last_ts:
                        last_ts = ts
                for bot_name, bot_info in AI_CRAWLERS.items():
                    if re.search(bot_info["pattern"], ua):
                        bot_hits[bot_name].append({
                            "path": entry["path"],
                            "timestamp": entry["timestamp"],
                            "ts": ts,
                            "status": entry["status"],
                            "ip": entry["ip"],
                        })
                        bot_pages[bot_name].add(entry["path"])
                        bot_ips[bot_name].add(entry["ip"])
                        break

    bots = []
    for bot_name, hits in sorted(bot_hits.items(), key=lambda x: len(x[1]), reverse=True):
        info = AI_CRAWLERS[bot_name]
        status_counts = defaultdict(int)
        page_counts = defaultdict(int)
        for h in hits:
            status_counts[h["status"]] += 1
            page_counts[h["path"]] += 1
        top_pages = sorted(page_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        ts_list = [h["ts"] for h in hits if h["ts"]]
        first_seen = min(ts_list).isoformat() if ts_list else hits[0]["timestamp"]
        last_seen = max(ts_list).isoformat() if ts_list else hits[-1]["timestamp"]
        bots.append({
            "name": bot_name,
            "powers": info["powers"],
            "importance": info["importance"],
            "requests": len(hits),
            "unique_pages": len(bot_pages[bot_name]),
            "ips": len(bot_ips[bot_name]),
            "status_codes": {str(k): v for k, v in sorted(status_counts.items())},
            "first_seen": first_seen,
            "last_seen": last_seen,
            "top_pages": [{"path": p, "count": c} for p, c in top_pages],
        })

    missing_critical = [
        {"name": n, "powers": AI_CRAWLERS[n]["powers"]}
        for n in AI_CRAWLERS
        if n not in bot_hits and AI_CRAWLERS[n]["importance"] == "critical"
    ]
    missing_optional = [
        {"name": n, "powers": AI_CRAWLERS[n]["powers"]}
        for n in AI_CRAWLERS
        if n not in bot_hits and AI_CRAWLERS[n]["importance"] == "optional"
    ]

    return {
        "files": [
            {
                "path": f,
                "size_mb": round(os.path.getsize(f) / 1024 / 1024, 2),
                "gzipped": f.endswith(".gz"),
            }
            for f in readable_files
        ],
        "total_size_mb": round(sum(os.path.getsize(f) for f in readable_files) / 1024 / 1024, 2),
        "total_lines": total_lines,
        "parsed_lines": parsed_lines,
        "period": {
            "first": first_ts.isoformat() if first_ts else None,
            "last": last_ts.isoformat() if last_ts else None,
        },
        "total_bot_requests": sum(len(h) for h in bot_hits.values()),
        "bots": bots,
        "missing_critical": missing_critical,
        "missing_optional": missing_optional,
    }


def crawl_check(log_pattern):
    """Convenience wrapper: resolve a single glob pattern and analyze."""
    import os
    log_files = resolve_log_paths(log_pattern)
    if not log_files:
        print(f"  [{FAIL}] No log files matched: {log_pattern}")
        return
    crawl_check_files(log_files, log_pattern)


def crawl_check_files(log_files, display_pattern=""):
    """Analyze server access logs for AI/LLM crawler activity.
    Accepts a list of file paths. Handles .gz compressed rotated logs.
    """
    import os
    from collections import defaultdict

    total_size = sum(os.path.getsize(f) for f in log_files)
    print(f"\n{'='*60}")
    print(f"  AI/LLM Crawl Activity Report")
    print(f"  Pattern: {display_pattern}")
    print(f"  Files matched: {len(log_files)} ({total_size / 1024 / 1024:.1f} MB total)")
    for lf in log_files:
        sz = os.path.getsize(lf)
        gz = " (gzipped)" if lf.endswith(".gz") else ""
        print(f"    - {lf} ({sz / 1024 / 1024:.1f} MB{gz})")
    print(f"{'='*60}")

    # Track per-bot stats
    bot_hits = defaultdict(list)      # bot_name -> list of {path, timestamp, status, ip}
    bot_pages = defaultdict(set)      # bot_name -> set of paths
    bot_ips = defaultdict(set)        # bot_name -> set of IPs
    total_lines = 0
    parsed_lines = 0
    first_ts = None
    last_ts = None

    for log_file in log_files:
        with open_log_file(log_file) as f:
            for line in f:
                total_lines += 1
                entry = parse_log_line(line.strip())
                if not entry:
                    continue
                parsed_lines += 1
                ua = entry["user_agent"]
                if not ua:
                    continue

                ts = parse_timestamp(entry["timestamp"])
                if ts:
                    if first_ts is None or ts < first_ts:
                        first_ts = ts
                    if last_ts is None or ts > last_ts:
                        last_ts = ts

                for bot_name, bot_info in AI_CRAWLERS.items():
                    if re.search(bot_info["pattern"], ua):
                        bot_hits[bot_name].append({
                            "path": entry["path"],
                            "timestamp": entry["timestamp"],
                            "status": entry["status"],
                            "ip": entry["ip"],
                        })
                        bot_pages[bot_name].add(entry["path"])
                        bot_ips[bot_name].add(entry["ip"])
                        break  # one bot per line

    # Summary
    print(f"\n  Log period: {first_ts or 'unknown'} → {last_ts or 'unknown'}")
    print(f"  Total lines: {total_lines:,} | Parsed: {parsed_lines:,}")
    print(f"  AI/LLM bot requests: {sum(len(h) for h in bot_hits.values()):,}")

    if not bot_hits:
        print(f"\n  [{WARN}] No AI/LLM crawler activity detected in this log file.")
        print(f"  [{INFO}] This could mean:")
        print(f"         - AI bots haven't discovered your site yet")
        print(f"         - The log file doesn't cover enough time")
        print(f"         - Bots are blocked by robots.txt or firewall")
        print(f"         - Your CDN/proxy strips bot user agents")
        fix("Register with Google Search Console and Bing Webmaster Tools to get indexed.\n"
            "Submit your sitemap.xml to each platform.\n"
            "Ensure robots.txt does not block AI crawlers.\n"
            "Check your CDN/WAF settings — some block bot traffic by default.")
        return

    # Per-bot breakdown
    print(f"\n--- Bot Activity Breakdown ---")
    sorted_bots = sorted(bot_hits.items(), key=lambda x: len(x[1]), reverse=True)
    for bot_name, hits in sorted_bots:
        info = AI_CRAWLERS[bot_name]
        pages = bot_pages[bot_name]
        ips = bot_ips[bot_name]
        status_counts = defaultdict(int)
        for h in hits:
            status_counts[h["status"]] += 1

        first_hit = hits[0]["timestamp"]
        last_hit = hits[-1]["timestamp"]

        print(f"\n  [{PASS}] {bot_name}")
        print(f"         Powers: {info['powers']}")
        print(f"         Requests: {len(hits):,} | Unique pages: {len(pages)} | IPs: {len(ips)}")
        print(f"         Status codes: {dict(status_counts)}")
        print(f"         First seen: {first_hit}")
        print(f"         Last seen:  {last_hit}")

        # Top pages
        page_counts = defaultdict(int)
        for h in hits:
            page_counts[h["path"]] += 1
        top_pages = sorted(page_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        print(f"         Top pages:")
        for path, count in top_pages:
            print(f"           {count:>5}x  {path}")

    # Bots NOT seen — split by importance
    missing_critical = [n for n in AI_CRAWLERS if n not in bot_hits and AI_CRAWLERS[n]["importance"] == "critical"]
    missing_optional = [n for n in AI_CRAWLERS if n not in bot_hits and AI_CRAWLERS[n]["importance"] == "optional"]

    if missing_critical:
        print(f"\n--- Critical Bots NOT Detected ---")
        for bot_name in missing_critical:
            info = AI_CRAWLERS[bot_name]
            print(f"  [{WARN}] {bot_name} — {info['powers']}")
        fix("These are core AI crawlers. If missing, your content may not appear in their AI products.\n"
            "Ensure you are registered with the corresponding search platforms.\n"
            "Check that robots.txt does not block these user agents.\n"
            "Submit your sitemap to Google Search Console and Bing Webmaster Tools.")

    if missing_optional:
        print(f"\n--- Optional Bots NOT Detected ---")
        for bot_name in missing_optional:
            info = AI_CRAWLERS[bot_name]
            print(f"  [{INFO}] {bot_name} — {info['powers']}")

    missing_bots = missing_critical + missing_optional

    # Summary table
    print(f"\n--- Summary ---")
    print(f"  {'Bot':<25} {'Requests':>10} {'Pages':>8} {'Last Seen':>25}")
    print(f"  {'-'*25} {'-'*10} {'-'*8} {'-'*25}")
    for bot_name, hits in sorted_bots:
        last_hit = hits[-1]["timestamp"]
        print(f"  {bot_name:<25} {len(hits):>10,} {len(bot_pages[bot_name]):>8} {last_hit:>25}")

    print(f"\n{'='*60}")
    print(f"  Detected: {len(bot_hits)} bot(s) | Not seen: {len(missing_bots)} bot(s)")
    print(f"{'='*60}\n")


