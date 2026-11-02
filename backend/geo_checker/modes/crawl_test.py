"""crawl_test — AI crawler accessibility test (no logs needed).

Migrated from /geo_checker.py lines 4539-4788.
"""

import json
import re
import sys
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from ..constants import AI_BOTS, AI_CRAWLERS, PASS, WARN, FAIL, INFO, FIX
from ..io import fetch, get_soup, get_text_content
from ..output import print, emit_check, emit_fix, fix
from ..state import (
    SHOW_FIX, _scores, _page_cache, reset_state, track_score,
    get_ai_visibility_score, get_grade,
)
from ..orchestrate import run_silent


def crawl_test(url, return_data=False):
    """Test if a site is accessible to AI crawlers by simulating requests with their user agents.
    Also checks robots.txt rules and external indexes (Common Crawl).
    Useful when you don't have access to server logs.

    When return_data=True, returns a dict describing robots.txt rules, per-bot
    simulated access results, and the Common Crawl index lookup.
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if not parsed.scheme:
        url = "https://" + url
        parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    domain = parsed.netloc

    robots_bots_data = []
    waf_bots_data = []
    common_crawl_data = {"found": False, "count": 0, "samples": [], "status": None, "error": None}

    print(f"\n{'='*60}")
    print(f"  AI Crawl Accessibility Test")
    print(f"  Target: {base_url}")
    print(f"{'='*60}")

    # ── Step 1: Parse robots.txt for bot-specific rules ──
    print(f"\n--- robots.txt Rules for AI Bots ---")
    robots_url = base_url + "/robots.txt"
    robots_resp = fetch(robots_url)
    robots_text = ""
    if robots_resp and robots_resp.status_code == 200:
        robots_text = robots_resp.text
        print(f"  [{PASS}] robots.txt found")
    else:
        print(f"  [{WARN}] robots.txt not found — all bots allowed by default")

    # Simple robots.txt parser: check per-bot rules
    def check_robots_for_bot(robots_text, bot_name):
        """Returns 'allowed', 'blocked', or 'no rule' based on robots.txt."""
        if not robots_text:
            return "allowed"
        lines = robots_text.lower().splitlines()
        in_block = False
        in_wildcard = False
        bot_lower = bot_name.lower()
        bot_blocked = None
        wildcard_blocked = None

        for line in lines:
            line = line.split("#")[0].strip()
            if line.startswith("user-agent:"):
                agent = line.split(":", 1)[1].strip()
                in_block = agent == bot_lower
                in_wildcard = agent == "*"
            elif in_block and line.startswith("disallow:"):
                path = line.split(":", 1)[1].strip()
                if path == "/" or path == "/*":
                    bot_blocked = True
                elif path == "":
                    bot_blocked = False
            elif in_block and line.startswith("allow:"):
                path = line.split(":", 1)[1].strip()
                if path == "/":
                    bot_blocked = False
            elif in_wildcard and line.startswith("disallow:"):
                path = line.split(":", 1)[1].strip()
                if path == "/" or path == "/*":
                    wildcard_blocked = True
                elif path == "":
                    wildcard_blocked = False
            elif in_wildcard and line.startswith("allow:"):
                path = line.split(":", 1)[1].strip()
                if path == "/":
                    wildcard_blocked = False

        if bot_blocked is True:
            return "blocked"
        if bot_blocked is False:
            return "allowed"
        if wildcard_blocked is True:
            return "blocked"
        if wildcard_blocked is False:
            return "allowed"
        return "allowed"

    # Check robots.txt rules for each critical bot
    critical_bots_for_robots = {
        "GPTBot": "GPTBot",
        "ChatGPT-User": "ChatGPT-User",
        "ClaudeBot": "ClaudeBot",
        "PerplexityBot": "PerplexityBot",
        "Google-Extended": "Google-Extended",
        "Googlebot": "Googlebot",
        "Bingbot": "bingbot",
        "CCBot": "CCBot",
        "Anthropic": "anthropic-ai",
        "Bytespider": "Bytespider",
        "Meta-ExternalAgent": "Meta-ExternalAgent",
    }

    blocked_bots = []
    for display_name, ua_name in critical_bots_for_robots.items():
        status = check_robots_for_bot(robots_text, ua_name)
        if status == "blocked":
            print(f"  [{FAIL}] {display_name} — BLOCKED by robots.txt")
            blocked_bots.append(display_name)
        else:
            print(f"  [{PASS}] {display_name} — allowed")
        robots_bots_data.append({"bot": display_name, "ua": ua_name, "status": status})

    if blocked_bots:
        fix("The following bots are blocked by robots.txt: " + ", ".join(blocked_bots) + "\n"
            "If you want AI engines to index your content, remove or modify these rules:\n"
            "  User-agent: BotName\n"
            "  Disallow: /\n"
            "Change 'Disallow: /' to 'Allow: /' or remove the block entirely.")

    # ── Step 2: Simulate requests with AI bot user agents ──
    print(f"\n--- Simulated Bot Access Test ---")
    print(f"  Sending requests to {base_url}/ with AI bot user agents...")
    print(f"  (Checks if your server/CDN/WAF blocks bot traffic)\n")

    test_bots = {
        "GPTBot":        "Mozilla/5.0 (compatible; GPTBot/1.0; +https://openai.com/gptbot)",
        "ChatGPT-User":  "Mozilla/5.0 ChatGPT-User/1.0",
        "ClaudeBot":     "ClaudeBot/1.0",
        "Googlebot":     "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "Bingbot":       "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
        "PerplexityBot": "Mozilla/5.0 (compatible; PerplexityBot/1.0; +https://perplexity.ai/perplexitybot)",
        "CCBot":         "CCBot/2.0 (https://commoncrawl.org/faq/)",
        "Bytespider":    "Mozilla/5.0 (compatible; Bytespider; spider-feedback@bytedance.com)",
    }

    # First get a baseline with a normal browser user agent
    try:
        baseline = requests.get(base_url + "/", timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        })
        baseline_status = baseline.status_code
        baseline_len = len(baseline.content)
    except requests.RequestException:
        baseline_status = None
        baseline_len = 0

    print(f"  Baseline (browser): status={baseline_status}, size={baseline_len:,} bytes\n")

    waf_blocked = []
    for bot_name, ua_string in test_bots.items():
        bot_entry = {"bot": bot_name, "status_code": None, "size": 0, "result": "unknown", "error": None}
        try:
            resp = requests.get(base_url + "/", timeout=15, headers={
                "User-Agent": ua_string
            })
            status = resp.status_code
            size = len(resp.content)
            bot_entry["status_code"] = status
            bot_entry["size"] = size

            # Detect blocking: 403/406/429, or dramatically smaller response (likely a block page)
            if status in (403, 406, 429, 451):
                print(f"  [{FAIL}] {bot_name:<18} status={status} — BLOCKED by server/WAF")
                waf_blocked.append(bot_name)
                bot_entry["result"] = "blocked"
            elif baseline_len > 0 and size < baseline_len * 0.3:
                print(f"  [{WARN}] {bot_name:<18} status={status}, size={size:,} bytes — "
                      f"suspiciously small vs baseline ({baseline_len:,})")
                waf_blocked.append(bot_name)
                bot_entry["result"] = "suspicious"
            else:
                print(f"  [{PASS}] {bot_name:<18} status={status}, size={size:,} bytes")
                bot_entry["result"] = "allowed"
        except requests.RequestException as e:
            print(f"  [{FAIL}] {bot_name:<18} request failed: {e}")
            waf_blocked.append(bot_name)
            bot_entry["result"] = "error"
            bot_entry["error"] = str(e)
        waf_bots_data.append(bot_entry)

    if waf_blocked:
        fix("Some AI bots are being blocked by your server, CDN, or WAF.\n"
            "Check your Cloudflare/AWS WAF/Nginx rules and whitelist these user agents.\n"
            "Common causes:\n"
            "  - Cloudflare Bot Fight Mode blocking non-browser user agents\n"
            "  - Rate limiting rules that are too aggressive\n"
            "  - Security plugins (Wordfence, Sucuri) with strict bot blocking")
    else:
        print(f"\n  All tested bots can access your site successfully.")

    # ── Step 3: Check Common Crawl index ──
    print(f"\n--- Common Crawl Index Check ---")
    cc_url = f"https://index.commoncrawl.org/CC-MAIN-2025-51-index?url={domain}&output=json"
    try:
        cc_resp = requests.get(cc_url, timeout=30)
        common_crawl_data["status"] = cc_resp.status_code
        if cc_resp.status_code == 200 and cc_resp.text.strip():
            cc_lines = [l for l in cc_resp.text.strip().splitlines() if l.strip()]
            print(f"  [{PASS}] Found {len(cc_lines)} page(s) in Common Crawl index")
            common_crawl_data["found"] = True
            common_crawl_data["count"] = len(cc_lines)
            for line in cc_lines[:5]:
                try:
                    data = json.loads(line)
                    print(f"         {data.get('url', 'unknown')}")
                    common_crawl_data["samples"].append(data.get("url", ""))
                except json.JSONDecodeError:
                    pass
            if len(cc_lines) > 5:
                print(f"         ...and {len(cc_lines) - 5} more")
        elif cc_resp.status_code == 404:
            print(f"  [{WARN}] Domain not found in Common Crawl index")
            fix("Your site hasn't been crawled by Common Crawl yet.\n"
                "This is normal for newer/smaller sites. Build inbound links to increase discovery.")
        else:
            print(f"  [{INFO}] Common Crawl index returned status {cc_resp.status_code} — try again later")
    except requests.RequestException as e:
        print(f"  [{INFO}] Could not reach Common Crawl index — their servers may be slow, try again later")
        common_crawl_data["error"] = str(e)

    # ── Summary ──
    total_issues = len(blocked_bots) + len(waf_blocked)
    print(f"\n{'='*60}")
    if total_issues == 0:
        print(f"  Your site appears accessible to all major AI crawlers.")
        print(f"  robots.txt: all bots allowed | WAF/CDN: no blocks detected")
    else:
        print(f"  Issues found: {len(blocked_bots)} bot(s) blocked by robots.txt, "
              f"{len(waf_blocked)} bot(s) blocked by server/WAF")
    print(f"{'='*60}\n")

    if return_data:
        return {
            "url": base_url,
            "domain": domain,
            "robots": {
                "found": bool(robots_text),
                "bots": robots_bots_data,
                "blocked": blocked_bots,
            },
            "waf": {
                "baseline_status": baseline_status,
                "baseline_size": baseline_len,
                "bots": waf_bots_data,
                "blocked": waf_blocked,
            },
            "common_crawl": common_crawl_data,
            "total_issues": total_issues,
        }


