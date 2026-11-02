#!/usr/bin/env python3
"""
GEO Readiness Checker
Checks a website's readiness for Generative Engine Optimization (GEO).
Inspects robots.txt, llms.txt, sitemap.xml, structured data, meta tags, and more.

Usage:
    python geo_checker.py https://example.com          # Diagnose only
    python geo_checker.py https://example.com --fix     # Diagnose + show fix recommendations
"""

import argparse
import io
import json
import re
import sys
import time
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Global config
# ---------------------------------------------------------------------------
SHOW_FIX = False  # Toggled by --fix flag

AI_BOTS = [
    "GPTBot", "ChatGPT-User", "Google-Extended", "GoogleOther",
    "Anthropic", "anthropic-ai", "ClaudeBot", "Claude-Web", "CCBot",
    "PerplexityBot", "Bytespider", "Diffbot", "Applebot-Extended",
    "Cohere-ai", "Meta-ExternalAgent",
]

# AI/LLM crawler user-agent patterns for log analysis
# importance: "critical" = core AI crawlers (WARN if missing),
#             "optional" = supplementary/preview bots (INFO if missing)
AI_CRAWLERS = {
    "GPTBot":              {"pattern": r"GPTBot",              "powers": "ChatGPT training data",          "importance": "critical"},
    "ChatGPT-User":        {"pattern": r"ChatGPT-User",       "powers": "ChatGPT live browsing",          "importance": "critical"},
    "ClaudeBot":           {"pattern": r"ClaudeBot",           "powers": "Claude training data",           "importance": "critical"},
    "Anthropic":           {"pattern": r"anthropic-ai|Anthropic", "powers": "Anthropic crawling",          "importance": "optional"},
    "PerplexityBot":       {"pattern": r"PerplexityBot",       "powers": "Perplexity AI answers",          "importance": "critical"},
    "Googlebot":           {"pattern": r"Googlebot",            "powers": "Google Search → AI Overviews / SGE", "importance": "critical"},
    "GoogleOther":         {"pattern": r"GoogleOther",         "powers": "Google AI training",             "importance": "optional"},
    "Bingbot":             {"pattern": r"bingbot|Bingbot",     "powers": "Bing index → Copilot / ChatGPT", "importance": "critical"},
    "BingPreview":         {"pattern": r"BingPreview",         "powers": "Bing link preview (Teams/Outlook)", "importance": "optional"},
    "Bytespider":          {"pattern": r"Bytespider",          "powers": "ByteDance / TikTok AI",          "importance": "optional"},
    "CCBot":               {"pattern": r"CCBot",               "powers": "Common Crawl (used by many LLMs)", "importance": "optional"},
    "Diffbot":             {"pattern": r"Diffbot",             "powers": "Knowledge graph extraction",     "importance": "optional"},
    "Applebot-Extended":   {"pattern": r"Applebot-Extended",   "powers": "Apple Intelligence / Siri",      "importance": "optional"},
    "Applebot":            {"pattern": r"Applebot(?!-Extended)", "powers": "Apple search / Siri",           "importance": "optional"},
    "Cohere-ai":           {"pattern": r"[Cc]ohere-ai",        "powers": "Cohere models",                  "importance": "optional"},
    "Meta-ExternalAgent":  {"pattern": r"Meta-ExternalAgent",  "powers": "Meta AI",                        "importance": "optional"},
    "YouBot":              {"pattern": r"YouBot",              "powers": "You.com AI search",              "importance": "optional"},
    "PetalBot":            {"pattern": r"PetalBot",            "powers": "Huawei / Petal Search AI",       "importance": "optional"},
    "SemrushBot":          {"pattern": r"SemrushBot",          "powers": "SEO analytics (AI-adjacent)",    "importance": "optional"},
    "AhrefsBot":           {"pattern": r"AhrefsBot",           "powers": "SEO analytics (AI-adjacent)",    "importance": "optional"},
}

PASS = "\033[92mPASS\033[0m"
WARN = "\033[93mWARN\033[0m"
FAIL = "\033[91mFAIL\033[0m"
INFO = "\033[94mINFO\033[0m"
FIX  = "\033[96m FIX\033[0m"

# ---------------------------------------------------------------------------
# i18n  — output-level translation
# ---------------------------------------------------------------------------
LANG = "en"

# Pre-scan sys.argv so everything downstream sees the right language
if "--lang" in sys.argv:
    _idx = sys.argv.index("--lang")
    if _idx + 1 < len(sys.argv) and sys.argv[_idx + 1] in ("en", "zh"):
        LANG = sys.argv[_idx + 1]

# _ZH maps English substrings → Chinese.  Populated at end of file before main().
# Entries are tried longest-first to avoid partial matches.
_ZH = {}
_ZH_SORTED = []  # [(en, zh)] sorted by len(en) descending; built once

def _tr(text):
    """Translate English substrings in *text* to Chinese using _ZH table."""
    global _ZH_SORTED
    if LANG == "en" or not _ZH:
        return text
    if not _ZH_SORTED:
        _ZH_SORTED = sorted(_ZH.items(), key=lambda kv: len(kv[0]), reverse=True)
    for en, zh in _ZH_SORTED:
        if en in text:
            text = text.replace(en, zh)
    return text


def _display_width(s):
    """Return the number of terminal columns *s* occupies.
    CJK characters are double-width; ANSI escapes are zero-width."""
    import unicodedata
    s = re.sub(r'\033\[[0-9;]*m', '', s)  # strip ANSI
    w = 0
    for ch in s:
        if unicodedata.east_asian_width(ch) in ('W', 'F'):
            w += 2
        else:
            w += 1
    return w


def _pad(s, width):
    """Left-align *s* in a field of *width* terminal columns.
    Translates *s* first so padding accounts for CJK display width."""
    s = _tr(s)
    return s + ' ' * max(0, width - _display_width(s))

# Module-level print override — only translates when LANG != "en"
_builtin_print = print  # keep a reference to the real print

def print(*args, **kwargs):            # noqa: A001 — intentional shadow
    if LANG != "en" and args:
        args = tuple(_tr(str(a)) if isinstance(a, str) else a for a in args)
    _builtin_print(*args, **kwargs)

_page_cache = {}

# ---------------------------------------------------------------------------
# i18n-ready check emitter — see geo_checker/__main__.py for full rationale.
# ---------------------------------------------------------------------------
import os as _os

_EMIT_STRUCTURED = _os.environ.get("GEO_EMIT_STRUCTURED") == "1"
_KEY_MARKER_START = "\x01GK\x01"
_KEY_MARKER_END = "\x01GE\x01"


def emit_check(status_tag, key, message, params=None):
    """Print a check result line and (optionally) embed i18n metadata."""
    line = f"  [{status_tag}] {message}"
    if _EMIT_STRUCTURED and key:
        meta = json.dumps({"k": key, "p": params or {}}, ensure_ascii=False)
        line += f"{_KEY_MARKER_START}{meta}{_KEY_MARKER_END}"
    print(line)

# ---------------------------------------------------------------------------
# Score tracking
# ---------------------------------------------------------------------------
_scores = {}  # category -> {"earned": float, "max": float}


def track_score(category, earned, max_points):
    """Record earned/max points for a check category."""
    if category not in _scores:
        _scores[category] = {"earned": 0.0, "max": 0.0}
    _scores[category]["earned"] += earned
    _scores[category]["max"] += max_points


def get_ai_visibility_score():
    """Calculate overall AI Visibility Score (0-100)."""
    total_earned = sum(v["earned"] for v in _scores.values())
    total_max = sum(v["max"] for v in _scores.values())
    if total_max == 0:
        return 0
    return round((total_earned / total_max) * 100)


def get_grade(score):
    """Convert 0-100 score to letter grade."""
    if score >= 90:
        return "A+"
    elif score >= 80:
        return "A"
    elif score >= 70:
        return "B"
    elif score >= 60:
        return "C"
    elif score >= 50:
        return "D"
    else:
        return "F"


def reset_state():
    """Reset global state for a fresh run."""
    global _scores, _page_cache
    _scores = {}
    _page_cache = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def fix(message):
    """Print a fix recommendation if --fix flag is enabled."""
    if SHOW_FIX:
        for line in message.strip().splitlines():
            print(f"  [{FIX}] {line}")


def fetch(url, timeout=15, allow_redirects=True):
    if url in _page_cache:
        return _page_cache[url]
    try:
        resp = requests.get(url, timeout=timeout, allow_redirects=allow_redirects, headers={
            "User-Agent": "GEO-Readiness-Checker/1.0"
        })
        _page_cache[url] = resp
        return resp
    except requests.RequestException:
        return None


def get_soup(base_url):
    resp = fetch(base_url)
    if not resp or resp.status_code != 200:
        return None, None
    return resp, BeautifulSoup(resp.text, "html.parser")


def get_text_content(soup):
    clone = BeautifulSoup(str(soup), "html.parser")
    for tag in clone(["script", "style", "noscript"]):
        tag.decompose()
    return clone.get_text(separator=" ", strip=True)


# ---------------------------------------------------------------------------
# 1. HTTPS
# ---------------------------------------------------------------------------
def check_https(url):
    print("\n--- HTTPS ---")
    parsed = urlparse(url)
    if parsed.scheme == "https":
        print(f"  [{PASS}] Site uses HTTPS")
        track_score("HTTPS", 5, 5)
        return True
    else:
        print(f"  [{FAIL}] Site does not use HTTPS — AI engines prefer secure sites")
        fix("Install an SSL/TLS certificate (free via Let's Encrypt) and redirect all HTTP traffic to HTTPS.\nExample nginx: return 301 https://$host$request_uri;")
        track_score("HTTPS", 0, 5)
        return False


# ---------------------------------------------------------------------------
# 2. robots.txt
# ---------------------------------------------------------------------------
def check_robots_txt(base_url):
    print("\n--- robots.txt ---")
    url = urljoin(base_url, "/robots.txt")
    resp = fetch(url)

    if resp is None or resp.status_code != 200:
        print(f"  [{FAIL}] robots.txt not found at {url}")
        fix("Create a robots.txt file at the root of your site.\nMinimal example:\n  User-agent: *\n  Allow: /\n  Sitemap: https://yoursite.com/sitemap.xml")
        track_score("robots.txt", 0, 8)
        return

    print(f"  [{PASS}] robots.txt found ({len(resp.text)} bytes)")
    track_score("robots.txt", 3, 3)
    lines = resp.text.splitlines()

    has_sitemap_ref = any(line.strip().lower().startswith("sitemap:") for line in lines)
    if has_sitemap_ref:
        print(f"  [{PASS}] robots.txt references a sitemap")
        track_score("robots.txt", 2, 2)
    else:
        print(f"  [{WARN}] robots.txt does not reference a sitemap")
        fix("Add a Sitemap directive to your robots.txt:\n  Sitemap: https://yoursite.com/sitemap.xml")
        track_score("robots.txt", 0, 2)

    blocked, allowed, not_mentioned = [], [], []
    for bot in AI_BOTS:
        bot_lower = bot.lower()
        bot_mentioned = False
        bot_blocked = False
        for i, line in enumerate(lines):
            stripped = line.strip().lower()
            if stripped.startswith("user-agent:") and bot_lower in stripped:
                bot_mentioned = True
                for j in range(i + 1, len(lines)):
                    next_line = lines[j].strip().lower()
                    if next_line.startswith("user-agent:"):
                        break
                    if next_line.startswith("disallow: /"):
                        bot_blocked = True
                        break
        if bot_mentioned and bot_blocked:
            blocked.append(bot)
        elif bot_mentioned:
            allowed.append(bot)
        else:
            not_mentioned.append(bot)

    wildcard_blocks_all = False
    for i, line in enumerate(lines):
        stripped = line.strip().lower()
        if stripped == "user-agent: *":
            for j in range(i + 1, len(lines)):
                next_line = lines[j].strip().lower()
                if next_line.startswith("user-agent:"):
                    break
                if next_line == "disallow: /":
                    wildcard_blocks_all = True
                    break

    if wildcard_blocks_all:
        print(f"  [{WARN}] Wildcard user-agent blocks all crawlers (Disallow: /)")
        fix("Change 'Disallow: /' under 'User-agent: *' to 'Allow: /' if you want AI crawlers to index your site.\nYou can selectively block specific bots while allowing others.")
    if blocked:
        print(f"  [{WARN}] AI bots explicitly BLOCKED: {', '.join(blocked)}")
        fix(f"To allow these AI bots, remove or modify their Disallow directives in robots.txt.\nExample to allow GPTBot:\n  User-agent: GPTBot\n  Allow: /")
    if allowed:
        print(f"  [{PASS}] AI bots with directives (not blocked): {', '.join(allowed)}")
    if not_mentioned:
        print(f"  [{INFO}] AI bots not mentioned (inherit wildcard rules): {', '.join(not_mentioned)}")

    # Score: 3 pts for AI bot access
    total_bots = len(AI_BOTS)
    accessible = total_bots - len(blocked) - (total_bots if wildcard_blocks_all and not allowed else 0)
    bot_ratio = max(accessible, 0) / total_bots if total_bots > 0 else 1
    track_score("robots.txt", round(bot_ratio * 3, 1), 3)

    # ai.txt / .well-known/ai.txt — emerging standard for strategic AI policy
    ai_txt_found = False
    for ai_path in ["/ai.txt", "/.well-known/ai.txt"]:
        ai_resp = fetch(urljoin(base_url, ai_path))
        if ai_resp and ai_resp.status_code == 200 and len(ai_resp.text.strip()) > 0:
            ai_txt_found = True
            print(f"  [{PASS}] {ai_path} found — strategic AI crawler policy declared")
            ai_text = ai_resp.text.lower()
            has_allow = "allow" in ai_text
            has_disallow = "disallow" in ai_text
            if has_allow and has_disallow:
                print(f"         Contains both allow and disallow directives (balanced policy)")
            elif has_allow:
                print(f"         Allow-focused policy (crawl-friendly)")
            elif has_disallow:
                print(f"         Disallow-focused policy (training opt-out)")
            track_score("robots.txt", 2, 2)
            break
    if not ai_txt_found:
        print(f"  [{INFO}] No ai.txt or .well-known/ai.txt found — emerging standard for AI-specific policies")
        fix("Consider an ai.txt file at your site root (spec: spawning.ai/ai-txt) to declare\n"
            "a strategic policy separate from robots.txt. Example balancing access vs. training:\n"
            "  # Allow search indexing for AI answers\n"
            "  User-Agent: *\n"
            "  Allow: /\n"
            "  # Opt out of training\n"
            "  User-Agent: GPTBot\n"
            "  Disallow: /private/\n"
            "This communicates a deliberate allow-for-citation / opt-out-of-training stance.")
        track_score("robots.txt", 0, 2)


# ---------------------------------------------------------------------------
# 3. llms.txt
# ---------------------------------------------------------------------------
def check_llms_txt(base_url):
    print("\n--- llms.txt ---")
    llms_score = 0

    for filename in ["llms.txt", "llms-full.txt", ".well-known/llms.txt"]:
        url = urljoin(base_url, f"/{filename}")
        resp = fetch(url)
        if resp and resp.status_code == 200 and len(resp.text.strip()) > 0:
            text = resp.text.strip()
            lines = text.splitlines()
            print(f"  [{PASS}] {filename} found ({len(lines)} lines, {len(text)} bytes)")

            has_title = any(line.strip().startswith("# ") for line in lines)
            has_description = len([l for l in lines if l.strip() and not l.strip().startswith("#") and not l.strip().startswith(">") and not l.strip().startswith("-")]) > 0
            has_sections = any(line.strip().startswith("## ") for line in lines)
            has_links = any(
                "](http" in line or "](/" in line
                or "http://" in line or "https://" in line
                for line in lines
            )
            has_blockquotes = any(line.strip().startswith("> ") for line in lines)

            llms_score += 2  # file found

            if has_title:
                title_line = next(l for l in lines if l.strip().startswith("# "))
                print(f"  [{PASS}] Title: {title_line.strip()}")
                llms_score += 0.5
            else:
                print(f"  [{WARN}] No markdown title (# heading) — recommended by llms.txt spec")
                fix(f"Add a title as the first line of {filename}:\n  # Your Site Name")

            if has_description:
                print(f"  [{PASS}] Contains descriptive text")
            else:
                print(f"  [{WARN}] No descriptive text found — should explain what the site/org does")
                fix(f"Add a paragraph below the title explaining what your site/org does:\n  # Your Site\n  A brief description of your site and what it offers.")

            if has_sections:
                section_count = sum(1 for l in lines if l.strip().startswith("## "))
                print(f"  [{PASS}] {section_count} section(s) found (## headings)")
                llms_score += 0.5
            else:
                print(f"  [{WARN}] No sections (## headings) — consider organizing content into sections")
                fix("Organize your llms.txt with sections like:\n  ## Documentation\n  ## API Reference\n  ## Blog")

            if has_links:
                link_count = sum(
                    1 for l in lines
                    if "](http" in l or "](/" in l
                    or "http://" in l or "https://" in l
                )
                print(f"  [{PASS}] {link_count} link(s) to resources found")
                llms_score += 0.5
            else:
                print(f"  [{WARN}] No links found — llms.txt should link to key resources")
                fix("Add markdown links to your key pages:\n  - [Documentation](https://yoursite.com/docs)\n  - [API Reference](https://yoursite.com/api)")

            if has_blockquotes:
                print(f"  [{PASS}] Blockquote descriptions (>) present")

            if len(text) < 100:
                print(f"  [{WARN}] File is very short ({len(text)} bytes) — may be a placeholder")
                fix("Expand the file with meaningful content about your site, its purpose, key pages, and resources.")
        else:
            print(f"  [{FAIL}] {filename} not found")
            if filename == "llms.txt":
                fix("Create an llms.txt file at your site root. Example structure:\n  # Your Site Name\n  A brief description of your site.\n  \n  ## Documentation\n  > Overview of your docs\n  - [Getting Started](https://yoursite.com/docs/start)\n  \n  ## API\n  > API reference\n  - [API Docs](https://yoursite.com/api)")
            elif filename == "llms-full.txt":
                fix("Create llms-full.txt with expanded content — a more detailed version of llms.txt\nwith full descriptions, complete resource listings, and deeper context for AI models.")

    track_score("llms.txt", min(llms_score, 5), 5)


# ---------------------------------------------------------------------------
# 4. .well-known Discovery
# ---------------------------------------------------------------------------
def check_well_known(base_url):
    print("\n--- .well-known Discovery ---")

    well_known_files = {
        ".well-known/ai-plugin.json": "OpenAI plugin manifest (ChatGPT plugins)",
        ".well-known/openai.yaml": "OpenAI API spec for plugins",
        ".well-known/security.txt": "Security contact info (trust signal for AI engines)",
        ".well-known/gpc.json": "Global Privacy Control signal",
    }

    found_any = False
    wk_found = 0
    for path, description in well_known_files.items():
        url = urljoin(base_url, f"/{path}")
        resp = fetch(url)
        if not (resp and resp.status_code == 200 and len(resp.text.strip()) > 0):
            print(f"  [{INFO}] {path} not found — {description}")
            continue

        ctype = (resp.headers.get("Content-Type") or "").lower()
        body = resp.text.lstrip()
        looks_html = ctype.startswith("text/html") or body[:15].lower().startswith(("<!doctype", "<html"))

        if path.endswith(".json"):
            if looks_html:
                print(f"  [{INFO}] {path} not found — {description} (server returned HTML fallback)")
                continue
            try:
                data = json.loads(resp.text)
            except json.JSONDecodeError:
                print(f"  [{WARN}] {path} exists but contains invalid JSON")
                fix(f"Validate and fix the JSON in {path} — use a JSON linter to check for syntax errors.")
                found_any = True
                wk_found += 1
                continue
            found_any = True
            wk_found += 1
            print(f"  [{PASS}] {path} found — {description}")
            if path.endswith("ai-plugin.json"):
                name = data.get("name_for_human", data.get("name", "unknown"))
                print(f"         Plugin name: {name}")
        elif path.endswith(".yaml") or path.endswith(".txt"):
            if looks_html:
                print(f"  [{INFO}] {path} not found — {description} (server returned HTML fallback)")
                continue
            found_any = True
            wk_found += 1
            print(f"  [{PASS}] {path} found — {description}")
        else:
            found_any = True
            wk_found += 1
            print(f"  [{PASS}] {path} found — {description}")

    if not found_any:
        print(f"  [{INFO}] No .well-known AI discovery files found")
        fix("Consider adding .well-known/security.txt (RFC 9116) as a trust signal:\n  Contact: mailto:security@yoursite.com\n  Preferred-Languages: en\n  Canonical: https://yoursite.com/.well-known/security.txt")

    track_score(".well-known", min(wk_found, 3), 3)


# ---------------------------------------------------------------------------
# 5. sitemap.xml
# ---------------------------------------------------------------------------
def check_sitemap(base_url):
    print("\n--- sitemap.xml ---")

    sitemap_paths = ["/sitemap.xml", "/sitemap_index.xml", "/sitemap/sitemap.xml"]
    found = False
    sitemap_urls = []

    for path in sitemap_paths:
        url = urljoin(base_url, path)
        resp = fetch(url)
        if resp and resp.status_code == 200 and ("<?xml" in resp.text or "<urlset" in resp.text or "<sitemapindex" in resp.text):
            found = True
            url_count = resp.text.count("<loc>")
            print(f"  [{PASS}] Sitemap found at {path} ({url_count} <loc> entries)")
            track_score("Sitemap", 4, 4)

            has_lastmod = "<lastmod>" in resp.text
            if has_lastmod:
                print(f"  [{PASS}] Sitemap includes <lastmod> timestamps")
                track_score("Sitemap", 3, 3)
            else:
                print(f"  [{WARN}] Sitemap missing <lastmod> timestamps — helps AI engines know content freshness")
                fix("Add <lastmod> to each <url> entry in your sitemap:\n  <url>\n    <loc>https://yoursite.com/page</loc>\n    <lastmod>2025-01-15</lastmod>\n  </url>")
                track_score("Sitemap", 1, 3)

            try:
                root = ElementTree.fromstring(resp.text)
                ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
                for loc in root.findall(".//sm:loc", ns):
                    if loc.text:
                        sitemap_urls.append(loc.text.strip())
                if not sitemap_urls:
                    for loc in root.iter():
                        if loc.tag.endswith("loc") and loc.text:
                            sitemap_urls.append(loc.text.strip())
            except ElementTree.ParseError:
                pass
            break

    if not found:
        print(f"  [{FAIL}] No sitemap.xml found")
        fix("Create a sitemap.xml at your site root. Example:\n  <?xml version=\"1.0\" encoding=\"UTF-8\"?>\n  <urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">\n    <url>\n      <loc>https://yoursite.com/</loc>\n      <lastmod>2025-01-15</lastmod>\n    </url>\n  </urlset>\nMost CMS platforms (WordPress, Next.js, etc.) can auto-generate sitemaps.")
        track_score("Sitemap", 0, 7)

    return sitemap_urls


# ---------------------------------------------------------------------------
# 5b. Search Engine & AI Platform Registration
# ---------------------------------------------------------------------------
def check_search_engine_registration(base_url):
    """Check for signs that the site is registered with search engines and AI platforms."""
    print("\n--- Search Engine & AI Platform Registration ---")
    resp, soup = get_soup(base_url)
    if not soup:
        print(f"  [{FAIL}] Could not fetch homepage")
        track_score("Platform Registration", 0, 7)
        return

    # Google Search Console verification
    google_verify = soup.find("meta", attrs={"name": "google-site-verification"})
    if google_verify and google_verify.get("content"):
        print(f"  [{PASS}] Google Search Console verification tag found")
    else:
        # Check for verification file
        gsc_resp = fetch(urljoin(base_url, "/google*.html"), timeout=5)
        # Can't glob on server, so just note the absence
        print(f"  [{WARN}] No Google Search Console verification tag found")
        fix("Register your site with Google Search Console (https://search.google.com/search-console):\n  1. Add your property (URL prefix or domain)\n  2. Verify ownership via meta tag, DNS, or HTML file\n  3. Submit your sitemap.xml under Sitemaps\n  4. Monitor indexing status and fix any crawl errors\nThis is critical — Google's AI Overviews and SGE pull from the Google index.")

    # Bing Webmaster Tools verification
    bing_verify = soup.find("meta", attrs={"name": "msvalidate.01"})
    if bing_verify and bing_verify.get("content"):
        print(f"  [{PASS}] Bing Webmaster Tools verification tag found")
    else:
        print(f"  [{WARN}] No Bing Webmaster Tools verification tag found")
        fix("Register your site with Bing Webmaster Tools (https://www.bing.com/webmasters):\n  1. Add your site and verify ownership\n  2. Submit your sitemap.xml\n  3. This is essential — Bing's index powers Microsoft Copilot, ChatGPT (via Bing search),\n     and other AI assistants that use Bing as their search backend.")

    # Yandex verification (feeds into some AI systems)
    yandex_verify = soup.find("meta", attrs={"name": "yandex-verification"})
    if yandex_verify and yandex_verify.get("content"):
        print(f"  [{PASS}] Yandex Webmaster verification tag found")
    else:
        print(f"  [{INFO}] No Yandex Webmaster verification tag — relevant if targeting international AI platforms")

    # IndexNow support — check for key file
    indexnow_found = False
    # Check for IndexNow key in common locations
    for key_path in ["/.well-known/indexnow", "/indexnow"]:
        inow_url = urljoin(base_url, key_path)
        inow_resp = fetch(inow_url, timeout=5)
        if inow_resp and inow_resp.status_code == 200 and len(inow_resp.text.strip()) > 0:
            indexnow_found = True
            print(f"  [{PASS}] IndexNow endpoint found at {key_path} — enables instant index notifications")
            break

    # Also check for IndexNow meta tag or key file pattern
    if not indexnow_found:
        # Some sites host the key as a text file at root
        indexnow_meta = soup.find("meta", attrs={"name": "indexnow"})
        if indexnow_meta:
            indexnow_found = True
            print(f"  [{PASS}] IndexNow meta tag found")

    if not indexnow_found:
        print(f"  [{INFO}] No IndexNow integration detected")
        fix("Set up IndexNow for instant indexing by Bing, Yandex, and others:\n  1. Generate an API key at https://www.indexnow.org/\n  2. Host the key file at your site root: https://yoursite.com/{key}.txt\n  3. Notify search engines when content changes:\n     POST https://api.indexnow.org/indexnow\n     {\"host\": \"yoursite.com\", \"key\": \"your-key\", \"urlList\": [\"https://yoursite.com/updated-page\"]}\n  4. Many CMS plugins (WordPress, etc.) support IndexNow automatically.")

    # Check for Pinterest verification (some AI visual search)
    pinterest_verify = soup.find("meta", attrs={"name": "p:domain_verify"})
    if pinterest_verify:
        print(f"  [{PASS}] Pinterest domain verification found")

    # Summary / platform checklist
    print()
    platforms = {
        "Google Search Console": bool(google_verify and google_verify.get("content")),
        "Bing Webmaster Tools": bool(bing_verify and bing_verify.get("content")),
        "IndexNow": indexnow_found,
    }
    registered = [k for k, v in platforms.items() if v]
    not_registered = [k for k, v in platforms.items() if not v]

    if registered:
        print(f"  [{PASS}] Registered: {', '.join(registered)}")
    if not_registered:
        print(f"  [{WARN}] Not detected: {', '.join(not_registered)}")

        fix("Having files like sitemap.xml and robots.txt is not enough on its own.\nYou must also register and submit them to each platform:\n  \n  Google Search Console → Submit sitemap → Powers Google AI Overviews / SGE\n  Bing Webmaster Tools  → Submit sitemap → Powers Copilot, ChatGPT (Bing backend)\n  IndexNow              → Auto-notify   → Instant indexing for Bing, Yandex, Naver\n  \nWithout registration, search engines may find your sitemap eventually via crawling,\nbut submission ensures faster, more reliable indexing.")

    reg_score = 0
    if platforms.get("Google Search Console"):
        reg_score += 3
    if platforms.get("Bing Webmaster Tools"):
        reg_score += 3
    if platforms.get("IndexNow"):
        reg_score += 1
    track_score("Platform Registration", reg_score, 7)


# ---------------------------------------------------------------------------
# 6. Structured Data
# ---------------------------------------------------------------------------
def check_structured_data(base_url):
    print("\n--- Structured Data ---")
    resp, soup = get_soup(base_url)
    if not soup:
        print(f"  [{FAIL}] Could not fetch homepage")
        return

    # Granular types that give AI engines the most extractable facts
    GRANULAR_TYPES = {
        "HowTo": "step-by-step instructions",
        "Recipe": "cooking/recipe data",
        "FAQPage": "Q&A pairs",
        "QAPage": "single Q&A",
        "Product": "product details",
        "Review": "individual review",
        "AggregateRating": "aggregate ratings",
        "Event": "event details",
        "Course": "course details",
        "JobPosting": "job listing",
        "SoftwareApplication": "software metadata",
        "Dataset": "dataset metadata",
        "Article": "article metadata",
        "NewsArticle": "news article",
        "BlogPosting": "blog post",
        "VideoObject": "video metadata",
        "LocalBusiness": "local business",
        "Organization": "organization",
        "BreadcrumbList": "site hierarchy",
    }
    GENERIC_TYPES = {"Thing", "WebPage", "WebSite", "CreativeWork"}

    def _collect_types(obj, collected):
        if isinstance(obj, dict):
            t = obj.get("@type")
            if isinstance(t, list):
                for x in t:
                    if isinstance(x, str):
                        collected.append((x, obj))
            elif isinstance(t, str):
                collected.append((t, obj))
            graph = obj.get("@graph", [])
            if isinstance(graph, list):
                for item in graph:
                    _collect_types(item, collected)

    json_ld_scripts = soup.find_all("script", type="application/ld+json")
    if json_ld_scripts:
        print(f"  [{PASS}] Found {len(json_ld_scripts)} JSON-LD block(s)")
        track_score("Structured Data", 3, 3)
        parsed_types = 0
        all_collected = []
        for i, script in enumerate(json_ld_scripts):
            try:
                data = json.loads(script.string)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    _collect_types(item, all_collected)
                type_names = sorted({name for name, _ in all_collected})
                if i == 0:
                    pass  # brief header output below
                if isinstance(data, dict):
                    print(f"         Block {i+1}: @type = {data.get('@type', 'unknown')}")
                elif isinstance(data, list):
                    types = [item.get("@type", "unknown") for item in data if isinstance(item, dict)]
                    print(f"         Block {i+1}: @types = {', '.join(str(t) for t in types)}")
                parsed_types += len(items)
            except (json.JSONDecodeError, TypeError):
                print(f"         Block {i+1}: present but could not parse")

        present_granular = {name for name, _ in all_collected if name in GRANULAR_TYPES}
        present_generic = {name for name, _ in all_collected if name in GENERIC_TYPES}
        if present_granular:
            labels = ", ".join(f"{n} ({GRANULAR_TYPES[n]})" for n in sorted(present_granular))
            print(f"  [{PASS}] Granular schema types present: {labels}")

            # Extra credit for Product with reviews
            product_has_reviews = False
            for name, obj in all_collected:
                if name == "Product":
                    if obj.get("review") or obj.get("aggregateRating") or obj.get("reviews"):
                        product_has_reviews = True
                        break
            if "Product" in present_granular:
                if product_has_reviews:
                    print(f"  [{PASS}] Product schema includes reviews/ratings — strong AI signal")
                else:
                    print(f"  [{WARN}] Product schema present but no review/aggregateRating field")
                    fix("Add review and aggregateRating to your Product schema:\n"
                        "  \"aggregateRating\": {\"@type\": \"AggregateRating\", \"ratingValue\": \"4.6\", \"reviewCount\": \"128\"},\n"
                        "  \"review\": [{\"@type\": \"Review\", \"author\": ..., \"reviewRating\": ...}]")

            granular_score = min(len(present_granular), 4)
            track_score("Structured Data", granular_score, 4)
        elif present_generic:
            print(f"  [{WARN}] Only generic schema types found ({', '.join(sorted(present_generic))}) — add granular types for richer AI extraction")
            fix("Upgrade from generic WebPage/CreativeWork to specific types:\n"
                "  • How-to content → HowTo with step list\n"
                "  • Q&A pages     → FAQPage with Question/Answer pairs\n"
                "  • Products      → Product with offers + aggregateRating\n"
                "  • Recipes       → Recipe with ingredients and instructions\n"
                "  • Articles      → NewsArticle or BlogPosting\n"
                "Granular types give AI engines far more extractable facts than WebPage.")
            track_score("Structured Data", 1, 4)
        else:
            print(f"  [{INFO}] Non-standard @types detected — consider using schema.org granular types")
            track_score("Structured Data", 1, 4)
    else:
        print(f"  [{WARN}] No JSON-LD structured data found — helps AI engines understand your content")
        track_score("Structured Data", 0, 7)
        fix("Add JSON-LD structured data to your <head>. Example for an Organization:\n  <script type=\"application/ld+json\">\n  {\n    \"@context\": \"https://schema.org\",\n    \"@type\": \"Organization\",\n    \"name\": \"Your Company\",\n    \"url\": \"https://yoursite.com\",\n    \"description\": \"What your company does\"\n  }\n  </script>\nUse Google's Rich Results Test to validate: https://search.google.com/test/rich-results")

    has_schema_ref = 'schema.org' in resp.text
    if has_schema_ref and not json_ld_scripts:
        print(f"  [{INFO}] schema.org references found (possibly microdata or RDFa)")


# ---------------------------------------------------------------------------
# 7. Meta Tags
# ---------------------------------------------------------------------------
def check_meta_tags(base_url):
    print("\n--- Meta Tags ---")
    resp, soup = get_soup(base_url)
    if not soup:
        print(f"  [{FAIL}] Could not fetch homepage")
        track_score("Meta Tags", 0, 7)
        return

    meta_score = 0
    title = soup.find("title")
    if title and title.string and title.string.strip():
        print(f"  [{PASS}] <title> found: \"{title.string.strip()[:80]}\"")
        meta_score += 1.5
    else:
        print(f"  [{FAIL}] Missing <title> tag")
        fix("Add a <title> tag in your <head>:\n  <title>Your Page Title — Your Brand</title>\nKeep it under 60 characters and include your primary keyword.")

    desc = soup.find("meta", attrs={"name": "description"})
    if desc and desc.get("content", "").strip():
        content = desc["content"].strip()
        print(f"  [{PASS}] Meta description found ({len(content)} chars)")
        meta_score += 1.5
        if len(content) < 50:
            print(f"  [{WARN}] Meta description is very short — aim for 120-160 characters")
            fix("Expand your meta description to 120-160 characters. Include a clear value proposition and primary keywords.")
    else:
        print(f"  [{FAIL}] Missing meta description")
        fix("Add a meta description in your <head>:\n  <meta name=\"description\" content=\"A 120-160 character summary of your page content, including key topics and value proposition.\">\nThis is often what AI engines use when summarizing your site.")

    canonical = soup.find("link", rel="canonical")
    if canonical and canonical.get("href"):
        print(f"  [{PASS}] Canonical URL set: {canonical['href']}")
        meta_score += 1
    else:
        print(f"  [{WARN}] No canonical URL — can cause duplicate content issues for AI engines")
        fix("Add a canonical link in your <head>:\n  <link rel=\"canonical\" href=\"https://yoursite.com/current-page\" />\nThis tells AI engines which version of a page is the authoritative one.")

    required_og = ["og:title", "og:description", "og:image", "og:url", "og:type"]
    present_og = {
        tag.get("property"): (tag.get("content") or "").strip()
        for tag in soup.find_all("meta", property=re.compile(r"^og:"))
        if tag.get("property")
    }
    found_og = [name for name in required_og if present_og.get(name)]
    missing_og = [name for name in required_og if not present_og.get(name)]
    if found_og:
        print(f"  [{PASS}] Open Graph tags present: {', '.join(found_og)}")
    if missing_og:
        print(f"  [{WARN}] Missing Open Graph tags: {', '.join(missing_og)} — shown by AI engines and link previews")
        fix("Add the missing Open Graph tags in your <head>:\n  <meta property=\"og:title\" content=\"Page Title\" />\n  <meta property=\"og:description\" content=\"Page description\" />\n  <meta property=\"og:type\" content=\"website\" />\n  <meta property=\"og:url\" content=\"https://yoursite.com/page\" />\n  <meta property=\"og:image\" content=\"https://yoursite.com/image.jpg\" />\nog:image is what makes your logo/thumbnail appear when links are shared.")
    meta_score += (len(found_og) / len(required_og))

    required_tw = ["twitter:card", "twitter:title", "twitter:description", "twitter:image"]
    present_tw = {}
    for tag in soup.find_all("meta"):
        name = tag.get("name") or tag.get("property")
        if name and name.startswith("twitter:"):
            present_tw[name] = (tag.get("content") or "").strip()
    found_tw = [name for name in required_tw if present_tw.get(name)]
    missing_tw = [name for name in required_tw if not present_tw.get(name)]
    if found_tw:
        print(f"  [{PASS}] Twitter Card tags present: {', '.join(found_tw)}")
    if missing_tw:
        print(f"  [{INFO}] Missing Twitter Card tags: {', '.join(missing_tw)} — improves X/Twitter link previews")
        fix("Add Twitter Card meta tags in your <head>:\n  <meta name=\"twitter:card\" content=\"summary_large_image\" />\n  <meta name=\"twitter:title\" content=\"Page Title\" />\n  <meta name=\"twitter:description\" content=\"Page description\" />\n  <meta name=\"twitter:image\" content=\"https://yoursite.com/image.jpg\" />")

    html_tag = soup.find("html")
    if html_tag and html_tag.get("lang"):
        print(f"  [{PASS}] Language declared: {html_tag['lang']}")
        meta_score += 1
    else:
        print(f"  [{WARN}] No lang attribute on <html> — helps AI engines understand content language")
        fix("Add a lang attribute to your <html> tag:\n  <html lang=\"en\">")

    hreflangs = soup.find_all("link", rel="alternate", hreflang=True)
    if hreflangs:
        langs = [tag.get("hreflang") for tag in hreflangs]
        print(f"  [{PASS}] Hreflang tags found for: {', '.join(langs)}")
        meta_score += 1
    else:
        print(f"  [{INFO}] No hreflang tags — add these if your site supports multiple languages")
        fix("If your site is multilingual, add hreflang tags:\n  <link rel=\"alternate\" hreflang=\"en\" href=\"https://yoursite.com/en/page\" />\n  <link rel=\"alternate\" hreflang=\"es\" href=\"https://yoursite.com/es/page\" />\n  <link rel=\"alternate\" hreflang=\"x-default\" href=\"https://yoursite.com/page\" />")

    track_score("Meta Tags", meta_score, 7)


# ---------------------------------------------------------------------------
# 8. Content Accessibility
# ---------------------------------------------------------------------------
def check_content_accessibility(base_url):
    print("\n--- Content Accessibility ---")
    resp, soup = get_soup(base_url)
    if not soup:
        print(f"  [{FAIL}] Could not fetch homepage")
        track_score("Content Accessibility", 0, 6)
        return

    ca_score = 0
    text = get_text_content(soup)
    word_count = len(text.split())

    if word_count > 200:
        print(f"  [{PASS}] Homepage has {word_count} words in initial HTML")
        ca_score += 2
    elif word_count > 50:
        print(f"  [{WARN}] Homepage has only {word_count} words in initial HTML — may rely too heavily on JavaScript rendering")
        fix("Ensure key content is rendered server-side (SSR/SSG) so AI crawlers can read it.\nIf using React/Vue/Angular, switch to Next.js/Nuxt.js/Angular Universal for server-side rendering.")
        ca_score += 1
    else:
        print(f"  [{FAIL}] Homepage has only {word_count} words — likely JS-rendered, invisible to most AI crawlers")
        fix("Your page content is likely rendered client-side via JavaScript. AI crawlers cannot execute JS.\nSolutions:\n  1. Use server-side rendering (SSR) — Next.js, Nuxt.js, etc.\n  2. Use static site generation (SSG) — pre-render pages at build time.\n  3. Add a pre-rendering service (e.g., Prerender.io) to serve static HTML to bots.")

    html_size = len(resp.text)
    text_size = len(text.encode("utf-8"))
    if html_size > 0:
        ratio = (text_size / html_size) * 100
        if ratio >= 15:
            print(f"  [{PASS}] Content-to-HTML ratio: {ratio:.1f}% (good)")
            ca_score += 2
        elif ratio >= 5:
            print(f"  [{WARN}] Content-to-HTML ratio: {ratio:.1f}% — low ratio means lots of boilerplate vs. real content")
            ca_score += 1
            fix("Reduce HTML bloat: minimize inline CSS/JS, remove unused markup, and move scripts to external files.\nEnsure the page body contains substantive, unique content — not just navigation and footers.")
        else:
            print(f"  [{FAIL}] Content-to-HTML ratio: {ratio:.1f}% — very low, mostly boilerplate/code")
            fix("Extremely low content ratio. Likely causes:\n  1. Heavy inline CSS/JS frameworks — externalize them.\n  2. Client-side rendering — switch to SSR/SSG.\n  3. Content hidden in JavaScript state — ensure HTML contains readable text.")

    headings = soup.find_all(re.compile(r"^h[1-6]$"))
    if headings:
        h_tags = [h.name for h in headings]
        h_summary = {tag: h_tags.count(tag) for tag in sorted(set(h_tags))}
        summary_str = ", ".join(f"{k}: {v}" for k, v in h_summary.items())
        print(f"  [{PASS}] Heading structure found ({summary_str})")
        ca_score += 2
        if headings[0].name != "h1":
            print(f"  [{WARN}] First heading is <{headings[0].name}>, not <h1> — clear hierarchy helps AI engines")
            fix("Ensure the first heading on the page is an <h1> tag containing the primary topic.\nUse a logical hierarchy: h1 > h2 > h3 (don't skip levels).")
    else:
        print(f"  [{WARN}] No heading tags found — structured headings help AI engines parse content")
        fix("Add heading tags to structure your content:\n  <h1>Main Page Topic</h1>\n  <h2>Subtopic</h2>\n  <h3>Detail</h3>\nHeadings help AI engines understand content hierarchy and extract key topics.")

    track_score("Content Accessibility", ca_score, 6)


# ---------------------------------------------------------------------------
# 9. AI Crawl Readiness
# ---------------------------------------------------------------------------
def check_ai_crawl_readiness(base_url):
    print("\n--- AI Crawl Readiness ---")
    resp, soup = get_soup(base_url)
    if not soup:
        print(f"  [{FAIL}] Could not fetch homepage")
        track_score("AI Crawl Readiness", 0, 8)
        return

    acr_score = 0
    body = soup.find("body")
    if body:
        body_text = body.get_text(separator=" ", strip=True)
        spa_indicators = ["__next", "__nuxt", "root", "app"]
        body_divs = body.find_all("div", id=True)
        div_ids = [d.get("id", "").lower() for d in body_divs]
        is_likely_spa = any(ind in div_ids for ind in spa_indicators)

        if is_likely_spa and len(body_text.split()) < 100:
            print(f"  [{FAIL}] Likely a client-side rendered SPA with minimal server-side content")
            print(f"         AI crawlers cannot execute JavaScript — consider SSR/SSG")
            fix("Enable server-side rendering in your framework:\n  Next.js: use getServerSideProps() or generateStaticParams()\n  Nuxt.js: set ssr: true in nuxt.config\n  React: consider migrating to Next.js or Remix")
        elif is_likely_spa:
            print(f"  [{PASS}] SPA framework detected but server-side content is present (SSR/SSG)")
            acr_score += 2
        else:
            print(f"  [{PASS}] Content is rendered server-side")
            acr_score += 2

    robots_meta = soup.find("meta", attrs={"name": "robots"})
    if robots_meta:
        robots_content = robots_meta.get("content", "").lower()
        if "noindex" in robots_content:
            print(f"  [{FAIL}] Meta robots contains 'noindex' — page will be excluded from AI training data")
            fix("Remove 'noindex' from the meta robots tag if you want AI engines to index this page:\n  <meta name=\"robots\" content=\"index, follow\" />")
        if "nofollow" in robots_content:
            print(f"  [{WARN}] Meta robots contains 'nofollow' — AI crawlers won't follow links on this page")
            fix("Remove 'nofollow' if you want AI crawlers to discover linked pages:\n  <meta name=\"robots\" content=\"index, follow\" />")
        if "noai" in robots_content or "noimageai" in robots_content:
            print(f"  [{WARN}] Meta robots contains AI-specific opt-out directive: {robots_content}")
            fix("The 'noai' / 'noimageai' directive opts your content out of AI training.\nRemove it if you want AI engines to include your content in their responses.")
        if "noindex" not in robots_content and "noai" not in robots_content:
            print(f"  [{PASS}] Meta robots allows indexing: {robots_content}")
            acr_score += 1
    else:
        print(f"  [{PASS}] No restrictive meta robots tag found")
        acr_score += 1

    x_robots = resp.headers.get("X-Robots-Tag", "")
    if x_robots:
        if "noindex" in x_robots.lower() or "noai" in x_robots.lower():
            print(f"  [{FAIL}] X-Robots-Tag header restricts AI: {x_robots}")
            fix("Remove the restrictive X-Robots-Tag header from your server config.\nNginx: remove 'add_header X-Robots-Tag \"noindex\";'\nApache: remove 'Header set X-Robots-Tag \"noindex\"'")
        else:
            print(f"  [{INFO}] X-Robots-Tag header present: {x_robots}")
    else:
        print(f"  [{PASS}] No restrictive X-Robots-Tag header")
        acr_score += 1

    paywall_indicators = [
        "paywall", "subscribe-wall", "login-wall", "premium-content",
        "gated-content", "registration-wall"
    ]
    paywall_classes = []
    for indicator in paywall_indicators:
        elements = soup.find_all(class_=re.compile(indicator, re.IGNORECASE))
        elements += soup.find_all(id=re.compile(indicator, re.IGNORECASE))
        if elements:
            paywall_classes.append(indicator)

    if paywall_classes:
        print(f"  [{WARN}] Possible gated content detected (classes/ids: {', '.join(paywall_classes)})")
        print(f"         Gated content is invisible to AI crawlers")
        fix("AI crawlers cannot see content behind paywalls/login walls.\nConsider:\n  1. Providing a generous free preview or summary above the gate.\n  2. Using 'metered' access so bots see full content on first visit.\n  3. Adding structured data (JSON-LD) with key facts outside the gate.")
    else:
        print(f"  [{PASS}] No paywall/login-wall indicators detected")
        acr_score += 1

    semantic_tags = ["article", "main", "section", "nav", "aside", "header", "footer"]
    found_semantic = [tag for tag in semantic_tags if soup.find(tag)]
    if len(found_semantic) >= 3:
        print(f"  [{PASS}] Good semantic HTML structure ({', '.join(found_semantic)})")
        acr_score += 1
    elif found_semantic:
        print(f"  [{WARN}] Limited semantic HTML ({', '.join(found_semantic)}) — more semantic tags help AI parse content")
        fix("Replace generic <div> containers with semantic HTML5 tags:\n  <header> for site header/nav\n  <main> for primary content\n  <article> for self-contained content\n  <section> for thematic groupings\n  <aside> for sidebar/related content\n  <footer> for footer")
    else:
        print(f"  [{FAIL}] No semantic HTML tags found — AI crawlers rely on semantic structure")
        fix("Your page uses only <div> tags. Replace them with semantic HTML5 elements:\n  <header>, <nav>, <main>, <article>, <section>, <aside>, <footer>\nThis helps AI engines understand the role of each content block.")

    images = soup.find_all("img")
    if images:
        with_alt = sum(1 for img in images if img.get("alt", "").strip())
        total = len(images)
        pct = (with_alt / total * 100) if total > 0 else 0
        if pct >= 80:
            print(f"  [{PASS}] {with_alt}/{total} images have alt text ({pct:.0f}%)")
            acr_score += 1
        elif pct >= 50:
            print(f"  [{WARN}] {with_alt}/{total} images have alt text ({pct:.0f}%) — aim for >80%")
            fix("Add descriptive alt text to all <img> tags:\n  <img src=\"photo.jpg\" alt=\"Description of what the image shows\" />\nGood alt text is specific: 'Team meeting in conference room' not 'image1'.")
        else:
            print(f"  [{FAIL}] Only {with_alt}/{total} images have alt text ({pct:.0f}%) — AI crawlers need alt text")
            fix("Most images are missing alt text. Add descriptive alt attributes to every <img>:\n  <img src=\"photo.jpg\" alt=\"Descriptive text about the image content\" />\nFor decorative images, use alt=\"\" (empty but present).")
    else:
        print(f"  [{INFO}] No images found on homepage")

    links = soup.find_all("a", href=True)
    parsed_base = urlparse(base_url)
    internal_links = [
        l for l in links
        if urlparse(urljoin(base_url, l["href"])).netloc == parsed_base.netloc
    ]
    if len(internal_links) >= 10:
        print(f"  [{PASS}] {len(internal_links)} internal links — good for AI crawl discovery")
    elif len(internal_links) >= 3:
        print(f"  [{WARN}] Only {len(internal_links)} internal links — more internal links help AI engines discover content")
        fix("Add more internal links to help AI crawlers discover your content.\nInclude links to key pages in your navigation, footer, and within content body.\nUse descriptive anchor text: 'Read our pricing guide' not 'click here'.")
    else:
        print(f"  [{FAIL}] Very few internal links ({len(internal_links)}) — AI crawlers rely on links to find content")
        fix("Your homepage has very few internal links. AI crawlers use links to discover pages.\nAdd:\n  1. A navigation menu linking to key sections\n  2. Featured content links in the body\n  3. A footer with links to important pages\n  4. Contextual links within content")

    start = time.time()
    fetch(urljoin(base_url, "/?_geo_timing_check"), timeout=10)
    elapsed = time.time() - start
    if elapsed < 1:
        print(f"  [{PASS}] Response time: {elapsed:.2f}s")
        acr_score += 1
    elif elapsed < 3:
        print(f"  [{WARN}] Response time: {elapsed:.2f}s — slow responses may cause AI crawlers to skip pages")
        fix("Improve response time:\n  1. Enable server-side caching (Redis, Varnish, CDN)\n  2. Optimize database queries\n  3. Use a CDN (Cloudflare, Fastly, CloudFront)\n  4. Enable gzip/brotli compression")
    else:
        print(f"  [{FAIL}] Response time: {elapsed:.2f}s — too slow for reliable AI crawling")
        fix("Response time is critically slow. AI crawlers may time out.\nImmediate actions:\n  1. Add a CDN in front of your origin server\n  2. Enable page caching at the server level\n  3. Profile your server-side code for bottlenecks\n  4. Consider static site generation for content pages")

    track_score("AI Crawl Readiness", acr_score, 8)


# ---------------------------------------------------------------------------
# 10. Content Quality for AI
# ---------------------------------------------------------------------------
def flesch_kincaid_grade(text):
    sentences = re.split(r'[.!?]+', text)
    sentences = [s.strip() for s in sentences if s.strip()]
    words = text.split()
    if not sentences or not words:
        return None

    def count_syllables(word):
        word = word.lower().rstrip("e")
        count = 0
        prev_vowel = False
        for ch in word:
            is_vowel = ch in "aeiou"
            if is_vowel and not prev_vowel:
                count += 1
            prev_vowel = is_vowel
        return max(count, 1)

    num_syllables = sum(count_syllables(w) for w in words)
    return 0.39 * (len(words) / len(sentences)) + 11.8 * (num_syllables / len(words)) - 15.59


def check_content_quality(base_url):
    print("\n--- Content Quality for AI ---")
    resp, soup = get_soup(base_url)
    if not soup:
        print(f"  [{FAIL}] Could not fetch homepage")
        track_score("Content Quality", 0, 7)
        return

    cq_score = 0
    text = get_text_content(soup)

    grade = flesch_kincaid_grade(text)
    if grade is not None:
        if 6 <= grade <= 12:
            print(f"  [{PASS}] Readability: Flesch-Kincaid grade {grade:.1f} (accessible)")
            cq_score += 2
        elif grade < 6:
            print(f"  [{INFO}] Readability: Flesch-Kincaid grade {grade:.1f} (very simple)")
            cq_score += 1.5
        else:
            print(f"  [{WARN}] Readability: Flesch-Kincaid grade {grade:.1f} (complex) — simpler text ranks better in AI answers")
            fix("Simplify your content for better AI readability:\n  1. Use shorter sentences (under 20 words)\n  2. Replace jargon with plain language\n  3. Break complex ideas into bullet points\n  4. Use active voice instead of passive\n  5. Target a grade 8-10 reading level")

    # FAQ detection
    faq_indicators = 0
    json_ld_scripts = soup.find_all("script", type="application/ld+json")
    for script in json_ld_scripts:
        try:
            data = json.loads(script.string)
            if isinstance(data, dict) and data.get("@type") == "FAQPage":
                faq_indicators += 2
        except (json.JSONDecodeError, TypeError):
            pass

    headings = soup.find_all(re.compile(r"^h[1-6]$"))
    question_headings = [h for h in headings if h.get_text(strip=True).rstrip().endswith("?")]
    if question_headings:
        faq_indicators += 1

    faq_elements = soup.find_all(class_=re.compile(r"faq|frequently.asked", re.IGNORECASE))
    faq_elements += soup.find_all(id=re.compile(r"faq|frequently.asked", re.IGNORECASE))
    if faq_elements:
        faq_indicators += 1

    if soup.find_all("details"):
        faq_indicators += 1

    if faq_indicators >= 2:
        print(f"  [{PASS}] FAQ content detected — strong signal for AI-generated answers")
        cq_score += 2
    elif faq_indicators == 1:
        print(f"  [{INFO}] Possible FAQ-like content — consider adding FAQPage structured data")
        cq_score += 1
        fix("Add FAQPage schema to boost AI answer ranking:\n  <script type=\"application/ld+json\">\n  {\n    \"@context\": \"https://schema.org\",\n    \"@type\": \"FAQPage\",\n    \"mainEntity\": [{\n      \"@type\": \"Question\",\n      \"name\": \"What is your product?\",\n      \"acceptedAnswer\": {\n        \"@type\": \"Answer\",\n        \"text\": \"Our product is...\"\n      }\n    }]\n  }\n  </script>")
    else:
        print(f"  [{INFO}] No FAQ content detected — FAQ pages rank well in AI-generated answers")
        fix("Consider adding an FAQ section to your page. Format questions as headings:\n  <h2>Frequently Asked Questions</h2>\n  <h3>What does your product do?</h3>\n  <p>Clear, concise answer...</p>\nThen add FAQPage structured data (JSON-LD) for each Q&A pair.")

    stat_patterns = re.findall(r'\d+(?:\.\d+)?%|\$\d+|\d+(?:,\d{3})+', text)
    if len(stat_patterns) >= 3:
        print(f"  [{PASS}] {len(stat_patterns)} quotable statistics found — good for AI citations")
        cq_score += 1
    elif stat_patterns:
        print(f"  [{INFO}] {len(stat_patterns)} statistic(s) found — more specific data improves AI citation likelihood")
    else:
        print(f"  [{WARN}] No quotable statistics found — specific numbers/data help AI engines cite your content")
        fix("Add concrete, quotable statistics to your content:\n  '95% of customers report improved performance'\n  'Over 10,000 companies use our platform'\n  'Reduces processing time by 3.5x'\nAI engines prefer citing specific data points over vague claims.")

    source_patterns = re.findall(
        r'(?:according to|source:|study by|research from|data from|report by|published in)\s',
        text, re.IGNORECASE
    )
    if source_patterns:
        print(f"  [{PASS}] {len(source_patterns)} source attribution(s) found — increases trust for AI engines")
        cq_score += 1
    else:
        print(f"  [{INFO}] No explicit source attributions — citing sources increases AI trust in your content")
        fix("Add source attributions to increase credibility:\n  'According to [Source Name], ...'\n  'Data from our 2025 industry report shows...'\n  'A study by [Institution] found...'\nAI engines weight attributed claims higher than unattributed ones.")

    lists = soup.find_all(["ul", "ol"])
    list_items = soup.find_all("li")
    if len(list_items) >= 5:
        print(f"  [{PASS}] Structured lists found ({len(lists)} lists, {len(list_items)} items)")
        cq_score += 1
    elif list_items:
        print(f"  [{INFO}] Some list content ({len(list_items)} items) — structured lists help AI extract key points")
    else:
        print(f"  [{WARN}] No list elements — structured lists help AI engines extract key points")
        fix("Add structured lists to make content easily extractable by AI:\n  <ul>\n    <li>Key feature or benefit</li>\n    <li>Another important point</li>\n  </ul>\nUse <ol> for steps/processes and <ul> for features/benefits.")

    track_score("Content Quality", min(cq_score, 7), 7)


# ---------------------------------------------------------------------------
# 11. Technical Crawlability
# ---------------------------------------------------------------------------
def check_technical_crawlability(base_url):
    print("\n--- Technical Crawlability ---")
    resp, soup = get_soup(base_url)
    if not soup:
        print(f"  [{FAIL}] Could not fetch homepage")
        track_score("Technical Crawlability", 0, 5)
        return

    tc_score = 0
    canonical = soup.find("link", rel="canonical")
    if canonical and canonical.get("href"):
        canonical_url = urljoin(base_url, canonical["href"])
        if canonical_url.rstrip("/") != base_url.rstrip("/"):
            canon_resp = fetch(canonical_url)
            if canon_resp and canon_resp.status_code == 200:
                canon_soup = BeautifulSoup(canon_resp.text, "html.parser")
                canon2 = canon_soup.find("link", rel="canonical")
                if canon2 and canon2.get("href"):
                    canon2_url = urljoin(canonical_url, canon2["href"])
                    if canon2_url.rstrip("/") != canonical_url.rstrip("/"):
                        print(f"  [{WARN}] Canonical chain detected: {base_url} -> {canonical_url} -> {canon2_url}")
                        fix("Fix the canonical chain — each page's canonical should point directly to the final URL, not through intermediaries.\nSet the canonical on each page to its own URL or the ultimate target.")
                    else:
                        print(f"  [{PASS}] Canonical URL resolves correctly")
                        tc_score += 1.5
                else:
                    print(f"  [{PASS}] Canonical URL resolves correctly")
                    tc_score += 1.5
            else:
                print(f"  [{FAIL}] Canonical URL {canonical_url} returns error")
                fix(f"The canonical URL {canonical_url} is broken. Either fix the target page or update the canonical to a working URL.")
        else:
            print(f"  [{PASS}] Canonical URL is self-referencing (correct)")
            tc_score += 1.5

    try:
        no_redir_resp = requests.get(base_url, allow_redirects=False, timeout=10, headers={
            "User-Agent": "GEO-Readiness-Checker/1.0"
        })
        if no_redir_resp.is_redirect:
            redir_resp = requests.get(base_url, allow_redirects=True, timeout=10, headers={
                "User-Agent": "GEO-Readiness-Checker/1.0"
            })
            num_redirects = len(redir_resp.history)
            if num_redirects > 2:
                chain = " -> ".join(r.url for r in redir_resp.history)
                print(f"  [{WARN}] Redirect chain with {num_redirects} hops: {chain} -> {redir_resp.url}")
                print(f"         Long redirect chains can cause AI crawlers to give up")
                fix("Reduce the redirect chain to a single hop (A -> B, not A -> B -> C -> D).\nUpdate your server config to redirect directly to the final destination URL.")
            elif num_redirects > 0:
                print(f"  [{PASS}] {num_redirects} redirect(s) — within acceptable range")
                tc_score += 1
        else:
            print(f"  [{PASS}] No redirects — direct access")
            tc_score += 1
    except requests.RequestException:
        print(f"  [{WARN}] Could not test redirect chain")

    try:
        import subprocess
        result = subprocess.run(
            ["curl", "-sI", "--http2", "-o", "/dev/null", "-w", "%{http_version}", base_url],
            capture_output=True, text=True, timeout=10
        )
        http_version = result.stdout.strip()
        if http_version in ("2", "3"):
            print(f"  [{PASS}] HTTP/{http_version} supported — faster crawling")
            tc_score += 1
        elif http_version:
            print(f"  [{INFO}] HTTP/{http_version} — consider upgrading to HTTP/2 or HTTP/3 for faster crawling")
            fix("Enable HTTP/2 on your server for faster crawling:\n  Nginx: listen 443 ssl http2;\n  Apache: Protocols h2 http/1.1\n  Or use a CDN like Cloudflare which enables HTTP/2 automatically.")
    except Exception:
        print(f"  [{INFO}] Could not determine HTTP version")

    feed_url = None
    feeds = soup.find_all("link", type=re.compile(r"(rss|atom)\+xml", re.IGNORECASE))
    if feeds:
        feed_urls = [f.get("href", "N/A") for f in feeds]
        print(f"  [{PASS}] RSS/Atom feed(s) found: {', '.join(feed_urls[:3])}")
        tc_score += 1.5
        first_href = feeds[0].get("href")
        if first_href:
            feed_url = urljoin(base_url, first_href)
    else:
        for feed_path in ["/feed", "/feed.xml", "/rss.xml", "/atom.xml", "/rss", "/blog/feed"]:
            candidate = urljoin(base_url, feed_path)
            feed_resp = fetch(candidate, timeout=5)
            if feed_resp and feed_resp.status_code == 200 and ("<rss" in feed_resp.text or "<feed" in feed_resp.text):
                print(f"  [{PASS}] Feed found at {feed_path}")
                feed_url = candidate
                tc_score += 1.5
                break
        if not feed_url:
            print(f"  [{INFO}] No RSS/Atom feed found — feeds help AI engines monitor content freshness")
            fix("Add an RSS or Atom feed for your content and link to it in <head>:\n  <link rel=\"alternate\" type=\"application/rss+xml\" title=\"RSS\" href=\"/feed.xml\" />\nMost CMS platforms generate feeds automatically. For static sites, tools like eleventy-rss can help.")

    # Feed richness: full content vs excerpt
    if feed_url:
        feed_resp = fetch(feed_url, timeout=8)
        if feed_resp and feed_resp.status_code == 200:
            feed_text = feed_resp.text
            # Count items/entries and measure content length
            rss_items = re.findall(r"<item\b[^>]*>.*?</item>", feed_text, re.DOTALL | re.IGNORECASE)
            atom_entries = re.findall(r"<entry\b[^>]*>.*?</entry>", feed_text, re.DOTALL | re.IGNORECASE)
            entries = rss_items or atom_entries
            if entries:
                lengths = []
                for entry in entries[:10]:
                    content_match = re.search(r"<content:encoded[^>]*>(.*?)</content:encoded>", entry, re.DOTALL | re.IGNORECASE)
                    if not content_match:
                        content_match = re.search(r"<content[^>]*>(.*?)</content>", entry, re.DOTALL | re.IGNORECASE)
                    if not content_match:
                        content_match = re.search(r"<description[^>]*>(.*?)</description>", entry, re.DOTALL | re.IGNORECASE)
                    if content_match:
                        stripped = re.sub(r"<[^>]+>", "", content_match.group(1))
                        stripped = re.sub(r"<!\[CDATA\[|\]\]>", "", stripped).strip()
                        lengths.append(len(stripped.split()))
                if lengths:
                    avg = sum(lengths) / len(lengths)
                    if avg >= 300:
                        print(f"  [{PASS}] Feed provides full content (avg {int(avg)} words/item) — AI-friendly")
                        tc_score += 0.5
                    elif avg >= 80:
                        print(f"  [{INFO}] Feed provides excerpts (avg {int(avg)} words/item) — consider full content")
                        fix("Publish full content in your feed rather than excerpts. AI agents that consume feeds\n"
                            "programmatically prefer complete text they can extract without following every link:\n"
                            "  WordPress: Settings → Reading → 'Full text' in feed\n"
                            "  Custom: include <content:encoded> with the full post body")
                    else:
                        print(f"  [{WARN}] Feed items are very short (avg {int(avg)} words) — mostly headlines")
                        fix("Your feed publishes only headlines/snippets. Switch to full content so AI agents\n"
                            "and aggregators can index the actual article without scraping the HTML page.")

    # Machine-readable exports & integration docs
    api_probes = [
        ("/api", "API base path"),
        ("/api/v1", "Versioned API"),
        ("/graphql", "GraphQL endpoint"),
        ("/openapi.json", "OpenAPI spec"),
        ("/openapi.yaml", "OpenAPI spec"),
        ("/swagger.json", "Swagger spec"),
        ("/docs/api", "API documentation"),
        ("/webhooks", "Webhook documentation"),
        ("/integrations", "Integrations page"),
        ("/developers", "Developer portal"),
    ]
    machine_readable_found = []
    for path, label in api_probes:
        r = fetch(urljoin(base_url, path), timeout=5)
        if r and r.status_code == 200 and len(r.text.strip()) > 100:
            machine_readable_found.append((path, label))
            if len(machine_readable_found) >= 3:
                break
    if machine_readable_found:
        print(f"  [{PASS}] Machine-readable / integration endpoints: {', '.join(p for p, _ in machine_readable_found[:3])}")
        tc_score += 0.5
    else:
        print(f"  [{INFO}] No API / integration / webhook documentation detected")
        fix("Publish machine-readable data feeds and integration docs so AI agents can consume\n"
            "your data programmatically:\n"
            "  • /openapi.json (or /swagger.json) for a public API\n"
            "  • /webhooks for event subscription documentation\n"
            "  • /integrations or /developers as a landing page linking SDKs, API keys, examples")

    track_score("Technical Crawlability", min(tc_score, 5), 5)


# ---------------------------------------------------------------------------
# 12. Authority & Trust Signals
# ---------------------------------------------------------------------------
def check_authority_trust(base_url):
    print("\n--- Authority & Trust Signals ---")
    resp, soup = get_soup(base_url)
    if not resp:
        print(f"  [{FAIL}] Could not fetch homepage")
        track_score("Authority & Trust", 0, 5)
        return

    at_score = 0

    security_headers = {
        "Strict-Transport-Security": "HSTS",
        "Content-Security-Policy": "CSP",
        "X-Content-Type-Options": "X-Content-Type-Options",
        "X-Frame-Options": "X-Frame-Options",
    }
    found_sec_headers = 0
    for header in security_headers:
        if resp.headers.get(header):
            found_sec_headers += 1

    if found_sec_headers >= 3:
        present = [h for h in security_headers if resp.headers.get(h)]
        print(f"  [{PASS}] Strong security headers ({found_sec_headers}/4): {', '.join(present)}")
        at_score += 2
    elif found_sec_headers >= 1:
        present = [h for h in security_headers if resp.headers.get(h)]
        missing = [h for h in security_headers if not resp.headers.get(h)]
        print(f"  [{WARN}] Some security headers present ({found_sec_headers}/4): {', '.join(present)}")
        at_score += 1
        print(f"         Missing: {', '.join(missing)}")
        fix("Add missing security headers to your server config:\n  Strict-Transport-Security: max-age=31536000; includeSubDomains\n  Content-Security-Policy: default-src 'self'\n  X-Content-Type-Options: nosniff\n  X-Frame-Options: DENY")
    else:
        print(f"  [{FAIL}] No security headers found — reduces trust signal for AI engines")
        fix("Add security headers to your server response. In nginx:\n  add_header Strict-Transport-Security \"max-age=31536000; includeSubDomains\" always;\n  add_header Content-Security-Policy \"default-src 'self'\" always;\n  add_header X-Content-Type-Options \"nosniff\" always;\n  add_header X-Frame-Options \"DENY\" always;")

    humans_url = urljoin(base_url, "/humans.txt")
    humans_resp = fetch(humans_url)
    if humans_resp and humans_resp.status_code == 200 and len(humans_resp.text.strip()) > 0:
        print(f"  [{PASS}] humans.txt found — authorship transparency")
        at_score += 1
    else:
        print(f"  [{INFO}] No humans.txt — optional authorship transparency file")
        fix("Create a humans.txt at your site root to signal authorship:\n  /* TEAM */\n  Name: Your Name\n  Role: Lead Developer\n  Contact: email@example.com\n  \n  /* SITE */\n  Last update: 2025/01/15\n  Standards: HTML5, CSS3\nSee humanstxt.org for the full spec.")

    if soup:
        json_ld_scripts = soup.find_all("script", type="application/ld+json")
        has_author = False
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict):
                    if data.get("author") or data.get("@type") == "Person":
                        has_author = True
                    graph = data.get("@graph", [])
                    for item in graph:
                        if isinstance(item, dict) and (item.get("author") or item.get("@type") == "Person"):
                            has_author = True
            except (json.JSONDecodeError, TypeError):
                pass

        author_meta = soup.find("meta", attrs={"name": "author"})
        author_link = soup.find("link", rel="author")
        author_tag = soup.find(class_=re.compile(r"author", re.IGNORECASE))

        if has_author:
            print(f"  [{PASS}] Author markup found in structured data (JSON-LD)")
            at_score += 2
        elif author_meta or author_link:
            print(f"  [{PASS}] Author information found (meta/link tag)")
            at_score += 1.5
        elif author_tag:
            print(f"  [{INFO}] Author class detected in HTML — consider adding schema.org Person markup")
            fix("Upgrade your author attribution with JSON-LD:\n  \"author\": {\n    \"@type\": \"Person\",\n    \"name\": \"Author Name\",\n    \"url\": \"https://authorsite.com\"\n  }")
        else:
            print(f"  [{WARN}] No author attribution found — authorship signals boost AI trust (E-E-A-T)")
            fix("Add author information to boost E-E-A-T signals:\n  1. Add <meta name=\"author\" content=\"Author Name\">\n  2. Or add author to your JSON-LD structured data:\n     \"author\": {\"@type\": \"Person\", \"name\": \"Author Name\"}\n  3. For blog posts, display author name, bio, and credentials visibly on the page.")

        # E-E-A-T depth: look for a bio/about/team page and assess credentials
        bio_url = None
        bio_text = ""
        for path in ["/about", "/about-us", "/team", "/authors", "/our-team", "/people"]:
            candidate = urljoin(base_url, path)
            r = fetch(candidate, timeout=8)
            if r and r.status_code == 200 and len(r.text) > 500:
                try:
                    s = BeautifulSoup(r.text, "html.parser")
                    bio_text = get_text_content(s)
                    if len(bio_text.split()) >= 50:
                        bio_url = candidate
                        break
                except Exception:
                    pass

        credential_keywords = [
            "phd", "ph.d", "m.d.", "md,", "dphil", "doctorate",
            "founder", "ceo", "cto", "cfo", "coo", "chief ",
            "years of experience", "years experience", "decades of",
            "formerly at", "previously at", "ex-", "alumnus", "alumni",
            "certified", "licensed", "board-certified",
            "author of", "published in", "featured in", "cited by",
            "harvard", "stanford", "mit ", "oxford", "cambridge", "berkeley",
        ]
        bylines_hosts = [
            "medium.com/@", "substack.com", "forbes.com", "techcrunch.com",
            "hbr.org", "wired.com", "theverge.com", "bloomberg.com",
            "scholar.google", "orcid.org", "arxiv.org",
        ]

        if bio_url:
            print(f"  [{PASS}] Bio/about page found at {urlparse(bio_url).path}")
            at_score += 0.5
            bio_lower = bio_text.lower()
            found_creds = [k for k in credential_keywords if k in bio_lower]
            if found_creds:
                print(f"  [{PASS}] Credential signals in bio: {', '.join(sorted(set(found_creds))[:5])}")
                at_score += 1
            else:
                print(f"  [{INFO}] Bio page has little credential language — add credentials/experience")
                fix("Strengthen your bio/about page with explicit E-E-A-T signals:\n"
                    "  • Credentials (PhD, MD, certifications)\n"
                    "  • Years of experience and roles (\"10 years at X as...\")\n"
                    "  • Notable prior affiliations (\"formerly at Google\", \"ex-McKinsey\")\n"
                    "  • External bylines, publications, or press coverage")

            # External bylines discovered on bio page
            try:
                bs = BeautifulSoup(fetch(bio_url, timeout=8).text, "html.parser")
                external_bylines = set()
                for a in bs.find_all("a", href=True):
                    href = a["href"].lower()
                    for host in bylines_hosts:
                        if host in href:
                            external_bylines.add(host.split("/")[0] if "/" in host else host)
                if external_bylines:
                    print(f"  [{PASS}] External byline/profile links: {', '.join(sorted(external_bylines))}")
                    at_score += 0.5
                else:
                    print(f"  [{INFO}] No external bylines detected on bio page")
                    fix("Link to external bylines (Medium, Substack, trade press, Google Scholar, ORCID)\n"
                        "from your bio/about page. Independent bylines carry more E-E-A-T weight than self-claims.")
            except Exception:
                pass
        else:
            print(f"  [{WARN}] No author bio / about / team page found")
            fix("Create a substantive /about or /team page (200+ words) documenting who is behind\n"
                "the site: real names, credentials, photos, contact paths, and links to external profiles.\n"
                "AI engines treat faceless sites as lower E-E-A-T.")

    track_score("Authority & Trust", min(at_score, 5), 5)


# ---------------------------------------------------------------------------
# 12b. Brand Entity in Knowledge Graphs (Wikipedia / Wikidata)
# ---------------------------------------------------------------------------
def check_brand_entity_kg(base_url):
    """Check if the site's brand exists as a recognized entity in Wikipedia/Wikidata."""
    print("\n--- Brand Entity in Knowledge Graphs ---")

    # Derive brand candidates from domain and page signals
    resp, soup = get_soup(base_url)
    parsed = urlparse(base_url)
    domain = parsed.netloc.replace("www.", "")
    raw_brand = domain.split(".")[0]

    candidates = [raw_brand]
    # Prefer a human-readable brand from og:site_name or <title>
    if soup:
        og_site = soup.find("meta", property="og:site_name")
        if og_site and og_site.get("content"):
            candidates.insert(0, og_site["content"].strip())
        t = soup.find("title")
        if t and t.string and t.string.strip():
            parts = re.split(r'[|\-\u2013\u2014]', t.string)
            if parts:
                tail = parts[-1].strip()
                if 2 <= len(tail) <= 40 and tail not in candidates:
                    candidates.append(tail)
        # Organization name from JSON-LD
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                items = [data] if isinstance(data, dict) else data if isinstance(data, list) else []
                if isinstance(data, dict) and "@graph" in data:
                    items.extend(data["@graph"])
                for item in items:
                    if isinstance(item, dict):
                        t_val = item.get("@type", "")
                        if t_val in ("Organization", "LocalBusiness", "Corporation") and item.get("name"):
                            candidates.insert(0, item["name"].strip())
            except (json.JSONDecodeError, TypeError):
                pass

    # Dedupe while preserving order
    seen_c = set()
    candidates = [c for c in candidates if c and not (c.lower() in seen_c or seen_c.add(c.lower()))]
    brand = candidates[0]
    print(f"  Checking entity: \"{brand}\" (domain: {domain})")

    import urllib.parse
    score = 0
    wiki_page = None
    wikidata_id = None
    backlink_count = 0

    # Wikipedia
    try:
        enc = urllib.parse.quote(brand)
        r = requests.get(
            f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={enc}&format=json&srlimit=3",
            timeout=10, headers={"User-Agent": "GEO-Checker/1.0"},
        )
        if r.status_code == 200:
            results = r.json().get("query", {}).get("search", [])
            for result in results:
                title = result.get("title", "")
                if brand.lower() in title.lower() or title.lower() in brand.lower():
                    wiki_page = title
                    break
    except requests.RequestException:
        pass

    if wiki_page:
        print(f"  [{PASS}] Wikipedia page found: \"{wiki_page}\"")
        score += 2
        # Backlink proxy: count pages that link to this article
        try:
            enc = urllib.parse.quote(wiki_page)
            br = requests.get(
                f"https://en.wikipedia.org/w/api.php?action=query&list=backlinks&bltitle={enc}&bllimit=50&format=json",
                timeout=10, headers={"User-Agent": "GEO-Checker/1.0"},
            )
            if br.status_code == 200:
                backlink_count = len(br.json().get("query", {}).get("backlinks", []))
                if backlink_count >= 20:
                    print(f"  [{PASS}] Wikipedia backlinks: {backlink_count}+ pages link to this entity — strong authority")
                    score += 1
                elif backlink_count >= 5:
                    print(f"  [{INFO}] Wikipedia backlinks: {backlink_count} pages link to this entity")
                    score += 0.5
                else:
                    print(f"  [{INFO}] Only {backlink_count} Wikipedia backlink(s) — entity is recognized but niche")
        except requests.RequestException:
            pass
    else:
        print(f"  [{WARN}] No Wikipedia page found for \"{brand}\"")
        fix("A Wikipedia page is one of the strongest entity signals for AI engines. If you're\n"
            "notable enough, seek independent coverage in news/trade press and follow Wikipedia's\n"
            "notability guidelines. Do not write your own page — it will be flagged as COI.")

    # Wikidata
    try:
        enc = urllib.parse.quote(brand)
        r = requests.get(
            f"https://www.wikidata.org/w/api.php?action=wbsearchentities&search={enc}&language=en&format=json&limit=3",
            timeout=10, headers={"User-Agent": "GEO-Checker/1.0"},
        )
        if r.status_code == 200:
            for result in r.json().get("search", []):
                label = result.get("label", "")
                if brand.lower() in label.lower() or label.lower() in brand.lower():
                    wikidata_id = result.get("id")
                    break
    except requests.RequestException:
        pass

    if wikidata_id:
        print(f"  [{PASS}] Wikidata entity found: {wikidata_id}")
        score += 2
    else:
        print(f"  [{WARN}] No Wikidata entity found for \"{brand}\"")
        fix("Wikidata is free to edit and AI engines (especially Google Knowledge Graph) ingest it\n"
            "heavily. Create an entry at https://www.wikidata.org/wiki/Special:NewItem with:\n"
            "  • Label + description\n"
            "  • instance of (P31) — e.g. 'business'\n"
            "  • official website (P856) — your domain\n"
            "  • sameAs links to social profiles")

    track_score("Brand Entity KG", min(score, 5), 5)


# ---------------------------------------------------------------------------
# 12c. Trust & Safety Signals (privacy/terms/contact/DMCA/business info)
# ---------------------------------------------------------------------------
def check_trust_safety(base_url):
    """Check for trust & safety pages and business identity signals that AI engines use
    to assess source credibility and citation-worthiness."""
    print("\n--- Trust & Safety Signals ---")
    resp, soup = get_soup(base_url)
    if not soup:
        print(f"  [{FAIL}] Could not fetch homepage")
        track_score("Trust & Safety", 0, 6)
        return

    ts_score = 0

    # Build a merged haystack: homepage HTML + linked policy anchors
    home_links = {a.get("href", "").lower(): (a.get_text(strip=True) or "").lower()
                  for a in soup.find_all("a", href=True)}

    def _anchor_match(keywords):
        for href, text in home_links.items():
            combined = f"{href} {text}"
            if any(k in combined for k in keywords):
                return href
        return None

    # Path sets for 4 trust pages. Kept as separate names so the per-category
    # scoring logic below reads naturally.
    privacy_paths = ["/privacy", "/privacy-policy", "/privacy.html", "/legal/privacy",
                     "/policies/privacy", "/privacypolicy"]
    terms_paths = ["/terms", "/terms-of-service", "/tos", "/terms-of-use",
                   "/terms.html", "/legal/terms"]
    contact_paths = ["/contact", "/contact-us", "/contactus", "/get-in-touch",
                     "/support", "/help"]
    legal_paths = ["/dmca", "/copyright", "/legal", "/legal-notice", "/imprint"]

    # Fetch all 23 candidate URLs in one concurrent batch instead of 4 serial
    # probe loops. For sites where most paths return 404/403 (baidu etc.),
    # this collapses ~55s of serial waiting into ~3s of parallel fetches.
    # _page_cache writes are GIL-safe; worst case is a duplicate fetch if two
    # threads miss the cache simultaneously, which is harmless.
    all_probe_paths = privacy_paths + terms_paths + contact_paths + legal_paths
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(10, len(all_probe_paths))) as pool:
        probe_results = dict(pool.map(
            lambda p: (p, fetch(urljoin(base_url, p), timeout=6)),
            all_probe_paths,
        ))

    def _first_match(paths):
        """Pick the first path whose cached response is 200 + substantive."""
        for p in paths:
            r = probe_results.get(p)
            if r and r.status_code == 200 and len(r.text) > 500:
                return p
        return None

    # 1. Privacy policy
    privacy_found = _first_match(privacy_paths) or _anchor_match(["privacy"])
    if privacy_found:
        print(f"  [{PASS}] Privacy policy found: {privacy_found}")
        ts_score += 1.5
    else:
        print(f"  [{FAIL}] No privacy policy page detected")
        fix("Publish a Privacy Policy at /privacy (or /privacy-policy). AI engines treat missing\n"
            "privacy policies as a trust red flag — required by GDPR, CCPA, and most ad networks.")

    # 2. Terms of service
    terms_found = _first_match(terms_paths) or _anchor_match(["terms", "tos"])
    if terms_found:
        print(f"  [{PASS}] Terms of service found: {terms_found}")
        ts_score += 1
    else:
        print(f"  [{WARN}] No terms of service page detected")
        fix("Publish Terms of Service at /terms. This is a basic trust signal AI engines\n"
            "and search platforms expect from legitimate sites.")

    # 3. Contact page
    contact_found = _first_match(contact_paths) or _anchor_match(["contact", "get in touch"])
    if contact_found:
        print(f"  [{PASS}] Contact page found: {contact_found}")
        ts_score += 1
    else:
        print(f"  [{WARN}] No contact page detected")
        fix("Add a /contact page with at least an email address and/or form. AI engines rank\n"
            "sites with clear contact paths higher for trust-sensitive queries.")

    # 4. DMCA / copyright / legal
    legal_found = _first_match(legal_paths) or _anchor_match(["dmca", "copyright", "imprint", "legal notice"])
    if legal_found:
        print(f"  [{PASS}] Legal/DMCA/imprint page found: {legal_found}")
        ts_score += 0.5
    else:
        print(f"  [{INFO}] No DMCA / legal / imprint page detected")
        fix("Add a /dmca or /legal page. In the EU an 'Impressum' (imprint) is legally required;\n"
            "elsewhere a DMCA agent page protects you from copyright liability and boosts trust.")

    # 5. Business identity: address / phone / email / registration in footer or schema
    homepage_text = get_text_content(soup)
    footer = soup.find("footer")
    footer_text = footer.get_text(" ", strip=True) if footer else ""

    # Email / phone / street address heuristics
    email_re = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
    phone_re = re.compile(r"(?:\+?\d{1,3}[\s\-.])?\(?\d{2,4}\)?[\s\-.]\d{3,4}[\s\-.]\d{3,4}")
    address_hint = re.compile(
        r"\b\d{1,5}\s+\w+(?:\s+\w+){0,5}\s+"
        r"(?:street|st\.?|road|rd\.?|avenue|ave\.?|boulevard|blvd\.?|lane|ln\.?|drive|dr\.?|suite|ste\.?|floor|fl\.?)\b",
        re.IGNORECASE,
    )
    # Business registration numbers (LLC, Inc, GmbH, Ltd, AG, AB, SA, SARL, Pty, EIN, VAT, ABN, SIREN)
    registration_re = re.compile(
        r"\b(?:LLC|Inc\.?|Corp\.?|Ltd\.?|GmbH|AG|S\.?A\.?|S\.?L\.?|SARL|Pty|BV|Oy)\b"
        r"|\b(?:EIN|VAT|ABN|SIREN|SIRET|company\s+(?:no|number)|reg(?:istration)?\s+(?:no|number)|CIN)\b",
        re.IGNORECASE,
    )

    # Structured data signals
    sd_has_address = False
    sd_has_contact_point = False
    sd_has_telephone = False
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            items = [data] if isinstance(data, dict) else data if isinstance(data, list) else []
            if isinstance(data, dict) and "@graph" in data:
                items.extend(data["@graph"])
            for item in items:
                if not isinstance(item, dict):
                    continue
                if item.get("address"):
                    sd_has_address = True
                if item.get("contactPoint"):
                    sd_has_contact_point = True
                if item.get("telephone"):
                    sd_has_telephone = True
        except (json.JSONDecodeError, TypeError):
            pass

    has_email = bool(email_re.search(footer_text) or email_re.search(homepage_text))
    has_phone = bool(phone_re.search(footer_text) or phone_re.search(homepage_text))
    has_address = (
        sd_has_address
        or bool(address_hint.search(footer_text))
        or bool(address_hint.search(homepage_text))
    )
    has_registration = bool(registration_re.search(footer_text) or registration_re.search(homepage_text))

    identity_signals = []
    if has_email or sd_has_contact_point:
        identity_signals.append("email/contactPoint")
    if has_phone or sd_has_telephone:
        identity_signals.append("phone")
    if has_address:
        identity_signals.append("address")
    if has_registration:
        identity_signals.append("legal entity")

    if len(identity_signals) >= 3:
        print(f"  [{PASS}] Strong business identity in footer/schema: {', '.join(identity_signals)}")
        ts_score += 2
    elif len(identity_signals) >= 1:
        print(f"  [{WARN}] Partial business identity: {', '.join(identity_signals)}")
        ts_score += 1
        missing = []
        if not (has_email or sd_has_contact_point):
            missing.append("email or contactPoint")
        if not (has_phone or sd_has_telephone):
            missing.append("phone")
        if not has_address:
            missing.append("physical address")
        if not has_registration:
            missing.append("legal entity (LLC/Inc/Ltd/GmbH/EIN/VAT)")
        fix("Add missing trust signals so AI engines can verify who is behind the site:\n  "
            + "\n  ".join(f"- {m}" for m in missing))
    else:
        print(f"  [{FAIL}] No business identity signals found (email, phone, address, or legal entity)")
        fix("AI engines cannot verify who runs this site. Add in the footer and/or Organization JSON-LD:\n"
            "  • Physical address (schema.org PostalAddress)\n"
            "  • Contact email and telephone (contactPoint)\n"
            "  • Legal entity suffix (LLC / Inc / Ltd / GmbH) and registration number where applicable")

    track_score("Trust & Safety", min(ts_score, 6), 6)


# ---------------------------------------------------------------------------
# 13. AI-Specific Optimization
# ---------------------------------------------------------------------------
def check_ai_optimization(base_url):
    print("\n--- AI-Specific Optimization ---")
    resp, soup = get_soup(base_url)
    if not soup:
        print(f"  [{FAIL}] Could not fetch homepage")
        track_score("AI Optimization", 0, 5)
        return

    ao_score = 0

    freshness_signals = []
    json_ld_scripts = soup.find_all("script", type="application/ld+json")
    for script in json_ld_scripts:
        try:
            data = json.loads(script.string)
            if isinstance(data, dict):
                for key in ["dateModified", "datePublished", "dateCreated"]:
                    if data.get(key):
                        freshness_signals.append(f"JSON-LD {key}: {data[key]}")
                graph = data.get("@graph", [])
                for item in graph:
                    if isinstance(item, dict):
                        for key in ["dateModified", "datePublished"]:
                            if item.get(key):
                                freshness_signals.append(f"JSON-LD {key}: {item[key]}")
        except (json.JSONDecodeError, TypeError):
            pass

    time_tags = soup.find_all("time", datetime=True)
    if time_tags:
        freshness_signals.append(f"{len(time_tags)} <time> tag(s)")

    last_modified = resp.headers.get("Last-Modified")
    if last_modified:
        freshness_signals.append(f"Last-Modified header: {last_modified}")

    if freshness_signals:
        print(f"  [{PASS}] Content freshness signals found:")
        ao_score += 2
        for sig in freshness_signals[:5]:
            print(f"         {sig}")
    else:
        print(f"  [{WARN}] No content freshness signals — add dateModified to JSON-LD or <time> elements")
        fix("Add freshness signals so AI engines know your content is current:\n  1. Add dateModified to your JSON-LD: \"dateModified\": \"2025-01-15\"\n  2. Use <time> tags: <time datetime=\"2025-01-15\">January 15, 2025</time>\n  3. Set Last-Modified HTTP header on your server")

    # Sitewide update cadence — analyze sitemap <lastmod> dates across the whole site
    from datetime import datetime, timezone
    sitemap_resp = fetch(urljoin(base_url, "/sitemap.xml"), timeout=10)
    if not sitemap_resp or sitemap_resp.status_code != 200:
        sitemap_resp = fetch(urljoin(base_url, "/sitemap_index.xml"), timeout=10)
    lastmods = []
    if sitemap_resp and sitemap_resp.status_code == 200 and "<" in sitemap_resp.text:
        lastmods = re.findall(r"<lastmod>([^<]+)</lastmod>", sitemap_resp.text)
        # If this is an index, follow the first few child sitemaps
        if "<sitemapindex" in sitemap_resp.text:
            child_locs = re.findall(r"<loc>([^<]+)</loc>", sitemap_resp.text)[:3]
            for loc in child_locs:
                child = fetch(loc.strip(), timeout=8)
                if child and child.status_code == 200:
                    lastmods.extend(re.findall(r"<lastmod>([^<]+)</lastmod>", child.text))

    parsed_dates = []
    for lm in lastmods[:200]:
        lm = lm.strip()
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(lm.replace("Z", "+0000") if fmt == "%Y-%m-%dT%H:%M:%S%z" and "Z" in lm else lm, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                parsed_dates.append(dt)
                break
            except ValueError:
                continue

    if parsed_dates:
        now = datetime.now(timezone.utc)
        ages_days = sorted((now - d).days for d in parsed_dates)
        median_days = ages_days[len(ages_days) // 2]
        fresh_90 = sum(1 for a in ages_days if a <= 90)
        fresh_ratio = fresh_90 / len(ages_days)
        print(f"  [{INFO}] Sitemap contains {len(parsed_dates)} <lastmod> entries "
              f"(median age: {median_days} days, {fresh_90}/{len(ages_days)} updated in last 90d)")
        if fresh_ratio >= 0.5 or median_days <= 90:
            print(f"  [{PASS}] Healthy sitewide update cadence")
            ao_score += 1
        elif fresh_ratio >= 0.2:
            print(f"  [{WARN}] Moderate cadence — less than half of pages updated in the last 90 days")
            fix("Increase content refresh cadence. AI engines prefer sites that update regularly — stale pages\n"
                "drop out of training windows and retrieval indexes.")
        else:
            print(f"  [{WARN}] Low cadence — most pages are stale (median {median_days} days old)")
            fix("Most of your content hasn't been touched in months. Refresh high-value pages periodically\n"
                "(update stats, add recent examples, bump dateModified) so AI engines see ongoing maintenance.")
    else:
        print(f"  [{INFO}] Could not analyze sitewide update cadence (no parseable <lastmod> in sitemap)")

    title = soup.find("title")
    og_site = soup.find("meta", property="og:site_name")
    site_names = set()
    if title and title.string:
        parts = re.split(r'[|\-\u2013\u2014]', title.string)
        if len(parts) > 1:
            site_names.add(parts[-1].strip())
    if og_site and og_site.get("content"):
        site_names.add(og_site["content"].strip())

    if len(site_names) > 1:
        print(f"  [{WARN}] Inconsistent site name across tags: {', '.join(site_names)}")
        fix(f"Use the same brand name everywhere. Ensure og:site_name, the title tag suffix,\nand JSON-LD Organization name all use the exact same string.\nPick one: {' or '.join(repr(n) for n in site_names)}")
    elif site_names:
        name = list(site_names)[0]
        text = get_text_content(soup)
        occurrences = text.lower().count(name.lower())
        if occurrences >= 2:
            print(f"  [{PASS}] Brand entity \"{name}\" used consistently ({occurrences} occurrences)")
            ao_score += 1.5
        else:
            print(f"  [{INFO}] Brand entity \"{name}\" found but used sparingly — consistent naming helps AI entity recognition")
            fix(f"Use your brand name \"{name}\" more consistently throughout the page content.\nMention it in headings, intro paragraphs, and structured data to strengthen entity recognition.")
    else:
        print(f"  [{INFO}] Could not determine primary brand/entity name")
        fix("Make your brand name discoverable by adding:\n  <meta property=\"og:site_name\" content=\"Your Brand\" />\nAnd use a consistent 'Brand — Page Title' format in your <title> tags.")

    api_paths = [
        "/openapi.json", "/openapi.yaml", "/swagger.json",
        "/api-docs", "/api/v1", "/graphql",
    ]
    api_found = False
    for path in api_paths:
        api_url = urljoin(base_url, path)
        api_resp = fetch(api_url, timeout=5)
        if api_resp and api_resp.status_code == 200:
            print(f"  [{PASS}] Machine-readable endpoint found: {path}")
            api_found = True
            ao_score += 1.5
            break
    if not api_found:
        print(f"  [{INFO}] No public API endpoints found — optional, but helps AI systems access structured data")

    track_score("AI Optimization", min(ao_score, 5), 5)


# ---------------------------------------------------------------------------
# 14. Social Signals
# ---------------------------------------------------------------------------
def check_social_signals(base_url):
    """Check for social media presence signals that help AI entity recognition."""
    print("\n--- Social Signals ---")
    resp, soup = get_soup(base_url)
    if not soup:
        print(f"  [{FAIL}] Could not fetch homepage")
        track_score("Social Signals", 0, 3)
        return

    ss_score = 0

    # Twitter/X card meta tags
    twitter_tags = soup.find_all("meta", attrs={"name": re.compile(r"^twitter:", re.IGNORECASE)})
    if not twitter_tags:
        twitter_tags = soup.find_all("meta", property=re.compile(r"^twitter:", re.IGNORECASE))
    if twitter_tags:
        tw_types = [t.get("name") or t.get("property") for t in twitter_tags]
        print(f"  [{PASS}] Twitter/X card tags found: {', '.join(tw_types)}")
        ss_score += 1
    else:
        print(f"  [{WARN}] No Twitter/X card meta tags found")
        fix("Add Twitter card tags to your <head>:\n  <meta name=\"twitter:card\" content=\"summary_large_image\" />\n  <meta name=\"twitter:site\" content=\"@yourhandle\" />\n  <meta name=\"twitter:title\" content=\"Page Title\" />\n  <meta name=\"twitter:description\" content=\"Page description\" />\n  <meta name=\"twitter:image\" content=\"https://yoursite.com/image.jpg\" />")

    # sameAs links in JSON-LD (social profiles for entity disambiguation)
    same_as_links = []
    json_ld_scripts = soup.find_all("script", type="application/ld+json")
    for script in json_ld_scripts:
        try:
            data = json.loads(script.string)
            if isinstance(data, dict):
                sa = data.get("sameAs", [])
                if isinstance(sa, str):
                    same_as_links.append(sa)
                elif isinstance(sa, list):
                    same_as_links.extend(sa)
                for item in data.get("@graph", []):
                    if isinstance(item, dict):
                        sa = item.get("sameAs", [])
                        if isinstance(sa, str):
                            same_as_links.append(sa)
                        elif isinstance(sa, list):
                            same_as_links.extend(sa)
        except (json.JSONDecodeError, TypeError):
            pass

    if same_as_links:
        print(f"  [{PASS}] sameAs social links in JSON-LD ({len(same_as_links)}):")
        ss_score += 2
        for link in same_as_links[:5]:
            print(f"         {link}")
    else:
        print(f"  [{WARN}] No sameAs social profile links in structured data")
        fix("Add sameAs to your Organization JSON-LD to connect your social profiles:\n  \"sameAs\": [\n    \"https://twitter.com/yourbrand\",\n    \"https://linkedin.com/company/yourbrand\",\n    \"https://github.com/yourbrand\",\n    \"https://facebook.com/yourbrand\"\n  ]\nThis helps AI engines confirm your entity identity across platforms.")

    # Check for social profile links in HTML (fallback)
    if not same_as_links:
        social_domains = ["twitter.com", "x.com", "linkedin.com", "facebook.com",
                          "instagram.com", "youtube.com", "github.com", "tiktok.com"]
        social_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            for domain in social_domains:
                if domain in href:
                    social_links.append(href)
                    break
        if social_links:
            print(f"  [{INFO}] {len(social_links)} social profile link(s) found in HTML — consider adding them as sameAs in JSON-LD too")
        else:
            print(f"  [{INFO}] No social profile links detected on the page")

    track_score("Social Signals", min(ss_score, 3), 3)


# ---------------------------------------------------------------------------
# 15. AI Answer Format Optimization
# ---------------------------------------------------------------------------
def check_ai_answer_formats(base_url):
    """Check for content patterns that AI engines prefer to cite."""
    print("\n--- AI Answer Format Optimization ---")
    resp, soup = get_soup(base_url)
    if not soup:
        print(f"  [{FAIL}] Could not fetch homepage")
        track_score("AI Answer Formats", 0, 5)
        return

    text = get_text_content(soup)
    score = 0
    total_checks = 6

    # 1. Definition sentences ("X is...", "X refers to...")
    definition_patterns = re.findall(
        r'(?:^|\.\s+)([A-Z][^.]{5,60}?\s+(?:is|are|refers to|means|describes)\s+[^.]{10,}\.)',
        text
    )
    if definition_patterns:
        score += 1
        print(f"  [{PASS}] {len(definition_patterns)} definition-style sentence(s) found — highly citable by AI")
    else:
        print(f"  [{WARN}] No definition-style sentences detected")
        fix("Add clear definition sentences that AI engines can directly quote:\n  'Generative Engine Optimization (GEO) is the practice of optimizing web content...'\n  'A sitemap refers to a file that lists all pages on a website...'\nPattern: '[Term] is/are [clear definition].'")

    # 2. Comparison tables
    tables = soup.find_all("table")
    has_comparison_table = False
    for table in tables:
        headers = table.find_all("th")
        if len(headers) >= 2:
            has_comparison_table = True
            break
    if has_comparison_table:
        score += 1
        print(f"  [{PASS}] Comparison table(s) with headers found — AI engines extract tabular data")
    else:
        if tables:
            print(f"  [{WARN}] Tables found but missing <th> headers — add headers for AI extraction")
            fix("Add proper headers to your tables:\n  <table>\n    <thead><tr><th>Feature</th><th>Plan A</th><th>Plan B</th></tr></thead>\n    <tbody><tr><td>Price</td><td>$10</td><td>$20</td></tr></tbody>\n  </table>\nAI engines extract well-structured tables for comparison answers.")
        else:
            print(f"  [{INFO}] No comparison tables — consider adding tables for feature comparisons, pricing, etc.")
            fix("Add comparison tables where applicable (pricing, features, vs. competitors):\n  <table>\n    <thead><tr><th>Feature</th><th>Basic</th><th>Pro</th></tr></thead>\n    <tbody>...</tbody>\n  </table>\nAI engines frequently cite tabular data in comparison answers.")

    # 3. Numbered step-by-step instructions
    ordered_lists = soup.find_all("ol")
    has_steps = False
    for ol in ordered_lists:
        items = ol.find_all("li")
        if len(items) >= 3:
            has_steps = True
            break
    # Also check for "Step 1", "Step 2" patterns in headings
    step_headings = [h for h in soup.find_all(re.compile(r"^h[1-6]$"))
                     if re.search(r'step\s+\d|^\d+[\.\)]\s', h.get_text(strip=True), re.IGNORECASE)]
    if has_steps or step_headings:
        score += 1
        print(f"  [{PASS}] Step-by-step instructional content detected — great for 'how to' AI answers")
    else:
        print(f"  [{INFO}] No step-by-step instructions found")
        fix("Add numbered how-to instructions where relevant:\n  <h2>How to Set Up Your Account</h2>\n  <ol>\n    <li>Go to the signup page</li>\n    <li>Enter your email address</li>\n    <li>Verify your account</li>\n  </ol>\nAI engines surface step-by-step content for 'how to' queries.")

    # 4. Pros and cons / advantages and disadvantages
    pros_cons_patterns = re.findall(
        r'(?:pros?\s+(?:and|&)\s+cons?|advantages?\s+(?:and|&)\s+disadvantages?|benefits?\s+(?:and|&)\s+drawbacks?)',
        text, re.IGNORECASE
    )
    pros_cons_elements = soup.find_all(class_=re.compile(r"pros?|cons?|advantage|disadvantage", re.IGNORECASE))
    if pros_cons_patterns or pros_cons_elements:
        score += 1
        print(f"  [{PASS}] Pros/cons or advantages/disadvantages content detected")
    else:
        print(f"  [{INFO}] No pros/cons pattern detected")
        fix("Add pros and cons sections for products, services, or comparisons:\n  <h3>Pros</h3>\n  <ul><li>Fast performance</li><li>Easy to use</li></ul>\n  <h3>Cons</h3>\n  <ul><li>Limited free tier</li><li>No mobile app</li></ul>\nAI engines frequently cite balanced pros/cons in recommendation answers.")

    # 5. Key takeaways / TL;DR / summary sections
    summary_indicators = soup.find_all(
        re.compile(r"^h[1-6]$"),
        string=re.compile(r"key\s+takeaway|tl;?\s*dr|summary|in\s+(?:a\s+)?nutshell|bottom\s+line|conclusion", re.IGNORECASE)
    )
    summary_classes = soup.find_all(class_=re.compile(r"takeaway|tldr|summary|highlight", re.IGNORECASE))
    if summary_indicators or summary_classes:
        score += 1
        print(f"  [{PASS}] Summary/key takeaways section found — AI engines prefer concise summaries")
    else:
        print(f"  [{INFO}] No key takeaways or TL;DR section found")
        fix("Add a 'Key Takeaways' or 'TL;DR' section near the top or bottom:\n  <h2>Key Takeaways</h2>\n  <ul>\n    <li>Main point 1</li>\n    <li>Main point 2</li>\n  </ul>\nAI engines often pull from summary sections for quick answers.")

    # 6. Conversational question-pattern headings (who/what/how/why/when/where/is/can/does)
    question_word_re = re.compile(
        r"^\s*(?:who|what|how|why|when|where|is|are|can|does|do|should|will|which|whose|whom)\b",
        re.IGNORECASE,
    )
    headings_all = soup.find_all(re.compile(r"^h[1-6]$"))
    q_headings = []
    for h in headings_all:
        txt = h.get_text(strip=True)
        if not txt:
            continue
        if question_word_re.match(txt) or txt.rstrip().endswith("?"):
            q_headings.append(txt)
    if len(q_headings) >= 3:
        score += 1
        print(f"  [{PASS}] {len(q_headings)} question-pattern heading(s) — strong conversational readiness")
        for qh in q_headings[:3]:
            print(f"         \"{qh[:70]}\"")
    elif q_headings:
        print(f"  [{INFO}] Only {len(q_headings)} question-pattern heading(s) — add more for chat-style queries")
        fix("Add more question-pattern headings that match how people prompt AI engines:\n"
            "  <h2>What is GEO?</h2>\n"
            "  <h2>How do I optimize for AI search?</h2>\n"
            "  <h2>Why does GEO matter?</h2>\n"
            "Follow each with a short, direct answer so AI engines can extract it.")
    else:
        print(f"  [{WARN}] No question-pattern headings detected — low conversational readiness")
        fix("Add question-pattern headings so AI engines can match chat-style queries to your content:\n"
            "  <h2>What is GEO?</h2>\n"
            "  <h3>How does this work?</h3>\n"
            "Pages structured around who/what/how/why questions rank higher in AI answers.")

    print(f"\n  AI answer format score: {score}/{total_checks}")
    track_score("AI Answer Formats", score, total_checks)


# ---------------------------------------------------------------------------
# 16. Schema Breadcrumbs & Knowledge Panel Readiness
# ---------------------------------------------------------------------------
def check_schema_knowledge(base_url):
    """Check for BreadcrumbList schema and knowledge panel readiness."""
    print("\n--- Schema Breadcrumbs & Knowledge Panel ---")
    resp, soup = get_soup(base_url)
    if not soup:
        print(f"  [{FAIL}] Could not fetch homepage")
        track_score("Schema & Knowledge", 0, 4)
        return

    sk_score = 0

    json_ld_scripts = soup.find_all("script", type="application/ld+json")
    all_types = []
    org_data = None

    for script in json_ld_scripts:
        try:
            data = json.loads(script.string)
            items = [data] if isinstance(data, dict) else data if isinstance(data, list) else []
            # Also check @graph
            if isinstance(data, dict) and "@graph" in data:
                items.extend(data["@graph"])
            for item in items:
                if not isinstance(item, dict):
                    continue
                t = item.get("@type", "")
                if isinstance(t, list):
                    all_types.extend(t)
                else:
                    all_types.append(t)
                if t in ("Organization", "LocalBusiness", "Corporation"):
                    org_data = item
        except (json.JSONDecodeError, TypeError):
            pass

    # Breadcrumbs
    if "BreadcrumbList" in all_types:
        print(f"  [{PASS}] BreadcrumbList schema found — helps AI engines understand site hierarchy")
        sk_score += 1.5
    else:
        # Check for HTML breadcrumb nav
        breadcrumb_nav = soup.find(attrs={"aria-label": re.compile(r"breadcrumb", re.IGNORECASE)})
        breadcrumb_class = soup.find(class_=re.compile(r"breadcrumb", re.IGNORECASE))
        if breadcrumb_nav or breadcrumb_class:
            print(f"  [{WARN}] HTML breadcrumb navigation found but no BreadcrumbList schema")
            fix("Add BreadcrumbList structured data to match your HTML breadcrumbs:\n  <script type=\"application/ld+json\">\n  {\n    \"@context\": \"https://schema.org\",\n    \"@type\": \"BreadcrumbList\",\n    \"itemListElement\": [\n      {\"@type\": \"ListItem\", \"position\": 1, \"name\": \"Home\", \"item\": \"https://yoursite.com\"},\n      {\"@type\": \"ListItem\", \"position\": 2, \"name\": \"Products\", \"item\": \"https://yoursite.com/products\"}\n    ]\n  }\n  </script>")
        else:
            print(f"  [{INFO}] No breadcrumb navigation or schema found")
            fix("Add breadcrumb navigation to help AI engines understand your site structure:\n  1. Add visible breadcrumbs: Home > Category > Page\n  2. Add BreadcrumbList JSON-LD schema to match")

    # Knowledge panel readiness — check Organization/LocalBusiness completeness
    if org_data:
        print(f"  [{PASS}] Organization/Business schema found: @type = {org_data.get('@type')}")
        sk_score += 1
        required_fields = {
            "name": "Organization name",
            "url": "Website URL",
            "logo": "Logo image",
            "description": "Description",
        }
        optional_fields = {
            "address": "Physical address",
            "telephone": "Phone number",
            "email": "Email contact",
            "foundingDate": "Founding date",
            "sameAs": "Social profiles",
            "contactPoint": "Contact point",
        }

        for field, label in required_fields.items():
            if org_data.get(field):
                print(f"  [{PASS}] {label}: present")
                sk_score += 0.375  # 4 fields * 0.375 = 1.5 pts max
            else:
                print(f"  [{WARN}] {label}: missing")
                fix(f"Add \"{field}\" to your Organization JSON-LD to improve knowledge panel eligibility.")

        present_optional = [label for field, label in optional_fields.items() if org_data.get(field)]
        missing_optional = [label for field, label in optional_fields.items() if not org_data.get(field)]
        if present_optional:
            print(f"  [{PASS}] Optional fields present: {', '.join(present_optional)}")
        if missing_optional:
            print(f"  [{INFO}] Optional fields missing: {', '.join(missing_optional)}")
            fix("Add more fields to strengthen knowledge panel eligibility:\n  \"address\": {\"@type\": \"PostalAddress\", \"streetAddress\": \"...\", \"addressLocality\": \"...\"},\n  \"telephone\": \"+1-xxx-xxx-xxxx\",\n  \"foundingDate\": \"2020\",\n  \"sameAs\": [\"https://twitter.com/...\", \"https://linkedin.com/...\"]")
    else:
        print(f"  [{WARN}] No Organization/LocalBusiness schema found — needed for knowledge panels")
        fix("Add Organization structured data for knowledge panel eligibility:\n  <script type=\"application/ld+json\">\n  {\n    \"@context\": \"https://schema.org\",\n    \"@type\": \"Organization\",\n    \"name\": \"Your Company\",\n    \"url\": \"https://yoursite.com\",\n    \"logo\": \"https://yoursite.com/logo.png\",\n    \"description\": \"What your company does\",\n    \"sameAs\": [\"https://twitter.com/you\", \"https://linkedin.com/company/you\"]\n  }\n  </script>")

    track_score("Schema & Knowledge", min(sk_score, 4), 4)


# ---------------------------------------------------------------------------
# 17. Mobile-Friendliness & Page Weight
# ---------------------------------------------------------------------------
def check_mobile_and_weight(base_url):
    """Check mobile-friendliness signals and page weight."""
    print("\n--- Mobile-Friendliness & Page Weight ---")
    resp, soup = get_soup(base_url)
    if not soup:
        print(f"  [{FAIL}] Could not fetch homepage")
        track_score("Mobile & Weight", 0, 4)
        return

    mw_score = 0

    # Viewport meta tag
    viewport = soup.find("meta", attrs={"name": "viewport"})
    if viewport and viewport.get("content"):
        content = viewport["content"]
        print(f"  [{PASS}] Viewport meta tag found: {content[:80]}")
        if "width=device-width" in content:
            print(f"  [{PASS}] Uses width=device-width (responsive)")
            mw_score += 1
        else:
            print(f"  [{WARN}] Viewport doesn't use width=device-width")
            fix("Set viewport to responsive:\n  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />")
    else:
        print(f"  [{FAIL}] No viewport meta tag — page won't render properly on mobile")
        fix("Add a viewport meta tag to your <head>:\n  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />\nMobile-first indexing means AI crawlers expect mobile-friendly pages.")

    # Page weight
    html_size = len(resp.text.encode("utf-8"))
    html_kb = html_size / 1024
    if html_kb < 100:
        print(f"  [{PASS}] HTML page weight: {html_kb:.0f} KB (lightweight)")
        mw_score += 1
    elif html_kb < 500:
        print(f"  [{WARN}] HTML page weight: {html_kb:.0f} KB — consider reducing inline CSS/JS")
        fix("Reduce page weight:\n  1. Move inline CSS to external stylesheets\n  2. Move inline JS to external scripts with defer/async\n  3. Remove unused HTML/comments\n  4. Enable server-side compression (gzip/brotli)")
    else:
        print(f"  [{FAIL}] HTML page weight: {html_kb:.0f} KB — very heavy, may slow AI crawlers")
        fix("Page is too heavy for efficient crawling. Actions:\n  1. Externalize all inline CSS and JavaScript\n  2. Remove inline SVGs and base64 images — use external files\n  3. Enable gzip/brotli compression on your server\n  4. Consider code-splitting for JavaScript-heavy pages")

    # Count inline resources
    inline_styles = soup.find_all("style")
    inline_scripts = soup.find_all("script", src=False)
    inline_scripts = [s for s in inline_scripts if s.string and len(s.string.strip()) > 100 and s.get("type") != "application/ld+json"]

    if len(inline_styles) > 3 or len(inline_scripts) > 5:
        print(f"  [{WARN}] Heavy inline resources: {len(inline_styles)} <style> blocks, {len(inline_scripts)} large <script> blocks")
        fix("Move inline styles and scripts to external files to reduce HTML weight\nand improve caching for repeat crawls.")
    else:
        print(f"  [{PASS}] Inline resources within acceptable range")
        mw_score += 1

    # Cache headers
    cache_control = resp.headers.get("Cache-Control", "")
    etag = resp.headers.get("ETag", "")
    last_modified = resp.headers.get("Last-Modified", "")

    cache_signals = []
    if cache_control:
        cache_signals.append(f"Cache-Control: {cache_control}")
    if etag:
        cache_signals.append(f"ETag: {etag[:40]}")
    if last_modified:
        cache_signals.append(f"Last-Modified: {last_modified}")

    if cache_signals:
        print(f"  [{PASS}] Cache headers found: {'; '.join(cache_signals[:2])}")
        mw_score += 1
    else:
        print(f"  [{WARN}] No cache headers (Cache-Control, ETag, Last-Modified)")
        fix("Add cache headers for efficient re-crawling:\n  Cache-Control: public, max-age=3600\n  ETag: (auto-generated by most servers)\nThis allows AI crawlers to use conditional requests (If-None-Match)\nand avoid re-downloading unchanged pages.")

    track_score("Mobile & Weight", mw_score, 4)


# ---------------------------------------------------------------------------
# 18. URL Normalization
# ---------------------------------------------------------------------------
def check_url_normalization(base_url):
    """Check for URL consistency (www vs non-www, trailing slashes, etc.)."""
    print("\n--- URL Normalization ---")
    un_score = 0

    parsed = urlparse(base_url)
    hostname = parsed.netloc

    # www vs non-www
    if hostname.startswith("www."):
        alt_host = hostname[4:]
        alt_url = base_url.replace(f"www.{alt_host}", alt_host, 1)
    else:
        alt_host = f"www.{hostname}"
        alt_url = base_url.replace(hostname, alt_host, 1)

    try:
        alt_resp = requests.get(alt_url, allow_redirects=True, timeout=10, headers={
            "User-Agent": "GEO-Readiness-Checker/1.0"
        })
        final_url = alt_resp.url.rstrip("/")
        base_stripped = base_url.rstrip("/")

        if final_url == base_stripped or final_url == base_stripped + "/":
            print(f"  [{PASS}] {alt_host} redirects to {hostname} (consistent)")
            un_score += 1
        elif alt_resp.status_code == 200:
            print(f"  [{WARN}] Both {hostname} and {alt_host} serve content — duplicate content risk")
            fix(f"Set up a 301 redirect so one version redirects to the other:\n  # Nginx: redirect www to non-www\n  server {{ server_name www.{parsed.netloc.replace('www.', '')}; return 301 https://{parsed.netloc.replace('www.', '')}$request_uri; }}\nThen set the canonical URL to match the preferred version.")
        else:
            print(f"  [{PASS}] Alternate hostname ({alt_host}) is not accessible")
            un_score += 1
    except requests.RequestException:
        print(f"  [{PASS}] Alternate hostname ({alt_host}) is not accessible")
        un_score += 1

    # Trailing slash consistency
    test_path = base_url.rstrip("/")
    test_path_slash = test_path + "/"
    try:
        resp_no_slash = requests.get(test_path, allow_redirects=False, timeout=5, headers={
            "User-Agent": "GEO-Readiness-Checker/1.0"
        })
        resp_slash = requests.get(test_path_slash, allow_redirects=False, timeout=5, headers={
            "User-Agent": "GEO-Readiness-Checker/1.0"
        })

        if resp_no_slash.status_code == resp_slash.status_code == 200:
            print(f"  [{INFO}] Both trailing slash and non-trailing slash return 200 — ensure canonical is set")
        elif resp_no_slash.is_redirect or resp_slash.is_redirect:
            print(f"  [{PASS}] Trailing slash consistency handled via redirect")
            un_score += 0.5
        else:
            print(f"  [{PASS}] URL paths are consistent")
            un_score += 0.5
    except requests.RequestException:
        pass

    # Mixed case check
    upper_url = base_url.upper()
    if upper_url != base_url:
        try:
            upper_resp = requests.get(upper_url, allow_redirects=True, timeout=5, headers={
                "User-Agent": "GEO-Readiness-Checker/1.0"
            })
            if upper_resp.status_code == 200 and upper_resp.url.rstrip("/") != base_url.rstrip("/"):
                print(f"  [{WARN}] Mixed case URLs resolve to different pages — can cause duplicate content")
                fix("Ensure your server normalizes URL case (lowercase). In nginx:\n  location ~ [A-Z] { rewrite ^(.*)$ $scheme://$host$uri_lowercase permanent; }")
            else:
                print(f"  [{PASS}] URL case handling is consistent")
                un_score += 0.5
        except requests.RequestException:
            pass

    track_score("URL Normalization", min(un_score, 2), 2)


# ---------------------------------------------------------------------------
# 19. Outbound Link Quality & Media Schema
# ---------------------------------------------------------------------------
def check_outbound_and_media(base_url):
    """Check outbound link quality and video/media structured data."""
    print("\n--- Outbound Links & Media ---")
    resp, soup = get_soup(base_url)
    if not soup:
        print(f"  [{FAIL}] Could not fetch homepage")
        track_score("Outbound & Media", 0, 3)
        return

    om_score = 0

    # Outbound link analysis
    parsed_base = urlparse(base_url)
    links = soup.find_all("a", href=True)
    outbound_links = []
    for link in links:
        href = link["href"]
        parsed_href = urlparse(urljoin(base_url, href))
        if parsed_href.netloc and parsed_href.netloc != parsed_base.netloc:
            outbound_links.append(parsed_href.netloc)

    if outbound_links:
        unique_domains = list(dict.fromkeys(outbound_links))
        authoritative_domains = [d for d in unique_domains if any(
            auth in d for auth in [".gov", ".edu", ".org", "wikipedia", "scholar.google",
                                    "nature.com", "ieee.org", "arxiv.org", "ncbi.nlm.nih"]
        )]
        print(f"  [{PASS}] {len(outbound_links)} outbound link(s) to {len(unique_domains)} unique domain(s)")
        om_score += 0.5
        if authoritative_domains:
            print(f"  [{PASS}] Links to authoritative sources: {', '.join(authoritative_domains[:5])}")
            om_score += 0.5
        else:
            print(f"  [{INFO}] No links to .gov/.edu/.org authoritative sources detected")
            fix("Link to authoritative external sources where relevant (research papers, .gov/.edu sites,\nindustry standards). Outbound links to reputable sources signal well-researched content to AI engines.")
    else:
        print(f"  [{INFO}] No outbound links found — linking to authoritative sources increases content trust")
        fix("Add outbound links to reputable, authoritative sources that support your claims.\nAI engines see this as a signal of well-researched, trustworthy content.")

    # Video / media schema
    json_ld_scripts = soup.find_all("script", type="application/ld+json")
    has_video_schema = False
    for script in json_ld_scripts:
        try:
            data = json.loads(script.string)
            items = [data] if isinstance(data, dict) else data if isinstance(data, list) else []
            if isinstance(data, dict) and "@graph" in data:
                items.extend(data["@graph"])
            for item in items:
                if isinstance(item, dict) and item.get("@type") in ("VideoObject", "AudioObject", "MediaObject"):
                    has_video_schema = True
        except (json.JSONDecodeError, TypeError):
            pass

    # Check for video embeds
    videos = soup.find_all(["video", "iframe"])
    video_embeds = [v for v in videos if v.name == "video" or
                    (v.get("src") and any(p in v.get("src", "") for p in ["youtube", "vimeo", "wistia"]))]

    if has_video_schema:
        print(f"  [{PASS}] VideoObject structured data found")
        om_score += 0.5
    elif video_embeds:
        print(f"  [{WARN}] Video content found ({len(video_embeds)} embed(s)) but no VideoObject schema")
        fix("Add VideoObject structured data for your video content:\n  <script type=\"application/ld+json\">\n  {\n    \"@context\": \"https://schema.org\",\n    \"@type\": \"VideoObject\",\n    \"name\": \"Video Title\",\n    \"description\": \"Video description\",\n    \"thumbnailUrl\": \"https://yoursite.com/thumb.jpg\",\n    \"uploadDate\": \"2025-01-15\",\n    \"contentUrl\": \"https://yoursite.com/video.mp4\"\n  }\n  </script>")
    else:
        print(f"  [{INFO}] No video content detected")

    # Check for video transcripts
    if video_embeds:
        transcript_indicators = soup.find_all(class_=re.compile(r"transcript", re.IGNORECASE))
        transcript_indicators += soup.find_all(id=re.compile(r"transcript", re.IGNORECASE))
        if transcript_indicators:
            print(f"  [{PASS}] Video transcript section found — AI engines can index transcript text")
        else:
            print(f"  [{WARN}] Videos found but no transcript detected")
            fix("Add text transcripts for video content so AI crawlers can index the spoken content.\nPlace the transcript in a visible section below the video.")

    # Multi-format coverage: podcast, PDF, infographic, slides
    formats_found = set()
    if video_embeds or has_video_schema:
        formats_found.add("video")

    # Podcast detection: audio elements, podcast RSS, common host links
    audio_tags = soup.find_all("audio")
    podcast_hosts = ["anchor.fm", "spotify.com/show", "podcasts.apple.com",
                     "soundcloud.com", "buzzsprout.com", "transistor.fm",
                     "libsyn.com", "simplecast.com"]
    podcast_link = False
    for a in soup.find_all("a", href=True):
        href = a["href"].lower()
        for h in podcast_hosts:
            if h in href:
                podcast_link = True
                break
        if podcast_link:
            break
    podcast_schema = False
    for script in json_ld_scripts:
        try:
            data = json.loads(script.string)
            s = json.dumps(data).lower()
            if '"podcastseries"' in s or '"podcastepisode"' in s:
                podcast_schema = True
                break
        except (json.JSONDecodeError, TypeError):
            pass
    if audio_tags or podcast_link or podcast_schema:
        formats_found.add("podcast/audio")

    # PDFs
    pdf_links = [a["href"] for a in soup.find_all("a", href=True) if a["href"].lower().endswith(".pdf")]
    if pdf_links:
        formats_found.add("PDF")

    # Infographics: images with "infographic" in alt/src, or large standalone graphics
    infographic_imgs = []
    for img in soup.find_all("img"):
        alt = (img.get("alt") or "").lower()
        src = (img.get("src") or "").lower()
        if "infographic" in alt or "infographic" in src or "diagram" in alt or "chart" in alt:
            infographic_imgs.append(img)
    if infographic_imgs:
        formats_found.add("infographic")

    # Slides / presentations
    slide_hosts = ["slideshare.net", "speakerdeck.com", "slides.com"]
    for a in soup.find_all("a", href=True):
        href = a["href"].lower()
        if any(h in href for h in slide_hosts):
            formats_found.add("slides")
            break

    print(f"  [{INFO}] Multi-format coverage: {', '.join(sorted(formats_found)) or 'text only'}")
    if len(formats_found) >= 3:
        print(f"  [{PASS}] {len(formats_found)} content format(s) — broad AI surface area")
        om_score += 0.5
    elif len(formats_found) >= 1:
        print(f"  [{INFO}] Only {len(formats_found)} non-text format(s) detected — more formats = more AI surface area")
        fix("Diversify your content formats so AI engines encounter you in more contexts:\n"
            "  • Podcast (audio transcripts feed ChatGPT, Perplexity)\n"
            "  • PDF whitepapers (citable documents)\n"
            "  • Infographics with descriptive alt text\n"
            "  • Slides on SlideShare / Speaker Deck\n"
            "  • Video with transcripts")
    else:
        print(f"  [{WARN}] No non-text formats detected — content is text-only")
        fix("Add at least one alternative format (video with transcript, podcast, PDF, or infographic).\n"
            "Each format opens a new retrieval channel for AI engines.")

    # Table markup quality
    tables = soup.find_all("table")
    if tables:
        well_formed = 0
        for table in tables:
            has_thead = bool(table.find("thead"))
            has_th = bool(table.find("th"))
            if has_thead and has_th:
                well_formed += 1
        if well_formed == len(tables):
            print(f"  [{PASS}] {len(tables)} table(s) with proper <thead>/<th> markup")
            om_score += 0.5
        elif well_formed > 0:
            print(f"  [{WARN}] {well_formed}/{len(tables)} tables have proper headers — fix the rest")
            fix("Add <thead> and <th> to all data tables:\n  <table>\n    <thead><tr><th>Column 1</th><th>Column 2</th></tr></thead>\n    <tbody><tr><td>Data</td><td>Data</td></tr></tbody>\n  </table>")
        else:
            print(f"  [{WARN}] {len(tables)} table(s) but none have proper <thead>/<th> headers")
            fix("Add semantic headers to your tables for AI extraction:\n  <table>\n    <thead><tr><th>Header 1</th><th>Header 2</th></tr></thead>\n    <tbody>...</tbody>\n  </table>")
    else:
        print(f"  [{INFO}] No tables found on homepage")

    # Definition elements
    dfn_tags = soup.find_all("dfn")
    abbr_tags = soup.find_all("abbr")
    if dfn_tags or abbr_tags:
        print(f"  [{PASS}] Definition markup found: {len(dfn_tags)} <dfn>, {len(abbr_tags)} <abbr> tags")
        om_score += 0.5
    else:
        print(f"  [{INFO}] No <dfn> or <abbr> tags — use these to mark up technical terms and abbreviations")
        fix("Mark up key terms and abbreviations:\n  <dfn>Generative Engine Optimization</dfn> (GEO) is...\n  <abbr title=\"Generative Engine Optimization\">GEO</abbr>\nThis helps AI engines understand and define terms in your content.")

    # First-paragraph extractability — AI engines preferentially pull facts from the top
    main = soup.find("main") or soup.find("article") or soup.find("body")
    first_para = None
    if main:
        for p in main.find_all("p"):
            t = p.get_text(strip=True)
            if len(t.split()) >= 15:
                first_para = t
                break
    if first_para:
        has_definition = bool(re.search(r"\b(is|are|means|refers to|describes)\b", first_para, re.IGNORECASE))
        has_stat = bool(re.search(r"\d+(?:\.\d+)?%|\$\d+|\d{1,3}(?:,\d{3})+|\b\d{4}\b", first_para))
        wc = len(first_para.split())
        facts = []
        if has_definition:
            facts.append("definition")
        if has_stat:
            facts.append("statistic/number")
        if 25 <= wc <= 120 and facts:
            print(f"  [{PASS}] First paragraph ({wc} words) contains extractable facts: {', '.join(facts)}")
            om_score += 0.5
        elif facts:
            print(f"  [{INFO}] First paragraph has facts ({', '.join(facts)}) but is {wc} words — aim for 25-120")
            fix("Tighten your opening paragraph to 25-120 words so AI engines can lift it as a snippet.")
        else:
            print(f"  [{WARN}] First paragraph ({wc} words) lacks extractable facts — add a definition or key statistic up front")
            fix("Front-load facts into your first paragraph so AI engines can extract it directly:\n"
                "  'GEO is the practice of optimizing content for AI-powered search engines.\n"
                "   Over 70% of search users now consult an AI assistant before clicking a link.'\n"
                "Aim for one definition-style sentence and one concrete stat in the first 25-120 words.")
    else:
        print(f"  [{INFO}] Could not identify a substantive first paragraph — AI engines rely on early content for extraction")
        fix("Place a substantive opening paragraph high in the page body (inside <main> or <article>)\nthat answers 'what is this about?' with a definition and/or a concrete number.")

    track_score("Outbound & Media", min(om_score, 3), 3)


# ---------------------------------------------------------------------------
# 20. Multilingual Content Depth
# ---------------------------------------------------------------------------
def check_multilingual_depth(base_url):
    """Check if alternate language pages actually exist and have content."""
    print("\n--- Multilingual Content Depth ---")
    resp, soup = get_soup(base_url)
    if not soup:
        print(f"  [{FAIL}] Could not fetch homepage")
        return

    hreflangs = soup.find_all("link", rel="alternate", hreflang=True)
    if not hreflangs:
        print(f"  [{INFO}] No hreflang tags — skipping multilingual check")
        return

    print(f"  Found {len(hreflangs)} hreflang tag(s), checking content depth...\n")

    thin_pages = []
    broken_pages = []
    good_pages = []

    for tag in hreflangs[:8]:  # Limit to 8 to avoid too many requests
        lang = tag.get("hreflang", "?")
        href = urljoin(base_url, tag.get("href", ""))

        if href.rstrip("/") == base_url.rstrip("/"):
            continue  # Skip self-reference

        alt_resp = fetch(href, timeout=10)
        if not alt_resp or alt_resp.status_code != 200:
            broken_pages.append((lang, href))
            continue

        alt_soup = BeautifulSoup(alt_resp.text, "html.parser")
        alt_text = get_text_content(alt_soup)
        word_count = len(alt_text.split())

        if word_count < 50:
            thin_pages.append((lang, href, word_count))
        else:
            good_pages.append((lang, word_count))

    if good_pages:
        for lang, wc in good_pages:
            print(f"  [{PASS}] [{lang}] has substantive content ({wc} words)")

    if thin_pages:
        for lang, href, wc in thin_pages:
            print(f"  [{WARN}] [{lang}] has very thin content ({wc} words): {href}")
        fix("Alternate language pages have too little content. Ensure translations are complete\nand not just stubs or machine-translated snippets. AI engines may skip thin multilingual pages.")

    if broken_pages:
        for lang, href in broken_pages:
            print(f"  [{FAIL}] [{lang}] page is broken or inaccessible: {href}")
        fix("Fix broken hreflang URLs — they return errors. Either create the page\nor remove the hreflang tag to avoid confusing AI crawlers.")

    if not thin_pages and not broken_pages and good_pages:
        print(f"  [{PASS}] All alternate language pages have substantive content")
        track_score("Multilingual", 2, 2)
    elif good_pages and not broken_pages:
        track_score("Multilingual", 1, 2)
    elif good_pages:
        track_score("Multilingual", 0.5, 2)
    else:
        track_score("Multilingual", 0, 2)


# ---------------------------------------------------------------------------
# 21. Cross-Platform Content Distribution
# ---------------------------------------------------------------------------
def check_cross_platform(base_url):
    """Check if the brand has presence on major social/content platforms that AI models train on."""
    print("\n--- Cross-Platform Content Distribution ---")
    resp, soup = get_soup(base_url)

    parsed = urlparse(base_url)
    domain = parsed.netloc.replace("www.", "")
    brand = domain.split(".")[0]

    # Platform definitions: name -> (url_patterns_to_check, on_page_signal_domains)
    platforms = {
        "X / Twitter":  {
            "probe_urls": [f"https://x.com/{brand}", f"https://twitter.com/{brand}"],
            "link_domains": ["x.com", "twitter.com"],
            "meta_signal": "twitter:site",
        },
        "LinkedIn":     {
            "probe_urls": [f"https://www.linkedin.com/company/{brand}"],
            "link_domains": ["linkedin.com"],
        },
        "YouTube":      {
            "probe_urls": [f"https://www.youtube.com/@{brand}", f"https://www.youtube.com/c/{brand}"],
            "link_domains": ["youtube.com"],
        },
        "GitHub":       {
            "probe_urls": [f"https://github.com/{brand}"],
            "link_domains": ["github.com"],
        },
        "Reddit":       {
            "probe_urls": [f"https://www.reddit.com/r/{brand}", f"https://www.reddit.com/user/{brand}"],
            "link_domains": ["reddit.com"],
        },
        "Facebook":     {
            "probe_urls": [f"https://www.facebook.com/{brand}"],
            "link_domains": ["facebook.com"],
        },
        "Instagram":    {
            "probe_urls": [f"https://www.instagram.com/{brand}"],
            "link_domains": ["instagram.com"],
        },
        "Medium":       {
            "probe_urls": [f"https://medium.com/@{brand}", f"https://{brand}.medium.com"],
            "link_domains": ["medium.com"],
        },
        "TikTok":       {
            "probe_urls": [f"https://www.tiktok.com/@{brand}"],
            "link_domains": ["tiktok.com"],
        },
        "Quora":        {
            "probe_urls": [f"https://www.quora.com/profile/{brand}"],
            "link_domains": ["quora.com"],
        },
    }

    # --- Phase 1: Gather on-page signals ---
    on_page_links = {}   # platform_name -> url found on page
    same_as_links = []

    if soup:
        # Collect all sameAs from JSON-LD
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                items = [data] if isinstance(data, dict) else data if isinstance(data, list) else []
                if isinstance(data, dict) and "@graph" in data:
                    items.extend(data["@graph"])
                for item in items:
                    if isinstance(item, dict):
                        sa = item.get("sameAs", [])
                        if isinstance(sa, str):
                            same_as_links.append(sa)
                        elif isinstance(sa, list):
                            same_as_links.extend(sa)
            except (json.JSONDecodeError, TypeError):
                pass

        # Collect all outbound links
        all_hrefs = [a.get("href", "") for a in soup.find_all("a", href=True)]
        all_hrefs.extend(same_as_links)

        # Match links to platforms
        for plat_name, plat_info in platforms.items():
            for href in all_hrefs:
                href_lower = href.lower()
                for link_domain in plat_info["link_domains"]:
                    if link_domain in href_lower:
                        on_page_links[plat_name] = href
                        break
                if plat_name in on_page_links:
                    break

        # Check meta signals (e.g. twitter:site)
        for plat_name, plat_info in platforms.items():
            if plat_name in on_page_links:
                continue
            meta_key = plat_info.get("meta_signal")
            if meta_key:
                tag = soup.find("meta", attrs={"name": meta_key}) or soup.find("meta", attrs={"property": meta_key})
                if tag and tag.get("content"):
                    on_page_links[plat_name] = tag["content"]

    # --- Phase 2: Probe platforms not found on-page (concurrent) ---
    # Serial was the single biggest default-check bottleneck — 10 platforms
    # × 8s timeout = up to 80s blocking on this one function. Probes are
    # independent, so we fan them out with ThreadPoolExecutor. max_workers
    # caps at the platform count (≤ 10) to keep thread overhead minimal.
    probed = {}  # platform_name -> (found: bool, url)
    platforms_to_probe = {k: v for k, v in platforms.items() if k not in on_page_links}

    browser_ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

    def _probe_platform(plat_name, plat_info):
        """Probe one platform; return (plat_name, found, url).

        Pure — no prints, no shared mutation. Caller aggregates into `probed`.
        """
        for probe_url in plat_info["probe_urls"]:
            try:
                r = requests.get(probe_url, timeout=8, allow_redirects=True, headers={
                    "User-Agent": browser_ua
                })
                # Platform-specific detection logic
                if r.status_code == 200:
                    # Detect login redirects (e.g. Facebook redirects to /login/ for non-existent pages)
                    final_url = r.url.lower()
                    redirected_to_login = any(seg in final_url for seg in [
                        "/login", "/signin", "/sign_in", "/accounts/login",
                    ])

                    # Some platforms return 200 for "not found" pages, check content
                    text_lower = r.text.lower() if len(r.text) < 500000 else r.text[:500000].lower()
                    is_404_page = redirected_to_login or any(phrase in text_lower for phrase in [
                        "page not found", "this account doesn", "this page isn",
                        "nothing here", "sorry, nobody", "user not found",
                        "hmm...this page doesn", "account suspended",
                        "content isn't available", "content not available",
                        "this content is not available", "page isn't available",
                        "this page is not available", "link may be broken",
                        "profile not found", "channel not found",
                        "this user is not available", "suspended account",
                        "no results found", "couldn't find this account",
                        "we couldn't find", "does not exist",
                    ])
                    if not is_404_page:
                        return plat_name, True, probe_url
            except requests.RequestException:
                pass
        return plat_name, False, plat_info["probe_urls"][0]

    if platforms_to_probe:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=min(10, len(platforms_to_probe))) as pool:
            futures = [
                pool.submit(_probe_platform, name, info)
                for name, info in platforms_to_probe.items()
            ]
            for fut in as_completed(futures):
                plat_name, found, url = fut.result()
                probed[plat_name] = (found, url)

    # --- Phase 3: Report results ---
    found_platforms = []
    not_found_platforms = []

    # On-page links (highest confidence)
    for plat_name, link in sorted(on_page_links.items()):
        found_platforms.append(plat_name)
        print(f"  [{PASS}] {plat_name:<16} linked on site: {link}")

    # Probed and found
    for plat_name, (found, url) in sorted(probed.items()):
        if found:
            found_platforms.append(plat_name)
            print(f"  [{PASS}] {plat_name:<16} profile found: {url}")

    # Not found
    for plat_name, (found, url) in sorted(probed.items()):
        if not found:
            not_found_platforms.append(plat_name)
            print(f"  [{INFO}] {plat_name:<16} not detected")

    # --- Score & summary ---
    total_platforms = len(platforms)
    found_count = len(found_platforms)

    print()
    if found_count >= 6:
        print(f"  [{PASS}] Strong cross-platform presence: {found_count}/{total_platforms} platforms")
    elif found_count >= 3:
        print(f"  [{WARN}] Moderate cross-platform presence: {found_count}/{total_platforms} platforms")
    elif found_count >= 1:
        print(f"  [{WARN}] Limited cross-platform presence: {found_count}/{total_platforms} platforms")
    else:
        print(f"  [{FAIL}] No cross-platform presence detected")

    if not_found_platforms:
        fix(
            "Expand your brand presence on platforms that AI models train on:\n"
            + "".join(f"  - {p}\n" for p in not_found_platforms)
            + "AI engines (ChatGPT, Perplexity, Claude, Gemini) train on data from these platforms.\n"
            "Being present increases the probability of your brand being cited in AI answers,\n"
            "regardless of which source the AI pulls from."
        )

    # Score: 0-5 based on coverage
    if found_count >= 7:
        cp_score = 5
    elif found_count >= 5:
        cp_score = 4
    elif found_count >= 3:
        cp_score = 3
    elif found_count >= 1:
        cp_score = 1.5
    else:
        cp_score = 0
    track_score("Cross-Platform", cp_score, 5)

    # Provide the AI training context
    if found_platforms:
        print(f"\n  Platforms where your brand is visible to AI training:")
        ai_training_map = {
            "X / Twitter": "ChatGPT, Grok, Perplexity",
            "Reddit":      "ChatGPT, Claude, Gemini, Perplexity",
            "YouTube":     "Gemini, Perplexity (transcripts)",
            "LinkedIn":    "Bing Copilot, Perplexity",
            "GitHub":      "Copilot, ChatGPT, Claude",
            "Medium":      "ChatGPT, Claude, Perplexity",
            "Facebook":    "Meta AI",
            "Instagram":   "Meta AI",
            "TikTok":      "ByteDance AI",
            "Quora":       "ChatGPT, Perplexity",
        }
        for plat in found_platforms:
            ai_models = ai_training_map.get(plat, "various AI models")
            print(f"    {plat:<16} → trains: {ai_models}")


# ---------------------------------------------------------------------------
# 22. Multi-Page Sampling
# ---------------------------------------------------------------------------
def check_multi_page(base_url, sitemap_urls, max_pages=5):
    print("\n--- Multi-Page Sampling ---")

    candidates = []
    if sitemap_urls:
        candidates = sitemap_urls
    else:
        resp, soup = get_soup(base_url)
        if soup:
            parsed_base = urlparse(base_url)
            for a in soup.find_all("a", href=True):
                href = urljoin(base_url, a["href"])
                parsed_href = urlparse(href)
                if parsed_href.netloc == parsed_base.netloc and href.rstrip("/") != base_url.rstrip("/"):
                    candidates.append(href)

    if not candidates:
        print(f"  [{WARN}] No internal pages to sample")
        track_score("Multi-Page", 0, 5)
        return

    candidates = list(dict.fromkeys(candidates))
    content_candidates = [
        u for u in candidates
        if not re.search(r'\.(js|css|png|jpg|jpeg|gif|svg|ico|woff|woff2|ttf|eot|pdf|zip|gz|tar|mp4|mp3|webm|webp|avif|txt|md|xml|json|csv|rss|atom)$', urlparse(u).path, re.IGNORECASE)
        and "#" not in u
    ]
    sample = content_candidates[:max_pages]

    if not sample:
        print(f"  [{WARN}] No content pages found to sample")
        track_score("Multi-Page", 0, 5)
        return

    print(f"  Sampling {len(sample)} internal page(s)...\n")

    issues = {
        "missing_title": [],
        "missing_description": [],
        "missing_canonical": [],
        "missing_structured_data": [],
        "missing_h1": [],
        "low_word_count": [],
        "missing_og": [],
        "missing_alt_text": [],
    }
    descriptions_seen = {}
    titles_seen = {}
    page_shingles = {}  # short_url -> set of 5-word shingles

    def _shingles(text, k=5):
        tokens = re.findall(r"\w+", text.lower())
        if len(tokens) < k:
            return set()
        return {" ".join(tokens[i:i + k]) for i in range(len(tokens) - k + 1)}

    for page_url in sample:
        page_resp = fetch(page_url, timeout=10)
        if not page_resp or page_resp.status_code != 200:
            continue

        ctype = page_resp.headers.get("Content-Type", "").lower()
        if ctype and "html" not in ctype:
            continue

        page_soup = BeautifulSoup(page_resp.text, "html.parser")
        short_url = urlparse(page_url).path or page_url

        title = page_soup.find("title")
        title_text = ""
        if title and title.string and title.string.strip():
            title_text = title.string.strip()
        else:
            issues["missing_title"].append(short_url)
        if title_text:
            titles_seen.setdefault(title_text, []).append(short_url)

        desc = page_soup.find("meta", attrs={"name": "description"})
        desc_content = ""
        if desc and desc.get("content", "").strip():
            desc_content = desc["content"].strip()
        else:
            issues["missing_description"].append(short_url)

        if desc_content:
            descriptions_seen.setdefault(desc_content, []).append(short_url)

        canonical = page_soup.find("link", rel="canonical")
        if not canonical or not canonical.get("href"):
            issues["missing_canonical"].append(short_url)

        if not page_soup.find_all("script", type="application/ld+json"):
            issues["missing_structured_data"].append(short_url)

        if not page_soup.find("h1"):
            issues["missing_h1"].append(short_url)

        page_text = get_text_content(page_soup)
        if len(page_text.split()) < 100:
            issues["low_word_count"].append(short_url)
        page_shingles[short_url] = _shingles(page_text)

        if not page_soup.find("meta", property="og:title"):
            issues["missing_og"].append(short_url)

        imgs = page_soup.find_all("img")
        if imgs:
            missing_alt = sum(1 for img in imgs if not img.get("alt", "").strip())
            if missing_alt > len(imgs) * 0.5:
                issues["missing_alt_text"].append(short_url)

    duplicate_descs = {desc: pages for desc, pages in descriptions_seen.items() if len(pages) > 1}
    duplicate_titles = {t: pages for t, pages in titles_seen.items() if len(pages) > 1}

    # Jaccard similarity between page content pairs — detect overlap/cannibalization
    overlap_pairs = []
    shingle_items = [(u, s) for u, s in page_shingles.items() if s]
    for i in range(len(shingle_items)):
        u1, s1 = shingle_items[i]
        for j in range(i + 1, len(shingle_items)):
            u2, s2 = shingle_items[j]
            union = s1 | s2
            if not union:
                continue
            jaccard = len(s1 & s2) / len(union)
            if jaccard >= 0.5:
                overlap_pairs.append((u1, u2, jaccard))

    check_labels = {
        "missing_title": ("Missing <title>", FAIL),
        "missing_description": ("Missing meta description", FAIL),
        "missing_canonical": ("Missing canonical URL", WARN),
        "missing_structured_data": ("No structured data (JSON-LD)", WARN),
        "missing_h1": ("Missing <h1>", WARN),
        "low_word_count": ("Low word count (<100 words)", WARN),
        "missing_og": ("Missing Open Graph tags", WARN),
        "missing_alt_text": ("Most images missing alt text", WARN),
    }

    fix_suggestions = {
        "missing_title": "Add a unique, descriptive <title> tag to each page (under 60 chars).",
        "missing_description": "Add a unique meta description to each page (120-160 chars) summarizing the page content.",
        "missing_canonical": "Add <link rel=\"canonical\" href=\"...\"> to each page pointing to its preferred URL.",
        "missing_structured_data": "Add JSON-LD structured data to content pages (Article, Product, FAQPage, etc.).",
        "missing_h1": "Add a single <h1> tag to each page describing its primary topic.",
        "low_word_count": "Pages with <100 words have too little content for AI engines. Add substantive, unique text.",
        "missing_og": "Add Open Graph tags (og:title, og:description, og:image) to each page.",
        "missing_alt_text": "Add descriptive alt text to all images on these pages.",
    }

    all_good = True
    for key, (label, severity) in check_labels.items():
        pages = issues[key]
        if pages:
            all_good = False
            print(f"  [{severity}] {label} on {len(pages)} page(s):")
            for p in pages[:3]:
                print(f"         {p}")
            if len(pages) > 3:
                print(f"         ...and {len(pages) - 3} more")
            fix(fix_suggestions[key])

    if duplicate_descs:
        all_good = False
        print(f"  [{WARN}] Duplicate meta descriptions found across pages:")
        for desc_text, pages in list(duplicate_descs.items())[:3]:
            print(f"         \"{desc_text[:60]}...\" on {len(pages)} pages:")
            for p in pages[:5]:
                print(f"           - {p}")
            if len(pages) > 5:
                print(f"           ...and {len(pages) - 5} more")
        fix("Write unique meta descriptions for each page. Duplicate descriptions\nconfuse AI engines about which page to cite for a given topic.")

    if duplicate_titles:
        all_good = False
        print(f"  [{WARN}] Duplicate <title> tags found across pages:")
        for t, pages in list(duplicate_titles.items())[:3]:
            print(f"         \"{t[:60]}\" on {len(pages)} pages:")
            for p in pages[:5]:
                print(f"           - {p}")
            if len(pages) > 5:
                print(f"           ...and {len(pages) - 5} more")
        fix("Write unique <title> tags for each page. Identical titles cause keyword\ncannibalization — AI engines can't tell which page to cite for a given query.")

    if overlap_pairs:
        all_good = False
        print(f"  [{WARN}] Content overlap / possible cannibalization between pages:")
        for u1, u2, j in sorted(overlap_pairs, key=lambda x: -x[2])[:3]:
            print(f"         {int(j * 100)}% overlap: {u1}  ↔  {u2}")
        fix("Two or more pages cover the same topic with highly overlapping content.\n"
            "Options:\n"
            "  1. Consolidate into one canonical page and 301-redirect the others.\n"
            "  2. Differentiate each page with distinct angles, examples, and keywords.\n"
            "  3. Use rel=canonical to point near-duplicates to the primary page.\n"
            "Cannibalization dilutes your AI visibility — pick the strongest page to surface.")

    if all_good:
        print(f"  [{PASS}] All sampled pages maintain consistent GEO standards")
        track_score("Multi-Page", 5, 5)
    else:
        total_issues = (sum(len(v) for v in issues.values())
                        + len(duplicate_descs) + len(duplicate_titles) + len(overlap_pairs))
        mp_score = max(5 - total_issues, 0)
        track_score("Multi-Page", mp_score, 5)


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------
def generate_score(base_url):
    reset_state()
    parsed = urlparse(base_url)
    if not parsed.scheme:
        base_url = "https://" + base_url
    if not base_url.endswith("/"):
        base_url += "/"

    mode = "Diagnose + Fix Recommendations" if SHOW_FIX else "Diagnose Only"
    print(f"{'='*60}")
    print(f"  GEO Readiness Report for: {base_url}")
    print(f"  Mode: {mode}")
    print(f"{'='*60}")

    check_https(base_url)
    check_robots_txt(base_url)
    check_llms_txt(base_url)
    check_well_known(base_url)
    sitemap_urls = check_sitemap(base_url)
    check_search_engine_registration(base_url)
    check_structured_data(base_url)
    check_meta_tags(base_url)
    check_content_accessibility(base_url)
    check_ai_crawl_readiness(base_url)
    check_content_quality(base_url)
    check_technical_crawlability(base_url)
    check_authority_trust(base_url)
    check_brand_entity_kg(base_url)
    check_trust_safety(base_url)
    check_ai_optimization(base_url)
    check_social_signals(base_url)
    check_ai_answer_formats(base_url)
    check_schema_knowledge(base_url)
    check_mobile_and_weight(base_url)
    check_url_normalization(base_url)
    check_outbound_and_media(base_url)
    check_multilingual_depth(base_url)
    check_cross_platform(base_url)
    check_multi_page(base_url, sitemap_urls)

    # --- AI Visibility Score ---
    score = get_ai_visibility_score()
    grade = get_grade(score)

    print(f"\n{'='*60}")
    print(f"  AI VISIBILITY SCORE: {score}/100  (Grade: {grade})")
    print(f"{'='*60}")
    print(f"\n  Category Breakdown:")
    _W = 25
    print(f"  {_pad('Category', _W)} {'Score':>7}  {'Bar'}")
    print(f"  {'-'*_W} {'-'*7}  {'-'*20}")
    for cat, vals in sorted(_scores.items(), key=lambda x: x[0]):
        earned = vals["earned"]
        mx = vals["max"]
        pct = (earned / mx * 100) if mx > 0 else 0
        bar_len = int(pct / 5)
        bar = "\033[92m" + "█" * bar_len + "\033[0m" + "░" * (20 - bar_len)
        print(f"  {_pad(cat, _W)} {earned:>4.1f}/{mx:<3.0f}  {bar}")

    total_earned = sum(v["earned"] for v in _scores.values())
    total_max = sum(v["max"] for v in _scores.values())
    print(f"  {'-'*_W} {'-'*7}")
    print(f"  {_pad('TOTAL', _W)} {total_earned:>4.1f}/{total_max:<3.0f}")

    print(f"\n  Legend: PASS = good | WARN = could improve | FAIL = missing/bad")
    if SHOW_FIX:
        print("          FIX = recommended action to resolve the issue")

        # ── Content Gap Suggestions ──────────────────────────────
        # Analyze weak categories and suggest content strategies
        weak_cats = sorted(
            [(cat, vals) for cat, vals in _scores.items()
             if vals["max"] > 0 and (vals["earned"] / vals["max"]) < 0.5],
            key=lambda x: x[1]["earned"] / x[1]["max"],
        )
        if weak_cats:
            print(f"\n{'='*60}")
            print(f"  CONTENT GAP SUGGESTIONS")
            print(f"{'='*60}")
            print(f"\n  Based on your weakest categories, here are content strategies")
            print(f"  to improve your AI visibility:\n")

            # Map categories to content suggestions
            content_suggestions = {
                "Structured Data": [
                    "Create a FAQ page with FAQPage schema answering top questions about your product/service",
                    "Add HowTo schema to tutorial or setup guide pages",
                    "Use Product schema with reviews, pricing, and availability on product pages",
                ],
                "Content Quality": [
                    "Write long-form pillar content (2000+ words) covering your core topic comprehensively",
                    "Add an 'Industry Statistics' page with original data — AI engines heavily cite pages with numbers",
                    "Create comparison articles ('X vs Y') — these match competitive queries AI users ask",
                ],
                "AI Answer Formats": [
                    "Add a 'What is [your product]?' section with a clear 1-2 sentence definition",
                    "Structure blog posts as Q&A: use question headings followed by direct answers",
                    "Add 'Key Takeaways' or 'TL;DR' sections — AI engines extract these as summaries",
                ],
                "Meta Tags": [
                    "Write meta descriptions as self-contained answers (80-160 chars) — AI uses these as fallback snippets",
                    "Add Open Graph tags so AI engines can extract your preferred title and description",
                ],
                "Content Accessibility": [
                    "Reduce JavaScript dependency — AI crawlers can't execute JS; ensure content is in raw HTML",
                    "Add alt text to all images describing what they show — AI uses this for context",
                ],
                "Brand Entity KG": [
                    "Create or improve your Wikipedia page — AI engines use Wikipedia as a primary knowledge source",
                    "Claim and complete your Google Business Profile, Crunchbase, and LinkedIn company pages",
                    "Get featured on industry-specific directories and 'best of' lists",
                ],
                "Authority & Trust": [
                    "Add author bios with credentials and links to external profiles (LinkedIn, Twitter)",
                    "Publish guest posts on authoritative sites in your industry with backlinks",
                    "Add an 'About Us' page with team expertise, founding story, and mission statement",
                ],
                "Trust & Safety": [
                    "Add clearly linked Privacy Policy, Terms of Service, and Contact pages",
                    "Display business identity: address, phone, registration number where applicable",
                ],
                "Social Signals": [
                    "Link to active social media profiles from your site (header or footer)",
                    "Publish regularly on LinkedIn, Twitter/X — AI engines cross-reference social presence",
                ],
                "llms.txt": [
                    "Create /llms.txt describing your site's purpose and content for AI crawlers",
                    "Add /llms-full.txt with comprehensive site documentation for deeper AI indexing",
                ],
                "Robots.txt": [
                    "Create a robots.txt that explicitly allows AI crawler access",
                    "Add an ai.txt or .well-known/ai.txt to declare your AI data usage preferences",
                ],
                "Multi-Page": [
                    "Ensure each page has a unique title and meta description — duplicate content confuses AI",
                    "Diversify content across pages; avoid repeating the same paragraphs on multiple URLs",
                ],
                "Outbound & Media": [
                    "Link to authoritative external sources — AI engines trust pages that cite credible references",
                    "Embed diverse media (images, videos, infographics) — richer content gets cited more",
                ],
            }

            shown = 0
            for cat, vals in weak_cats:
                pct = round(vals["earned"] / vals["max"] * 100)
                suggestions = content_suggestions.get(cat, [])
                if not suggestions:
                    # Fuzzy match: try partial category name
                    for key in content_suggestions:
                        if key.lower() in cat.lower() or cat.lower() in key.lower():
                            suggestions = content_suggestions[key]
                            break
                if suggestions and shown < 5:
                    print(f"  {cat} ({pct}%):")
                    for s in suggestions[:2]:
                        print(f"    → {s}")
                    print()
                    shown += 1
    else:
        print("  Tip: Run with --fix to see recommended solutions")
    print(f"{'='*60}\n")

    return score


def run_silent(url):
    """Run all checks on a URL, suppress output, return (score, scores_dict)."""
    global SHOW_FIX
    old_fix = SHOW_FIX
    SHOW_FIX = False
    reset_state()

    parsed = urlparse(url)
    if not parsed.scheme:
        url = "https://" + url
    if not url.endswith("/"):
        url += "/"

    old_stdout = sys.stdout
    sys.stdout = io.StringIO()

    try:
        check_https(url)
        check_robots_txt(url)
        check_llms_txt(url)
        check_well_known(url)
        sitemap_urls = check_sitemap(url)
        check_search_engine_registration(url)
        check_structured_data(url)
        check_meta_tags(url)
        check_content_accessibility(url)
        check_ai_crawl_readiness(url)
        check_content_quality(url)
        check_technical_crawlability(url)
        check_authority_trust(url)
        check_brand_entity_kg(url)
        check_trust_safety(url)
        check_ai_optimization(url)
        check_social_signals(url)
        check_ai_answer_formats(url)
        check_schema_knowledge(url)
        check_mobile_and_weight(url)
        check_url_normalization(url)
        check_outbound_and_media(url)
        check_multilingual_depth(url)
        check_cross_platform(url)
        check_multi_page(url, sitemap_urls)
    finally:
        sys.stdout = old_stdout
        SHOW_FIX = old_fix

    score = get_ai_visibility_score()
    scores_copy = {k: dict(v) for k, v in _scores.items()}
    return score, scores_copy, url


def compare_urls(urls, return_data=False):
    """Compare GEO readiness across multiple URLs side-by-side.

    When return_data=True, skips CLI formatting and returns a JSON-serialisable
    dict with per-URL scores, per-category breakdown, and the computed winner.
    """
    results = []

    for url in urls:
        print(f"  Analyzing {url} ...", flush=True)
        score, scores_dict, normalized_url = run_silent(url)
        results.append({
            "url": normalized_url,
            "domain": urlparse(normalized_url).netloc,
            "score": score,
            "grade": get_grade(score),
            "categories": scores_dict,
        })

    # Collect all category names
    all_categories = sorted(set(
        cat for r in results for cat in r["categories"]
    ))

    # Display comparison
    domains = [r["domain"] for r in results]
    col_width = max(max(len(d) for d in domains) + 2, 14)

    print(f"\n{'='*60}")
    print(f"  GEO COMPETITIVE COMPARISON")
    print(f"{'='*60}\n")

    # Header row
    _W = 25
    header = f"  {_pad('Category', _W)}"
    for r in results:
        header += f" {r['domain']:>{col_width}}"
    print(header)
    print(f"  {'-'*_W}" + f" {'-'*col_width}" * len(results))

    # Category rows
    for cat in all_categories:
        row = f"  {_pad(cat, _W)}"
        cat_scores = []
        for r in results:
            vals = r["categories"].get(cat, {"earned": 0, "max": 0})
            earned = vals["earned"]
            mx = vals["max"]
            pct = round(earned / mx * 100) if mx > 0 else 0
            cat_scores.append(pct)
            row += f" {earned:>4.1f}/{mx:<3.0f} ({pct:>2}%)"

        # Mark the winner with color
        if len(cat_scores) > 1:
            max_pct = max(cat_scores)
            parts = row.split()
            # Just print the row — winner highlighting via score comparison table below
        print(row)

    # Totals
    print(f"  {'-'*_W}" + f" {'-'*col_width}" * len(results))
    total_row = f"  {_pad('AI VISIBILITY SCORE', _W)}"
    for r in results:
        total_row += f" {'':>{col_width - 10}}{r['score']:>3}/100 ({r['grade']})"
    print(total_row)

    # Winner
    if len(results) > 1:
        sorted_results = sorted(results, key=lambda x: x["score"], reverse=True)
        winner = sorted_results[0]
        runner_up = sorted_results[1]
        lead = winner["score"] - runner_up["score"]

        print(f"\n  Winner: {winner['domain']} ({winner['score']}/100, Grade {winner['grade']})")
        if lead > 0:
            print(f"  Lead: +{lead} points over {runner_up['domain']}")

        # Show where each site wins
        print(f"\n  Category Advantages:")
        for cat in all_categories:
            scores_per_url = []
            for r in results:
                vals = r["categories"].get(cat, {"earned": 0, "max": 0})
                mx = vals["max"]
                pct = (vals["earned"] / mx * 100) if mx > 0 else 0
                scores_per_url.append((r["domain"], pct))
            scores_per_url.sort(key=lambda x: x[1], reverse=True)
            if len(scores_per_url) > 1 and scores_per_url[0][1] > scores_per_url[1][1]:
                print(f"    {_pad(cat, _W)} → {scores_per_url[0][0]} ({scores_per_url[0][1]:.0f}% vs {scores_per_url[1][1]:.0f}%)")

    # ── AI Citation Share (when API keys available) ────────────
    import os as _os
    _pplx = _os.environ.get("PERPLEXITY_API_KEY", "").strip()
    _oai = _os.environ.get("OPENAI_API_KEY", "").strip()
    _anth = _os.environ.get("ANTHROPIC_API_KEY", "").strip()
    _dsk = _os.environ.get("DEEPSEEK_API_KEY", "").strip()
    _dbao = _os.environ.get("DOUBAO_API_KEY", "").strip()
    _dbao_m = _os.environ.get("DOUBAO_MODEL_ID", "").strip()

    _engines = {}
    if _pplx:
        _engines["Perplexity"] = ("perplexity", _pplx)
    if _oai:
        _engines["ChatGPT"] = ("openai", _oai)
    if _anth:
        _engines["Claude"] = ("anthropic", _anth)
    if _dsk:
        _engines["DeepSeek"] = ("deepseek", _dsk)
    if _dbao and _dbao_m:
        _engines["Doubao"] = ("doubao", _dbao)

    if _engines and len(results) >= 2:
        print(f"{'='*60}")
        print(f"  AI CITATION SHARE")
        print(f"  Engines: {', '.join(_engines.keys())}")
        print(f"{'='*60}")

        # Build competitive queries from the domains
        brands = [r["domain"].replace("www.", "").split(".")[0] for r in results]
        category_hint = ""
        for r in results:
            resp_c, soup_c = get_soup(r["url"])
            if soup_c:
                meta_d = soup_c.find("meta", attrs={"name": "description"})
                if meta_d and meta_d.get("content"):
                    category_hint = meta_d["content"][:60].split(",")[0].strip()
                    break

        cite_queries = []
        if category_hint:
            cite_queries.append(f"Best {category_hint} tools")
            cite_queries.append(f"Top {category_hint} solutions in 2025")
        cite_queries.append(f"Compare {' vs '.join(brands[:3])}")
        cite_queries.append(f"Which is better: {' or '.join(brands[:3])}?")
        for b in brands:
            cite_queries.append(f"What is {b}?")

        # Query each engine
        def _dispatch_query(query, eng_type, api_key):
            if eng_type == "perplexity":
                return _query_perplexity(query, api_key)
            elif eng_type == "openai":
                return _query_openai(query, api_key)
            elif eng_type == "anthropic":
                return _query_anthropic(query, api_key)
            elif eng_type == "deepseek":
                return _query_deepseek(query, api_key)
            elif eng_type == "doubao":
                return _query_doubao(query, api_key, _dbao_m)
            return "", [], "unknown_engine"

        # Track citation counts per domain
        domain_citations = {r["domain"]: 0 for r in results}
        domain_mentions = {r["domain"]: 0 for r in results}
        total_queries_run = 0

        for eng_name, (eng_type, api_key) in _engines.items():
            print(f"\n--- {eng_name} ---")
            for query in cite_queries:
                print(f"  [{INFO}] \"{query}\"")
                answer, citations, error = _dispatch_query(query, eng_type, api_key)
                if error == "invalid_key":
                    print(f"    [{FAIL}] Invalid API key — skipping {eng_name}")
                    break
                if error:
                    print(f"    [{WARN}] Error: {error}")
                    continue

                total_queries_run += 1
                answer_lower = answer.lower()
                for r in results:
                    dom = r["domain"]
                    dom_bare = dom.replace("www.", "")
                    brand_name = dom_bare.split(".")[0].lower()
                    # Check citations
                    cited = any(dom_bare in c for c in citations)
                    # Check text mentions
                    mentioned = dom_bare in answer_lower or brand_name in answer_lower
                    if cited:
                        domain_citations[dom] += 1
                        status = PASS
                    elif mentioned:
                        domain_mentions[dom] += 1
                        status = INFO
                    else:
                        status = FAIL
                    print(f"    {dom:<30} [{'CITED' if cited else 'MENTIONED' if mentioned else 'ABSENT'}]")

                time.sleep(1)

        # Citation share summary
        if total_queries_run > 0:
            print(f"\n{'='*60}")
            print(f"  CITATION SHARE RESULTS ({total_queries_run} queries x {len(_engines)} engine(s))")
            print(f"{'='*60}\n")
            print(f"  {_pad('Domain', 30)} {'Cited':>6} {'Mentioned':>10} {'Share':>8}")
            print(f"  {'-'*30} {'-'*6} {'-'*10} {'-'*8}")

            total_cites = sum(domain_citations.values()) or 1
            for r in results:
                dom = r["domain"]
                cites = domain_citations[dom]
                mentions = domain_mentions[dom]
                share = round(cites / total_cites * 100)
                bar_len = share // 5
                if share >= 40:
                    bc = "\033[92m"
                elif share >= 20:
                    bc = "\033[93m"
                else:
                    bc = "\033[91m"
                bar = bc + "█" * bar_len + "\033[0m" + "░" * (20 - bar_len)
                print(f"  {dom:<30} {cites:>6} {mentions:>10} {share:>6}%  {bar}")

            # Declare citation winner
            cite_winner = max(results, key=lambda r: domain_citations[r["domain"]])
            cite_loser = min(results, key=lambda r: domain_citations[r["domain"]])
            if domain_citations[cite_winner["domain"]] > domain_citations[cite_loser["domain"]]:
                print(f"\n  Citation leader: {cite_winner['domain']} "
                      f"({domain_citations[cite_winner['domain']]} citations, "
                      f"{round(domain_citations[cite_winner['domain']] / total_cites * 100)}% share)")

    elif not _engines and len(results) >= 2:
        print(f"\n  Tip: Set an AI API key to see Citation Share analysis")
        print(f"    export PERPLEXITY_API_KEY='pplx-...'   or   export OPENAI_API_KEY='sk-...'")

    print(f"\n{'='*60}\n")

    if return_data:
        # Build per-category advantage map used by the API consumer.
        advantages = []
        for cat in all_categories:
            per_url = []
            for r in results:
                vals = r["categories"].get(cat, {"earned": 0, "max": 0})
                mx = vals["max"]
                pct = (vals["earned"] / mx * 100) if mx > 0 else 0
                per_url.append({"domain": r["domain"], "percent": round(pct, 1)})
            per_url.sort(key=lambda x: x["percent"], reverse=True)
            advantages.append({"category": cat, "ranked": per_url})

        sorted_results = sorted(results, key=lambda x: x["score"], reverse=True)
        winner = None
        if sorted_results:
            top = sorted_results[0]
            lead = 0
            if len(sorted_results) > 1:
                lead = top["score"] - sorted_results[1]["score"]
            winner = {"domain": top["domain"], "score": top["score"], "grade": top["grade"], "lead": lead}

        return {
            "urls": [r["url"] for r in results],
            "results": results,
            "categories": all_categories,
            "advantages": advantages,
            "winner": winner,
        }


def parse_log_line(line):
    """Parse a single access log line (Common Log Format or Combined)."""
    # Combined/Common log format:
    # 66.249.66.1 - - [10/Apr/2026:12:34:56 +0000] "GET /page HTTP/1.1" 200 1234 "-" "Mozilla/5.0 ..."
    pattern = (
        r'^(\S+)\s+'           # IP
        r'\S+\s+\S+\s+'       # ident, authuser
        r'\[([^\]]+)\]\s+'    # timestamp
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


def aeo_visibility(url, return_data=False):
    """Answer Engine Optimization audit — checks how well a page is optimized
    to appear in AI-generated answers (ChatGPT, Perplexity, Google AI Overviews, etc.).
    Bundles all AEO-related signals into a single, focused report.
    Free — no API keys required.
    """
    parsed = urlparse(url)
    if not parsed.scheme:
        url = "https://" + url
    if not url.endswith("/"):
        url += "/"
    reset_state()

    print(f"\n{'='*60}")
    print(f"  AEO (Answer Engine Optimization) Audit")
    print(f"  Target: {url}")
    print(f"{'='*60}")

    resp, soup = get_soup(url)
    if not soup:
        print(f"\n  [{FAIL}] Could not fetch {url}")
        print(f"{'='*60}\n")
        return

    text = get_text_content(soup)

    # ── 1. FAQ Readiness ─────────────────────────────────────────
    print(f"\n--- 1. FAQ Readiness ---")
    faq_score = 0
    faq_max = 4

    # FAQPage schema
    json_ld_scripts = soup.find_all("script", type="application/ld+json")
    has_faq_schema = False
    faq_question_count = 0
    has_howto_schema = False
    has_qapage_schema = False
    all_schema_types = []
    for script in json_ld_scripts:
        try:
            data = json.loads(script.string)
            items = [data] if isinstance(data, dict) else data if isinstance(data, list) else []
            if isinstance(data, dict) and "@graph" in data:
                items.extend(data["@graph"])
            for item in items:
                if not isinstance(item, dict):
                    continue
                t = item.get("@type", "")
                if isinstance(t, list):
                    all_schema_types.extend(t)
                else:
                    all_schema_types.append(t)
                if t == "FAQPage":
                    has_faq_schema = True
                    entities = item.get("mainEntity", [])
                    if isinstance(entities, list):
                        faq_question_count = len(entities)
                elif t == "HowTo":
                    has_howto_schema = True
                elif t in ("QAPage", "Question"):
                    has_qapage_schema = True
        except (json.JSONDecodeError, TypeError):
            pass

    if has_faq_schema:
        print(f"  [{PASS}] FAQPage schema found ({faq_question_count} question(s))")
        faq_score += 2
    else:
        print(f"  [{FAIL}] No FAQPage schema — AI engines prioritize pages with FAQ structured data")
        fix("Add FAQPage JSON-LD schema:\n  <script type=\"application/ld+json\">\n  {\"@context\":\"https://schema.org\",\"@type\":\"FAQPage\",\n   \"mainEntity\":[{\"@type\":\"Question\",\"name\":\"Your question?\",\n   \"acceptedAnswer\":{\"@type\":\"Answer\",\"text\":\"Your answer.\"}}]}\n  </script>")

    # HTML FAQ signals
    faq_elements = soup.find_all(class_=re.compile(r"faq|frequently.asked", re.IGNORECASE))
    faq_elements += soup.find_all(id=re.compile(r"faq|frequently.asked", re.IGNORECASE))
    details_elements = soup.find_all("details")
    headings = soup.find_all(re.compile(r"^h[1-6]$"))
    question_headings = [h for h in headings if h.get_text(strip=True).rstrip().endswith("?")]

    html_faq_signals = 0
    if faq_elements:
        html_faq_signals += 1
        print(f"  [{PASS}] FAQ section found in HTML (class/id match)")
    if details_elements:
        html_faq_signals += 1
        print(f"  [{PASS}] {len(details_elements)} <details> accordion element(s) — good for expandable Q&A")
    if question_headings:
        html_faq_signals += 1
        print(f"  [{PASS}] {len(question_headings)} question heading(s) ending in '?'")
        for qh in question_headings[:3]:
            print(f"         \"{qh.get_text(strip=True)[:70]}\"")

    if html_faq_signals >= 2:
        faq_score += 2
    elif html_faq_signals == 1:
        faq_score += 1
        if not has_faq_schema:
            print(f"  [{WARN}] FAQ-like content exists but lacks FAQPage schema — add structured data")
    else:
        print(f"  [{WARN}] No FAQ section or question headings detected in HTML")
        fix("Add an FAQ section with question headings:\n  <h2>Frequently Asked Questions</h2>\n  <h3>What does your product do?</h3>\n  <p>Clear, concise answer...</p>")

    track_score("FAQ Readiness", faq_score, faq_max)

    # ── 2. Question-Pattern Headings ─────────────────────────────
    print(f"\n--- 2. Question-Pattern Headings ---")
    qh_score = 0
    qh_max = 3

    question_word_re = re.compile(
        r"^\s*(?:who|what|how|why|when|where|is|are|can|does|do|should|will|which|whose|whom)\b",
        re.IGNORECASE,
    )
    q_headings = []
    for h in headings:
        txt = h.get_text(strip=True)
        if not txt:
            continue
        if question_word_re.match(txt) or txt.rstrip().endswith("?"):
            q_headings.append((h.name, txt))

    if len(q_headings) >= 5:
        qh_score = 3
        print(f"  [{PASS}] {len(q_headings)} question-pattern headings — excellent conversational readiness")
    elif len(q_headings) >= 3:
        qh_score = 2
        print(f"  [{PASS}] {len(q_headings)} question-pattern headings — good conversational readiness")
    elif q_headings:
        qh_score = 1
        print(f"  [{WARN}] Only {len(q_headings)} question-pattern heading(s) — add more for chat-style queries")
        fix("Add more question-pattern headings matching how users prompt AI:\n  <h2>What is GEO?</h2>\n  <h2>How do I optimize for AI search?</h2>")
    else:
        print(f"  [{FAIL}] No question-pattern headings — AI answer engines match queries to Q&A headings")
        fix("Structure content around questions users ask AI engines:\n  <h2>What is [your topic]?</h2> → concise answer\n  <h3>How does [feature] work?</h3> → step-by-step")

    for tag_name, txt in q_headings[:5]:
        print(f"         <{tag_name}> \"{txt[:70]}\"")

    track_score("Question Headings", qh_score, qh_max)

    # ── 3. Direct Answer Snippets ────────────────────────────────
    print(f"\n--- 3. Direct Answer Snippets ---")
    da_score = 0
    da_max = 4

    # Definition sentences
    definition_patterns = re.findall(
        r'(?:^|\.\s+)([A-Z][^.]{5,60}?\s+(?:is|are|refers to|means|describes)\s+[^.]{10,}\.)',
        text
    )
    if definition_patterns:
        da_score += 1
        print(f"  [{PASS}] {len(definition_patterns)} definition-style sentence(s) — highly citable by AI")
        for d in definition_patterns[:2]:
            print(f"         \"{d[:80]}...\"" if len(d) > 80 else f"         \"{d}\"")
    else:
        print(f"  [{FAIL}] No definition-style sentences — AI engines quote 'X is Y' patterns directly")
        fix("Add clear definitions: '[Term] is [clear definition].'\n  e.g. 'Answer Engine Optimization (AEO) is the practice of optimizing content\n  to appear in AI-generated answers.'")

    # First-paragraph extractability
    main_el = soup.find("main") or soup.find("article") or soup.find("body")
    first_para = None
    if main_el:
        for p in main_el.find_all("p"):
            t = p.get_text(strip=True)
            if len(t.split()) >= 15:
                first_para = t
                break
    if first_para:
        has_definition = bool(re.search(r"\b(is|are|means|refers to|describes)\b", first_para, re.IGNORECASE))
        has_stat = bool(re.search(r"\d+(?:\.\d+)?%|\$\d+|\d{1,3}(?:,\d{3})+|\b\d{4}\b", first_para))
        wc = len(first_para.split())
        facts = []
        if has_definition:
            facts.append("definition")
        if has_stat:
            facts.append("statistic")
        if 25 <= wc <= 120 and facts:
            da_score += 1
            print(f"  [{PASS}] First paragraph ({wc} words) contains extractable facts: {', '.join(facts)}")
        elif facts:
            print(f"  [{WARN}] First paragraph has facts ({', '.join(facts)}) but is {wc} words — aim for 25-120")
            fix("Tighten your opening paragraph to 25-120 words for optimal AI snippet extraction.")
        else:
            print(f"  [{WARN}] First paragraph ({wc} words) lacks extractable facts")
            fix("Front-load a definition or key statistic into your first paragraph.")
    else:
        print(f"  [{WARN}] No substantive first paragraph found for snippet extraction")
        fix("Place a substantive opening paragraph inside <main> or <article> that\ndirectly answers 'what is this about?'")

    # Meta description as answer seed
    desc_tag = soup.find("meta", attrs={"name": "description"})
    desc_content = (desc_tag.get("content", "").strip()) if desc_tag else ""
    if desc_content:
        desc_len = len(desc_content)
        if 80 <= desc_len <= 160:
            da_score += 1
            print(f"  [{PASS}] Meta description ({desc_len} chars) — good length for AI answer seed")
        elif desc_len > 160:
            print(f"  [{WARN}] Meta description is {desc_len} chars — trim to 80-160 for a crisp AI summary")
        elif desc_len < 80:
            print(f"  [{WARN}] Meta description is only {desc_len} chars — expand to 80-160 for richer AI extraction")
    else:
        print(f"  [{FAIL}] No meta description — AI engines use this as a fallback answer snippet")
        fix("Add: <meta name=\"description\" content=\"80-160 char summary answering 'what is this page about?'\">")

    # Quotable statistics
    stat_patterns = re.findall(r'\d+(?:\.\d+)?%|\$\d+|\d+(?:,\d{3})+', text)
    if len(stat_patterns) >= 3:
        da_score += 1
        print(f"  [{PASS}] {len(stat_patterns)} quotable statistics — concrete data improves AI citations")
    elif stat_patterns:
        print(f"  [{INFO}] {len(stat_patterns)} statistic(s) — add more specific numbers for citability")
    else:
        print(f"  [{WARN}] No quotable statistics — specific data points make content more citable")
        fix("Add concrete, quotable statistics:\n  '95% of customers report improved performance'\n  'Reduces processing time by 3.5x'")

    track_score("Direct Answer Snippets", da_score, da_max)

    # ── 4. Structured Data for Answers ───────────────────────────
    print(f"\n--- 4. Answer Engine Schema ---")
    ae_score = 0
    ae_max = 4

    answer_types = {
        "FAQPage": has_faq_schema,
        "HowTo": has_howto_schema,
        "QAPage": has_qapage_schema,
    }
    present = [t for t, found in answer_types.items() if found]
    missing = [t for t, found in answer_types.items() if not found]

    if present:
        print(f"  [{PASS}] Answer-oriented schema: {', '.join(present)}")
        ae_score += min(len(present) * 1.5, 3)
    else:
        print(f"  [{FAIL}] No answer-oriented schema (FAQPage, HowTo, QAPage)")
        fix("Add at least one answer-oriented schema type:\n"
            "  • FAQPage — for Q&A content\n"
            "  • HowTo — for step-by-step instructions\n"
            "  • QAPage — for single-question answer pages")
    if missing and present:
        print(f"  [{INFO}] Not found: {', '.join(missing)}")

    # Speakable schema (voice search / smart speakers)
    has_speakable = "speakable" in " ".join(
        s.string or "" for s in json_ld_scripts
    ).lower()
    speakable_meta = soup.find("meta", attrs={"name": "speakable"})
    if has_speakable or speakable_meta:
        ae_score += 1
        print(f"  [{PASS}] Speakable markup found — voice assistants can read your content aloud")
    else:
        print(f"  [{INFO}] No Speakable markup — helps voice assistants (Siri, Alexa, Google) select content to read")
        fix("Add Speakable structured data to flag which content is voice-ready:\n"
            "  \"speakable\": {\"@type\": \"SpeakableSpecification\",\n"
            "    \"cssSelector\": [\".article-summary\", \".faq-answer\"]}")

    track_score("Answer Engine Schema", ae_score, ae_max)

    # ── 5. Content Structure for AI Extraction ───────────────────
    print(f"\n--- 5. Content Structure for AI Extraction ---")
    cs_score = 0
    cs_max = 5

    # Comparison tables
    tables = soup.find_all("table")
    has_comparison_table = False
    for table in tables:
        headers = table.find_all("th")
        if len(headers) >= 2:
            has_comparison_table = True
            break
    if has_comparison_table:
        cs_score += 1
        print(f"  [{PASS}] Comparison table(s) with headers — AI engines extract tabular data")
    elif tables:
        print(f"  [{WARN}] Tables found but missing <th> headers — add headers for AI extraction")
        fix("Add <thead>/<th> to tables for AI to extract comparison data.")
    else:
        print(f"  [{INFO}] No comparison tables — consider adding for feature/pricing comparisons")

    # Step-by-step instructions
    ordered_lists = soup.find_all("ol")
    has_steps = any(len(ol.find_all("li")) >= 3 for ol in ordered_lists)
    step_headings_found = [
        h for h in headings
        if re.search(r'step\s+\d|^\d+[\.\)]\s', h.get_text(strip=True), re.IGNORECASE)
    ]
    if has_steps or step_headings_found:
        cs_score += 1
        print(f"  [{PASS}] Step-by-step instructional content — great for 'how to' AI answers")
    else:
        print(f"  [{INFO}] No step-by-step instructions found")
        fix("Add numbered how-to instructions:\n  <h2>How to Set Up</h2>\n  <ol><li>Step 1</li><li>Step 2</li><li>Step 3</li></ol>")

    # Pros and cons
    pros_cons = re.findall(
        r'(?:pros?\s+(?:and|&)\s+cons?|advantages?\s+(?:and|&)\s+disadvantages?|benefits?\s+(?:and|&)\s+drawbacks?)',
        text, re.IGNORECASE
    )
    pros_cons_el = soup.find_all(class_=re.compile(r"pros?|cons?|advantage|disadvantage", re.IGNORECASE))
    if pros_cons or pros_cons_el:
        cs_score += 1
        print(f"  [{PASS}] Pros/cons content detected — AI engines cite balanced comparisons")
    else:
        print(f"  [{INFO}] No pros/cons content — balanced assessments help AI recommendation answers")
        fix("Add a pros/cons section:\n  <h3>Pros</h3><ul><li>...</li></ul>\n  <h3>Cons</h3><ul><li>...</li></ul>")

    # Key takeaways / TL;DR
    summary_headings = soup.find_all(
        re.compile(r"^h[1-6]$"),
        string=re.compile(r"key\s+takeaway|tl;?\s*dr|summary|in\s+(?:a\s+)?nutshell|bottom\s+line|conclusion", re.IGNORECASE)
    )
    summary_classes = soup.find_all(class_=re.compile(r"takeaway|tldr|summary|highlight", re.IGNORECASE))
    if summary_headings or summary_classes:
        cs_score += 1
        print(f"  [{PASS}] Summary/key takeaways section — AI engines prefer concise summaries")
    else:
        print(f"  [{WARN}] No key takeaways or TL;DR section")
        fix("Add a 'Key Takeaways' section:\n  <h2>Key Takeaways</h2>\n  <ul><li>Point 1</li><li>Point 2</li></ul>")

    # Structured lists
    list_items = soup.find_all("li")
    if len(list_items) >= 5:
        cs_score += 1
        print(f"  [{PASS}] Structured lists ({len(list_items)} items) — easily extractable by AI")
    elif list_items:
        print(f"  [{INFO}] Some list content ({len(list_items)} items) — more structured lists help AI")
    else:
        print(f"  [{WARN}] No list elements — structured lists help AI extract key points")

    track_score("Content Structure", min(cs_score, cs_max), cs_max)

    # ── 6. Readability & Source Trust ────────────────────────────
    print(f"\n--- 6. Readability & Source Trust ---")
    rt_score = 0
    rt_max = 4

    grade = flesch_kincaid_grade(text)
    if grade is not None:
        if 6 <= grade <= 12:
            rt_score += 1.5
            print(f"  [{PASS}] Readability: Flesch-Kincaid grade {grade:.1f} (accessible for AI extraction)")
        elif grade < 6:
            rt_score += 1
            print(f"  [{INFO}] Readability: Flesch-Kincaid grade {grade:.1f} (very simple)")
        else:
            print(f"  [{WARN}] Readability: Flesch-Kincaid grade {grade:.1f} — simpler text ranks better in AI answers")
            fix("Simplify content: shorter sentences, plain language, bullet points, active voice.")

    # Source attributions
    source_patterns = re.findall(
        r'(?:according to|source:|study by|research from|data from|report by|published in)\s',
        text, re.IGNORECASE
    )
    if source_patterns:
        rt_score += 1
        print(f"  [{PASS}] {len(source_patterns)} source attribution(s) — increases AI trust in your content")
    else:
        print(f"  [{WARN}] No source attributions — citing sources increases AI engine trust")
        fix("Add attributions: 'According to [Source]...' or 'Data from [Study]...'")

    # Definition markup (<dfn>, <abbr>)
    dfn_tags = soup.find_all("dfn")
    abbr_tags = soup.find_all("abbr")
    if dfn_tags or abbr_tags:
        rt_score += 0.5
        print(f"  [{PASS}] Definition markup: {len(dfn_tags)} <dfn>, {len(abbr_tags)} <abbr> tags")
    else:
        print(f"  [{INFO}] No <dfn>/<abbr> tags — markup terms so AI engines can define them")

    # Semantic HTML
    semantic_tags = ["article", "main", "section", "nav", "aside", "header", "footer"]
    found_semantic = [tag for tag in semantic_tags if soup.find(tag)]
    if len(found_semantic) >= 3:
        rt_score += 1
        print(f"  [{PASS}] Good semantic HTML ({', '.join(found_semantic)}) — helps AI parse content blocks")
    elif found_semantic:
        rt_score += 0.5
        print(f"  [{WARN}] Limited semantic HTML ({', '.join(found_semantic)}) — more semantic tags help AI")
    else:
        print(f"  [{FAIL}] No semantic HTML tags — AI engines rely on semantic structure to extract answers")
        fix("Replace <div> containers with: <main>, <article>, <section>, <aside>, <header>, <footer>")

    track_score("Readability & Trust", rt_score, rt_max)

    # ── 7. Heading Hierarchy & Answer Mapping ────────────────────
    print(f"\n--- 7. Heading Hierarchy ---")
    hh_score = 0
    hh_max = 3

    if headings:
        h_tags = [h.name for h in headings]
        h_summary = {tag: h_tags.count(tag) for tag in sorted(set(h_tags))}
        summary_str = ", ".join(f"{k}: {v}" for k, v in h_summary.items())
        print(f"  [{PASS}] Heading structure: {summary_str}")
        hh_score += 1
        if headings[0].name == "h1":
            hh_score += 1
            print(f"  [{PASS}] Page starts with <h1> — clear topic signal for AI")
        else:
            print(f"  [{WARN}] First heading is <{headings[0].name}>, not <h1>")
            fix("Start with an <h1> containing the primary topic.")

        # Check for logical hierarchy (no level skipping)
        prev_level = 0
        skips = 0
        for h in headings:
            level = int(h.name[1])
            if prev_level > 0 and level > prev_level + 1:
                skips += 1
            prev_level = level
        if skips == 0:
            hh_score += 1
            print(f"  [{PASS}] Clean heading hierarchy — no skipped levels")
        else:
            print(f"  [{WARN}] {skips} heading level skip(s) — use sequential h1→h2→h3 for AI parsing")
    else:
        print(f"  [{FAIL}] No heading tags found — headings are critical for AI content parsing")
        fix("Add heading tags: <h1>Main Topic</h1>, <h2>Subtopic</h2>, <h3>Detail</h3>")

    track_score("Heading Hierarchy", hh_score, hh_max)

    # ── 8. Per-Page Content Score ────────────────────────────────
    print(f"\n--- 8. Per-Page AEO Content Score ---")
    pp_score = 0
    pp_max = 5

    # Discover internal pages from links on the target page
    parsed_url = urlparse(url)
    internal_urls = []
    seen_paths = {parsed_url.path.rstrip("/") or "/"}
    for a_tag in soup.find_all("a", href=True):
        href = urljoin(url, a_tag["href"])
        parsed_href = urlparse(href)
        norm_path = parsed_href.path.rstrip("/") or "/"
        if (parsed_href.netloc == parsed_url.netloc
                and norm_path not in seen_paths
                and not re.search(r'\.(js|css|png|jpg|jpeg|gif|svg|ico|woff|woff2|ttf|eot|pdf|zip|gz|mp4|mp3|webm|webp|xml|json|txt|rss)$', parsed_href.path, re.IGNORECASE)
                and "#" not in href):
            seen_paths.add(norm_path)
            internal_urls.append(href)

    sample_pages = internal_urls[:5]
    # Include the target page itself as the first page to score
    all_pages = [url] + sample_pages

    def _score_page_aeo(page_url, page_soup):
        """Score a single page on AEO content signals. Returns (score_0_100, weakest_signal)."""
        signals = {}  # signal_name -> (earned, max, label)

        page_text = get_text_content(page_soup)
        page_headings = page_soup.find_all(re.compile(r"^h[1-6]$"))
        word_count = len(page_text.split()) if page_text else 0

        # Signal 1: Title length (40-65 chars is optimal)
        title_tag = page_soup.find("title")
        title_text = title_tag.get_text(strip=True) if title_tag else ""
        tlen = len(title_text)
        if 40 <= tlen <= 65:
            signals["Title length"] = (2, 2, f"{tlen}ch")
        elif 20 <= tlen < 40 or 65 < tlen <= 80:
            signals["Title length"] = (1, 2, f"{tlen}ch")
        else:
            signals["Title length"] = (0, 2, f"{tlen}ch" if tlen else "missing")

        # Signal 2: Heading density (headings per 500 words)
        if word_count >= 100:
            h_density = len(page_headings) / (word_count / 500) if word_count > 0 else 0
            if 2 <= h_density <= 8:
                signals["Heading density"] = (2, 2, f"{h_density:.1f}/500w")
            elif 1 <= h_density < 2 or 8 < h_density <= 12:
                signals["Heading density"] = (1, 2, f"{h_density:.1f}/500w")
            else:
                signals["Heading density"] = (0, 2, f"{h_density:.1f}/500w")
        else:
            signals["Heading density"] = (1, 2, f"{word_count}w total")

        # Signal 3: Paragraph balance (avg paragraph length 40-120 words)
        main_el = page_soup.find("main") or page_soup.find("article") or page_soup.find("body")
        paragraphs = main_el.find_all("p") if main_el else []
        para_lengths = [len(p.get_text(strip=True).split()) for p in paragraphs if len(p.get_text(strip=True).split()) >= 5]
        if para_lengths:
            avg_para = sum(para_lengths) / len(para_lengths)
            if 40 <= avg_para <= 120:
                signals["Paragraph balance"] = (2, 2, f"avg {avg_para:.0f}w")
            elif 20 <= avg_para < 40 or 120 < avg_para <= 180:
                signals["Paragraph balance"] = (1, 2, f"avg {avg_para:.0f}w")
            else:
                signals["Paragraph balance"] = (0, 2, f"avg {avg_para:.0f}w")
        else:
            signals["Paragraph balance"] = (0, 2, "no paragraphs")

        # Signal 4: Question-pattern headings
        q_word_re = re.compile(r"^\s*(?:who|what|how|why|when|where|is|are|can|does|do|should|will|which)\b", re.IGNORECASE)
        q_count = sum(1 for h in page_headings if q_word_re.match(h.get_text(strip=True)) or h.get_text(strip=True).rstrip().endswith("?"))
        if q_count >= 3:
            signals["Question headings"] = (2, 2, str(q_count))
        elif q_count >= 1:
            signals["Question headings"] = (1, 2, str(q_count))
        else:
            signals["Question headings"] = (0, 2, "0")

        # Signal 5: Definition sentences ("X is Y" patterns)
        def_count = len(re.findall(
            r'(?:^|\.\s+)([A-Z][^.]{5,60}?\s+(?:is|are|refers to|means|describes)\s+[^.]{10,}\.)',
            page_text
        )) if page_text else 0
        if def_count >= 3:
            signals["Definitions"] = (2, 2, str(def_count))
        elif def_count >= 1:
            signals["Definitions"] = (1, 2, str(def_count))
        else:
            signals["Definitions"] = (0, 2, "0")

        # Signal 6: Structured data specificity (answer-oriented types score higher)
        page_schemas = []
        answer_schemas = {"FAQPage", "HowTo", "QAPage", "Question"}
        specific_schemas = {"Product", "Recipe", "Event", "Course", "SoftwareApplication",
                           "LocalBusiness", "Review", "MedicalCondition", "JobPosting"}
        for sc in page_soup.find_all("script", type="application/ld+json"):
            try:
                sd = json.loads(sc.string)
                items = [sd] if isinstance(sd, dict) else sd if isinstance(sd, list) else []
                if isinstance(sd, dict) and "@graph" in sd:
                    items.extend(sd["@graph"])
                for item in items:
                    if isinstance(item, dict):
                        st = item.get("@type", "")
                        if isinstance(st, list):
                            page_schemas.extend(st)
                        else:
                            page_schemas.append(st)
            except (json.JSONDecodeError, TypeError):
                pass
        has_answer_schema = any(s in answer_schemas for s in page_schemas)
        has_specific_schema = any(s in specific_schemas for s in page_schemas)
        if has_answer_schema:
            signals["Schema specificity"] = (2, 2, "answer-oriented")
        elif has_specific_schema:
            signals["Schema specificity"] = (1, 2, "specific type")
        elif page_schemas:
            signals["Schema specificity"] = (0.5, 2, "generic only")
        else:
            signals["Schema specificity"] = (0, 2, "none")

        # Signal 7: List usage (structured content)
        list_items = len(page_soup.find_all("li"))
        if list_items >= 8:
            signals["List usage"] = (1, 1, f"{list_items} items")
        elif list_items >= 3:
            signals["List usage"] = (0.5, 1, f"{list_items} items")
        else:
            signals["List usage"] = (0, 1, f"{list_items} items")

        # Signal 8: Content freshness (dateModified, <time> tags, last-modified header)
        has_date_modified = False
        for sc in page_soup.find_all("script", type="application/ld+json"):
            try:
                sd = json.loads(sc.string)
                items = [sd] if isinstance(sd, dict) else sd if isinstance(sd, list) else []
                if isinstance(sd, dict) and "@graph" in sd:
                    items.extend(sd["@graph"])
                for item in items:
                    if isinstance(item, dict) and item.get("dateModified"):
                        has_date_modified = True
                        break
            except (json.JSONDecodeError, TypeError):
                pass
        time_tags = page_soup.find_all("time")
        if has_date_modified:
            signals["Content freshness"] = (1, 1, "dateModified")
        elif time_tags:
            signals["Content freshness"] = (0.5, 1, "<time> tags")
        else:
            signals["Content freshness"] = (0, 1, "no date signals")

        total_e = sum(v[0] for v in signals.values())
        total_m = sum(v[1] for v in signals.values())
        score_100 = round((total_e / total_m) * 100) if total_m > 0 else 0

        # Find weakest signal
        weakest = min(signals.items(), key=lambda x: x[1][0] / x[1][1] if x[1][1] > 0 else 0)
        return score_100, weakest[0], weakest[1][2], signals

    page_results = []
    for page_url in all_pages:
        p_resp, p_soup = get_soup(page_url)
        if not p_soup:
            continue
        score_100, weak_name, weak_detail, _ = _score_page_aeo(page_url, p_soup)
        short_url = urlparse(page_url).path or "/"
        if len(short_url) > 40:
            short_url = short_url[:37] + "..."
        page_results.append((short_url, score_100, weak_name, weak_detail))

    if page_results:
        print(f"  Scored {len(page_results)} page(s) on 8 AEO content signals:\n")
        print(f"  {_pad('Page', 42)} {'Score':>5}  {'Weakest Signal'}")
        print(f"  {'-'*42} {'-'*5}  {'-'*30}")
        total_page_score = 0
        for short_url, sc, wk_name, wk_detail in page_results:
            color = "\033[92m" if sc >= 70 else "\033[93m" if sc >= 40 else "\033[91m"
            rst = "\033[0m"
            print(f"  {short_url:<42} {color}{sc:>3}{rst}/100  {wk_name}: {wk_detail}")
            total_page_score += sc

        avg_score = total_page_score / len(page_results)
        print(f"  {'-'*42} {'-'*5}")
        print(f"  {_pad('Average', 42)} {avg_score:>5.0f}/100")

        # Map average to pp_score: 80+ = 5, 60-79 = 4, 40-59 = 3, 20-39 = 2, <20 = 1
        if avg_score >= 80:
            pp_score = 5
            print(f"\n  [{PASS}] Strong per-page AEO content quality across sampled pages")
        elif avg_score >= 60:
            pp_score = 4
            print(f"\n  [{PASS}] Good per-page AEO content quality — some pages need attention")
        elif avg_score >= 40:
            pp_score = 3
            print(f"\n  [{WARN}] Moderate per-page AEO quality — several pages need optimization")
        elif avg_score >= 20:
            pp_score = 2
            print(f"\n  [{WARN}] Weak per-page AEO content — most pages need significant improvement")
        else:
            pp_score = 1
            print(f"\n  [{FAIL}] Very weak per-page AEO content — pages lack AI-citable structure")

        # Show top improvement opportunities
        weak_pages = [(u, s, w, d) for u, s, w, d in page_results if s < 60]
        if weak_pages:
            fix("Pages scoring below 60 need attention:\n" + "\n".join(
                f"  • {u} — improve {w} ({d})" for u, s, w, d in sorted(weak_pages, key=lambda x: x[1])[:3]
            ))
    else:
        print(f"  [{WARN}] Could not score any pages")
        pp_score = 0

    track_score("Per-Page Content", pp_score, pp_max)

    # ── AEO Score ────────────────────────────────────────────────
    total_earned = sum(v["earned"] for v in _scores.values())
    total_max = sum(v["max"] for v in _scores.values())
    aeo_score = round((total_earned / total_max) * 100) if total_max > 0 else 0
    grade_letter = get_grade(aeo_score)

    print(f"\n{'='*60}")
    print(f"  AEO SCORE: {aeo_score}/100  (Grade: {grade_letter})")
    print(f"{'='*60}")
    print(f"\n  Category Breakdown:")
    _W = 25
    print(f"  {_pad('Category', _W)} {'Score':>7}  {'Bar'}")
    print(f"  {'-'*_W} {'-'*7}  {'-'*20}")
    for cat, vals in sorted(_scores.items(), key=lambda x: x[0]):
        earned = vals["earned"]
        mx = vals["max"]
        pct = (earned / mx * 100) if mx > 0 else 0
        bar_len = int(pct / 5)
        bar = "\033[92m" + "█" * bar_len + "\033[0m" + "░" * (20 - bar_len)
        print(f"  {_pad(cat, _W)} {earned:>4.1f}/{mx:<3.0f}  {bar}")

    print(f"  {'-'*_W} {'-'*7}")
    print(f"  {_pad('TOTAL', _W)} {total_earned:>4.1f}/{total_max:<3.0f}")

    # AEO-specific recommendations
    weak_categories = [
        (cat, vals) for cat, vals in _scores.items()
        if vals["max"] > 0 and (vals["earned"] / vals["max"]) < 0.5
    ]
    if weak_categories:
        print(f"\n  Priority improvements:")
        for cat, vals in sorted(weak_categories, key=lambda x: x[1]["earned"] / x[1]["max"]):
            pct = round(vals["earned"] / vals["max"] * 100)
            print(f"    • {cat} ({pct}%) — see recommendations above")

    if SHOW_FIX:
        print(f"\n  FIX recommendations are shown inline above.")
    else:
        print(f"\n  Tip: Run with --fix to see actionable fix recommendations")
    print(f"{'='*60}\n")

    if return_data:
        return {
            "url": url,
            "domain": urlparse(url).netloc,
            "score": aeo_score,
            "grade": grade_letter,
            "max_score": 100,
            "categories": {
                cat: {"earned": round(vals["earned"], 1), "max": round(vals["max"], 1)}
                for cat, vals in _scores.items()
            },
            "page_results": [
                {"path": u, "score": s, "weakest_signal": w, "weakest_detail": d}
                for u, s, w, d in page_results
            ],
            "priority_improvements": [
                {"category": cat, "percent": round(vals["earned"] / vals["max"] * 100)}
                for cat, vals in sorted(
                    [(c, v) for c, v in _scores.items()
                     if v["max"] > 0 and v["earned"] / v["max"] < 0.5],
                    key=lambda x: x[1]["earned"] / x[1]["max"],
                )
            ],
        }

    return aeo_score


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


def authority_audit(url, return_data=False):
    """Audit off-page authority signals: reviews, awards, Google authority, authoritative mentions.

    When return_data=True, returns a dict with section-by-section signals and a
    composite authority score + grade.
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if not parsed.scheme:
        url = "https://" + url
        parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    domain = parsed.netloc.replace("www.", "")
    brand = domain.split(".")[0]

    print(f"\n{'='*60}")
    print(f"  Authority & Reputation Audit")
    print(f"  Target: {base_url}")
    print(f"  Domain: {domain} | Brand: {brand}")
    print(f"{'='*60}")

    # Fetch homepage for on-page analysis
    resp, soup = get_soup(base_url)
    homepage_text = ""
    json_ld_blocks = []
    if soup:
        homepage_text = get_text_content(soup).lower()
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                if isinstance(data, list):
                    json_ld_blocks.extend(data)
                else:
                    json_ld_blocks.append(data)
            except (json.JSONDecodeError, TypeError):
                pass

    authority_score = 0
    max_score = 0

    # ── 1. Online Reviews ──
    print(f"\n--- 1. Online Reviews ---")
    max_score += 5

    # Check review platforms
    review_platforms = {
        "Trustpilot":    f"https://www.trustpilot.com/review/{domain}",
        "G2":            f"https://www.g2.com/products/{brand}/reviews",
        "Capterra":      f"https://www.capterra.com/p/{brand}/reviews/",
        "Product Hunt":  f"https://www.producthunt.com/products/{brand}",
        "Google Business": None,  # checked via schema
    }

    found_platforms = []
    for platform, check_url in review_platforms.items():
        if platform == "Google Business":
            continue
        try:
            r = requests.get(check_url, timeout=10, allow_redirects=True, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            })
            # Most platforms return 200 even for non-existent pages, so check content
            if r.status_code == 200 and domain in r.text.lower():
                found_platforms.append(platform)
                print(f"  [{PASS}] {platform} — profile found")
                print(f"         {check_url}")
            elif r.status_code == 200 and brand in r.text.lower():
                found_platforms.append(platform)
                print(f"  [{PASS}] {platform} — possible profile found")
                print(f"         {check_url}")
            else:
                print(f"  [{INFO}] {platform} — no profile detected")
        except requests.RequestException:
            print(f"  [{INFO}] {platform} — could not check (timeout/blocked)")

    # Check for review schema on site
    has_review_schema = False
    for block in json_ld_blocks:
        block_str = json.dumps(block).lower()
        if any(t in block_str for t in ['"review"', '"aggregaterating"', '"rating"']):
            has_review_schema = True
            break
    if soup:
        # Also check for embedded review markup
        review_attrs = soup.find_all(attrs={"itemtype": re.compile(r"schema.org/(Review|AggregateRating)", re.I)})
        if review_attrs:
            has_review_schema = True

    if has_review_schema:
        print(f"  [{PASS}] Review/Rating structured data found on site")
        found_platforms.append("On-site schema")

    # Check for links to review platforms in page
    if soup:
        review_domains = ["trustpilot.com", "g2.com", "capterra.com", "producthunt.com",
                         "yelp.com", "bbb.org", "glassdoor.com"]
        linked_platforms = set()
        for a in soup.find_all("a", href=True):
            href = a["href"].lower()
            for rd in review_domains:
                if rd in href:
                    linked_platforms.add(rd.split(".")[0].title())
        if linked_platforms:
            for lp in linked_platforms:
                print(f"  [{PASS}] Links to {lp} review page from site")
            found_platforms.extend(linked_platforms)

    if len(found_platforms) >= 3:
        authority_score += 5
        print(f"\n  Review presence: STRONG ({len(found_platforms)} platforms)")
    elif len(found_platforms) >= 1:
        authority_score += 3
        print(f"\n  Review presence: MODERATE ({len(found_platforms)} platform(s))")
    else:
        print(f"\n  [{WARN}] No review presence detected on major platforms")
        fix("List your product on review platforms to build trust signals:\n"
            "  - Trustpilot (https://business.trustpilot.com) — general reviews\n"
            "  - G2 (https://sell.g2.com) — B2B/SaaS reviews\n"
            "  - Product Hunt (https://producthunt.com) — launch & discovery\n"
            "  - Capterra (https://capterra.com) — software reviews\n"
            "Add AggregateRating schema to your site to display star ratings in search.")

    # ── 2. Awards, Accreditations & Affiliations ──
    print(f"\n--- 2. Awards, Accreditations & Affiliations ---")
    max_score += 5

    # Check page content for award/accreditation signals
    award_keywords = [
        "award", "awarded", "winner", "finalist", "recognized", "named",
        "best of", "top rated", "leader in", "badge", "certified",
        "accredited", "accreditation", "certification", "iso ", "soc 2",
        "soc2", "gdpr", "hipaa", "pci dss", "pci-dss", "compliant",
        "compliance", "member of", "affiliated", "partnership", "partner",
        "backed by", "funded by", "yc ", "y combinator", "techstars",
        "forbes", "gartner", "forrester", "inc 5000", "deloitte",
    ]
    found_awards = []
    for kw in award_keywords:
        if kw in homepage_text:
            found_awards.append(kw)

    # Check for award-related schema
    award_schema_types = ["Award", "Certification", "EducationalOccupationalCredential"]
    found_award_schema = False
    for block in json_ld_blocks:
        block_str = json.dumps(block)
        for ast in award_schema_types:
            if ast in block_str:
                found_award_schema = True
                break

    # Check for trust badges / certification images
    badge_keywords = ["badge", "certified", "award", "seal", "trust", "secure",
                     "accredited", "verified", "partner"]
    badge_images = []
    if soup:
        for img in soup.find_all("img"):
            alt = (img.get("alt") or "").lower()
            src = (img.get("src") or "").lower()
            for bk in badge_keywords:
                if bk in alt or bk in src:
                    badge_images.append(img.get("alt") or img.get("src", ""))
                    break

    if found_awards:
        unique_awards = list(set(found_awards))[:10]
        print(f"  [{PASS}] Award/accreditation signals found in content:")
        for kw in unique_awards:
            print(f"         • '{kw}'")
    else:
        print(f"  [{WARN}] No award/accreditation keywords detected in homepage content")

    if found_award_schema:
        print(f"  [{PASS}] Award/certification structured data found")
    else:
        print(f"  [{INFO}] No award-specific schema markup")

    if badge_images:
        print(f"  [{PASS}] Trust/certification badge images found ({len(badge_images)}):")
        for b in badge_images[:5]:
            print(f"         • {b}")
    else:
        print(f"  [{INFO}] No trust badge images detected")

    award_signals = len(found_awards) + (2 if found_award_schema else 0) + len(badge_images)
    if award_signals >= 5:
        authority_score += 5
        print(f"\n  Awards/accreditations: STRONG")
    elif award_signals >= 2:
        authority_score += 3
        print(f"\n  Awards/accreditations: MODERATE")
    else:
        print(f"\n  Awards/accreditations: WEAK")
        fix("Strengthen trust signals:\n"
            "  - Display certifications prominently (SOC2, GDPR, ISO, PCI-DSS)\n"
            "  - Add award badges with alt text: <img alt='2025 Best Fintech Award' ...>\n"
            "  - Add partner/affiliation logos (Y Combinator, accelerators, industry groups)\n"
            "  - Use structured data for awards:\n"
            '    {"@type": "Organization", "award": ["Best Fintech 2025", ...]}')

    # ── 3. Google Website Authority ──
    print(f"\n--- 3. Google Website Authority ---")
    max_score += 5

    # 3a. Check Google indexed page count via site: search
    print(f"  Checking Google index presence...")
    google_indexed = None
    try:
        google_url = f"https://www.google.com/search?q=site:{domain}"
        gr = requests.get(google_url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        })
        if gr.status_code == 200:
            # Try to extract result count from "About X results"
            count_match = re.search(r'About ([\d,]+) results', gr.text)
            if count_match:
                google_indexed = int(count_match.group(1).replace(",", ""))
                print(f"  [{PASS}] Google indexed pages: ~{google_indexed:,}")
            else:
                # Check if any results exist
                if "did not match any documents" in gr.text:
                    print(f"  [{FAIL}] Domain not indexed by Google")
                    google_indexed = 0
                else:
                    print(f"  [{INFO}] Google returned results but count not parseable (CAPTCHA or JS-rendered)")
        elif gr.status_code == 429:
            print(f"  [{INFO}] Google rate-limited the request — try 'site:{domain}' in your browser")
        else:
            print(f"  [{INFO}] Could not query Google (status {gr.status_code})")
    except requests.RequestException:
        print(f"  [{INFO}] Could not reach Google — check manually: site:{domain}")

    # 3b. Check for Google Knowledge Panel signals
    print(f"  Checking Knowledge Panel readiness...")
    kg_signals = 0
    # Check Organization schema completeness
    for block in json_ld_blocks:
        block_type = block.get("@type", "")
        if block_type in ("Organization", "Corporation", "LocalBusiness"):
            fields = ["name", "url", "logo", "description", "sameAs",
                      "contactPoint", "founder", "foundingDate", "address"]
            present = [f for f in fields if block.get(f)]
            kg_signals = len(present)
            print(f"  [{PASS}] Organization schema: {len(present)}/{len(fields)} fields")
            missing = [f for f in fields if not block.get(f)]
            if missing:
                print(f"         Missing: {', '.join(missing)}")
            break

    # Check Wikipedia/Wikidata presence (strong Knowledge Panel signal)
    wiki_found = False
    if soup:
        for a in soup.find_all("a", href=True):
            href = a["href"].lower()
            if "wikipedia.org" in href or "wikidata.org" in href:
                wiki_found = True
                print(f"  [{PASS}] Links to Wikipedia/Wikidata — strong entity signal")
                break
    for block in json_ld_blocks:
        same_as = block.get("sameAs", [])
        if isinstance(same_as, str):
            same_as = [same_as]
        for link in same_as:
            if "wikipedia.org" in link or "wikidata.org" in link:
                wiki_found = True
                print(f"  [{PASS}] Wikipedia/Wikidata in sameAs — strong entity signal")
                break

    if not wiki_found:
        print(f"  [{INFO}] No Wikipedia/Wikidata links — consider creating entries for brand recognition")

    google_score = 0
    if google_indexed and google_indexed >= 50:
        google_score += 2
    elif google_indexed and google_indexed >= 10:
        google_score += 1
    google_score += min(kg_signals, 3)  # up to 3 points for schema
    if wiki_found:
        google_score += 1

    authority_score += min(google_score, 5)
    if google_score >= 4:
        print(f"\n  Google authority signals: STRONG")
    elif google_score >= 2:
        print(f"\n  Google authority signals: MODERATE")
    else:
        print(f"\n  Google authority signals: WEAK")
        fix("Boost Google authority:\n"
            "  - Complete your Organization schema (all 9 fields)\n"
            "  - Create a Wikipedia article for your brand/product\n"
            "  - Create a Wikidata entity and link it in sameAs\n"
            "  - Claim your Google Business Profile\n"
            "  - Build high-quality backlinks from authoritative domains")

    # ── 4. Authoritative List Mentions ──
    print(f"\n--- 4. Authoritative List Mentions ---")
    max_score += 5

    # Check if the domain appears on authoritative platforms
    authority_sources = {
        "GitHub":         f"https://api.github.com/search/repositories?q={brand}&per_page=3",
        "npm":            f"https://registry.npmjs.org/{brand}",
        "PyPI":           f"https://pypi.org/pypi/{brand}/json",
        "Crunchbase":     f"https://www.crunchbase.com/organization/{brand}",
        "LinkedIn":       f"https://www.linkedin.com/company/{brand}",
        "AngelList":      f"https://wellfound.com/company/{brand}",
        "HackerNews":     f"https://hn.algolia.com/api/v1/search?query={domain}&tags=story",
    }

    found_mentions = []
    for source, check_url in authority_sources.items():
        try:
            r = requests.get(check_url, timeout=10, allow_redirects=True, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            })
            if source == "HackerNews":
                # JSON API — check for actual hits
                try:
                    hn_data = r.json()
                    hits = hn_data.get("nbHits", 0)
                    if hits > 0:
                        found_mentions.append(source)
                        print(f"  [{PASS}] {source} — {hits} mention(s)")
                    else:
                        print(f"  [{INFO}] {source} — no mentions")
                except (json.JSONDecodeError, ValueError):
                    print(f"  [{INFO}] {source} — could not parse response")
            elif source == "npm":
                # npm registry API returns JSON for existing packages
                if r.status_code == 200:
                    try:
                        pkg = r.json()
                        if pkg.get("name"):
                            found_mentions.append(source)
                            desc = pkg.get("description", "")[:60]
                            print(f"  [{PASS}] {source} — package found: {pkg['name']}")
                            if desc:
                                print(f"         {desc}")
                        else:
                            print(f"  [{INFO}] {source} — not found")
                    except (json.JSONDecodeError, ValueError):
                        print(f"  [{INFO}] {source} — not found")
                else:
                    print(f"  [{INFO}] {source} — not found")
            elif source == "PyPI":
                # PyPI JSON API returns package metadata
                if r.status_code == 200:
                    try:
                        pkg = r.json()
                        info = pkg.get("info", {})
                        if info.get("name"):
                            found_mentions.append(source)
                            desc = info.get("summary", "")[:60]
                            print(f"  [{PASS}] {source} — package found: {info['name']}")
                            if desc:
                                print(f"         {desc}")
                        else:
                            print(f"  [{INFO}] {source} — not found")
                    except (json.JSONDecodeError, ValueError):
                        print(f"  [{INFO}] {source} — not found")
                else:
                    print(f"  [{INFO}] {source} — not found")
            elif source == "Crunchbase":
                if r.status_code == 200 and brand in r.text.lower():
                    found_mentions.append(source)
                    print(f"  [{PASS}] {source} — profile found")
                else:
                    print(f"  [{INFO}] {source} — no profile found")
            elif source == "LinkedIn":
                # LinkedIn often blocks/redirects
                if r.status_code == 200:
                    found_mentions.append(source)
                    print(f"  [{PASS}] {source} — company page found")
                else:
                    print(f"  [{INFO}] {source} — not detected (may require login)")
            elif source == "GitHub":
                # GitHub search API returns JSON with matching repos
                if r.status_code == 200:
                    try:
                        data = r.json()
                        total = data.get("total_count", 0)
                        if total > 0:
                            found_mentions.append(source)
                            top = data["items"][0]
                            print(f"  [{PASS}] {source} — {total} repo(s) found, top: {top['full_name']}")
                        else:
                            print(f"  [{INFO}] {source} — not found")
                    except (json.JSONDecodeError, ValueError, KeyError):
                        print(f"  [{INFO}] {source} — could not check")
                else:
                    print(f"  [{INFO}] {source} — not found")
            else:
                if r.status_code == 200 and (brand in r.text.lower() or domain in r.text.lower()):
                    found_mentions.append(source)
                    print(f"  [{PASS}] {source} — found")
                else:
                    print(f"  [{INFO}] {source} — not found")
        except requests.RequestException:
            print(f"  [{INFO}] {source} — could not check")

    # Check for .gov / .edu / .org backlink signals on the page
    if soup:
        authority_outlinks = []
        for a in soup.find_all("a", href=True):
            href = a["href"].lower()
            for ext in [".gov", ".edu", ".org"]:
                if ext in href and domain not in href:
                    authority_outlinks.append(href)
                    break
        if authority_outlinks:
            unique_auth = list(set(authority_outlinks))[:5]
            print(f"  [{PASS}] Links to {len(set(authority_outlinks))} authoritative domain(s) (.gov/.edu/.org)")

    if len(found_mentions) >= 4:
        authority_score += 5
        print(f"\n  Authoritative mentions: STRONG ({len(found_mentions)} platforms)")
    elif len(found_mentions) >= 2:
        authority_score += 3
        print(f"\n  Authoritative mentions: MODERATE ({len(found_mentions)} platform(s))")
    else:
        authority_score += 1
        print(f"\n  Authoritative mentions: WEAK ({len(found_mentions)} platform(s))")
        fix("Increase your presence on authoritative platforms:\n"
            "  - Create a Crunchbase profile for your company\n"
            "  - Maintain an active GitHub organization\n"
            "  - Publish packages on npm/PyPI if applicable\n"
            "  - Get mentioned on Hacker News (Show HN posts)\n"
            "  - Submit to startup directories (Product Hunt, AngelList/Wellfound)\n"
            "  - Seek mentions in industry publications and comparison lists")

    # ── Final Score ──
    print(f"\n{'='*60}")
    print(f"  Authority Score: {authority_score}/{max_score}")
    pct = (authority_score / max_score * 100) if max_score > 0 else 0
    if pct >= 80:
        grade = "A — Excellent"
    elif pct >= 60:
        grade = "B — Good"
    elif pct >= 40:
        grade = "C — Needs improvement"
    elif pct >= 20:
        grade = "D — Weak"
    else:
        grade = "F — Critical gaps"
    print(f"  Grade: {grade}")
    print(f"\n  Breakdown:")
    print(f"    Online Reviews:         {'checked' :>10}")
    print(f"    Awards/Accreditations:  {'checked' :>10}")
    print(f"    Google Authority:       {'checked' :>10}")
    print(f"    Authoritative Mentions: {'checked' :>10}")
    print(f"{'='*60}\n")

    if return_data:
        return {
            "url": base_url,
            "domain": domain,
            "brand": brand,
            "score": authority_score,
            "max_score": max_score,
            "percent": round(pct, 1),
            "grade": grade,
            "reviews": {
                "platforms": list(dict.fromkeys(found_platforms)),
                "has_schema": has_review_schema,
            },
            "awards": {
                "keywords": list(set(found_awards)),
                "has_schema": found_award_schema,
                "badges": badge_images[:10],
                "signal_count": award_signals,
            },
            "google": {
                "indexed_pages": google_indexed,
                "kg_schema_fields": kg_signals,
                "wikipedia_or_wikidata": wiki_found,
                "score": google_score,
            },
            "mentions": {
                "platforms": found_mentions,
            },
        }


# ---------------------------------------------------------------------------
# AI Citation Check (PAID feature — requires OPENROUTER_API_KEY)
# ---------------------------------------------------------------------------
def citation_check(url, return_data=False):
    """Check if a site is being cited by AI engines using the OpenRouter API.

    When return_data=True, returns a dict with per-query citation results +
    overall citation rate. Raises RuntimeError on missing/invalid API key
    instead of sys.exit.
    """
    import os

    parsed = urlparse(url)
    if not parsed.scheme:
        url = "https://" + url
        parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    domain = parsed.netloc.replace("www.", "")
    brand = domain.split(".")[0]

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        if return_data:
            raise RuntimeError("OPENROUTER_API_KEY not set")
        print(f"\n  [{FAIL}] OPENROUTER_API_KEY environment variable not set.")
        print(f"  This is a paid feature. Set your API key to use it:")
        print(f"    export OPENROUTER_API_KEY='your-openrouter-api-key'")
        print(f"  Get an API key at: https://openrouter.ai/")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  AI Citation Check (Powered by OpenRouter)")
    print(f"  Target: {base_url}")
    print(f"  Domain: {domain} | Brand: {brand}")
    print(f"{'='*60}")
    print(f"\n  Sending brand-relevant queries to Perplexity AI via OpenRouter...")
    print(f"  Checking if {domain} appears in AI-generated citations...\n")

    # Build queries that should surface the brand if AI engines know about it
    queries = [
        f"What is {brand}?",
        f"What does {domain} do?",
        f"{brand} review",
        f"Best alternatives to {brand}",
        f"Is {brand} reliable and trustworthy?",
    ]

    # Fetch homepage to detect what the site is about for a category query
    resp, soup = get_soup(base_url)
    if soup:
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            desc = meta_desc["content"].strip()
            # Extract a short topic from the meta description
            if len(desc) > 10:
                queries.append(f"Best tools for {desc[:80]}")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    api_url = "https://openrouter.ai/api/v1/chat/completions"

    total_queries = len(queries)
    cited_count = 0
    total_citations = 0
    results = []

    for i, query in enumerate(queries, 1):
        print(f"  [{INFO}] Query {i}/{total_queries}: \"{query}\"")

        payload = {
            "model": "perplexity/sonar",
            "messages": [
                {"role": "user", "content": query}
            ],
        }

        try:
            r = requests.post(api_url, json=payload, headers=headers, timeout=30)
            if r.status_code == 401:
                if return_data:
                    raise RuntimeError("Invalid OPENROUTER_API_KEY")
                print(f"  [{FAIL}] Invalid API key. Check your OPENROUTER_API_KEY.")
                sys.exit(1)
            elif r.status_code == 429:
                print(f"  [{WARN}] Rate limited. Waiting before next query...")
                time.sleep(5)
                r = requests.post(api_url, json=payload, headers=headers, timeout=30)
            if r.status_code != 200:
                err_body = r.text[:200] if r.text else ""
                print(f"    [{WARN}] API error (HTTP {r.status_code}), skipping this query")
                results.append({
                    "query": query,
                    "cited": False,
                    "citations": [],
                    "error": True,
                    "upstream_status": r.status_code,
                    "upstream_body": err_body,
                })
                continue

            data = r.json()
            # Extract citations from the response
            citations = []
            # Also check the answer text for domain mentions
            answer = ""
            choices = data.get("choices", [])
            if choices:
                answer = choices[0].get("message", {}).get("content", "")

            # Check if our domain appears in citations
            domain_citations = []
            # Extract citations from the answer text
            import re
            url_pattern = re.compile(r'https?://[\w\-\.]+\.[a-z]{2,}/\S*')
            found_urls = url_pattern.findall(answer)
            for url in found_urls:
                if domain in url:
                    domain_citations.append(url)

            domain_in_text = domain in answer.lower() or brand.lower() in answer.lower()

            if domain_citations:
                cited_count += 1
                total_citations += len(domain_citations)
                print(f"    [{PASS}] CITED! {len(domain_citations)} citation(s) from {domain}")
                for c in domain_citations:
                    print(f"           → {c}")
            elif domain_in_text:
                cited_count += 1
                print(f"    [{PASS}] MENTIONED in answer (no direct citation link)")
            else:
                print(f"    [{WARN}] Not cited. Found {len(found_urls)} other source(s) instead.")
                if found_urls:
                    for c in found_urls[:3]:
                        print(f"           → {c}")
                    if len(found_urls) > 3:
                        print(f"           ... and {len(found_urls) - 3} more")

            results.append({
                "query": query,
                "cited": bool(domain_citations or domain_in_text),
                "citations": domain_citations,
                "mentioned": domain_in_text,
                "total_sources": len(found_urls),
                "error": False,
            })

        except requests.RequestException as e:
            print(f"    [{FAIL}] Request failed: {e}")
            results.append({"query": query, "cited": False, "citations": [], "error": True})

        # Brief pause between queries to avoid rate limiting
        if i < total_queries:
            time.sleep(1)

    # ── Summary ──
    valid_results = [r for r in results if not r.get("error")]
    valid_count = len(valid_results)

    print(f"\n{'='*60}")
    print(f"  AI CITATION REPORT")
    print(f"{'='*60}")

    if valid_count == 0:
        print(f"  [{FAIL}] No queries completed successfully.")
        print(f"{'='*60}\n")
        if return_data:
            first_err = next((r for r in results if r.get("error")), {})
            upstream_status = first_err.get("upstream_status")
            upstream_body = first_err.get("upstream_body", "")
            msg = "All citation queries failed — upstream AI API returned no valid responses"
            if upstream_status:
                msg += f" (upstream HTTP {upstream_status})"
            if upstream_body:
                msg += f": {upstream_body}"
            msg += ". Check OPENROUTER_API_KEY quota and network connectivity."
            raise RuntimeError(msg)
        return

    citation_rate = (cited_count / valid_count * 100) if valid_count > 0 else 0

    print(f"\n  Citation Rate:  {cited_count}/{valid_count} queries ({citation_rate:.0f}%)")
    print(f"  Direct Links:   {total_citations} citation(s) pointing to {domain}")

    # Grade the citation presence
    if citation_rate >= 80:
        grade = "A — Excellent AI visibility"
        bar_color = "\033[92m"  # green
    elif citation_rate >= 60:
        grade = "B — Good AI visibility"
        bar_color = "\033[92m"
    elif citation_rate >= 40:
        grade = "C — Moderate AI visibility"
        bar_color = "\033[93m"  # yellow
    elif citation_rate >= 20:
        grade = "D — Low AI visibility"
        bar_color = "\033[93m"
    else:
        grade = "F — Not visible to AI engines"
        bar_color = "\033[91m"  # red

    bar_len = int(citation_rate / 5)
    bar = bar_color + "█" * bar_len + "\033[0m" + "░" * (20 - bar_len)
    print(f"  AI Visibility:  {bar}  {citation_rate:.0f}%")
    print(f"  Grade:          {grade}")

    # Per-query breakdown
    print(f"\n  Query Results:")
    for r in results:
        if r.get("error"):
            status = f"[{WARN}] ERROR"
        elif r["cited"]:
            status = f"[{PASS}] CITED"
        else:
            status = f"[{FAIL}] NOT CITED"
        print(f"    {status}  \"{r['query']}\"")

    # Recommendations
    if citation_rate < 60:
        print(f"\n  Recommendations to improve AI citation rate:")
        print(f"    • Ensure your site has comprehensive, authoritative content about your brand")
        print(f"    • Add structured data (JSON-LD) with Organization schema")
        print(f"    • Create an llms.txt file to help AI engines understand your site")
        print(f"    • Build presence on platforms AI models reference (Wikipedia, Reddit, GitHub)")
        print(f"    • Publish original research, data, and expert content that AI engines want to cite")
        print(f"    • Ensure AI crawlers (GPTBot, ClaudeBot, PerplexityBot) are not blocked in robots.txt")

    print(f"\n  Note: Results reflect Perplexity AI's current knowledge. Other AI engines")
    print(f"  (ChatGPT, Gemini, Claude) may differ. Run periodically to track changes.")
    print(f"{'='*60}\n")

    if return_data:
        if citation_rate >= 80:
            grade_letter = "A"
        elif citation_rate >= 60:
            grade_letter = "B"
        elif citation_rate >= 40:
            grade_letter = "C"
        elif citation_rate >= 20:
            grade_letter = "D"
        else:
            grade_letter = "F"
        return {
            "url": base_url,
            "domain": domain,
            "brand": brand,
            "engine": "Perplexity",
            "total_queries": total_queries,
            "valid_queries": valid_count,
            "cited_queries": cited_count,
            "citation_rate": round(citation_rate, 1),
            "total_citations": total_citations,
            "grade": grade_letter,
            "queries": results,
        }


# ---------------------------------------------------------------------------
# AI Visibility Audit v2 (PAID — requires at least one AI API key)
# ---------------------------------------------------------------------------

def _query_perplexity(query, api_key):
    """Send a query to Perplexity Sonar via OpenRouter. Returns (answer, citations, error)."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "perplexity/sonar",
        "messages": [{"role": "user", "content": query}],
    }
    try:
        r = requests.post("https://openrouter.ai/api/v1/chat/completions",
                          json=payload, headers=headers, timeout=45)
        if r.status_code == 401:
            return "", [], "invalid_key"
        if r.status_code == 429:
            time.sleep(5)
            r = requests.post("https://openrouter.ai/api/v1/chat/completions",
                              json=payload, headers=headers, timeout=45)
        if r.status_code != 200:
            return "", [], f"http_{r.status_code}"
        data = r.json()
        answer = ""
        choices = data.get("choices", [])
        if choices:
            answer = choices[0].get("message", {}).get("content", "")
        import re
        url_pattern = re.compile(r'https?://[\w\-\.]+\.[a-z]{2,}/\S*')
        citations = list(dict.fromkeys(url_pattern.findall(answer)))
        return answer, citations, None
    except requests.RequestException as e:
        return "", [], str(e)


def _query_openai(query, api_key):
    """Send a query to OpenAI API via OpenRouter with web search. Returns (answer, citations, error)."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "openai/gpt-4o-mini:online",
        "messages": [
            {"role": "user", "content": query}
        ],
    }
    try:
        r = requests.post("https://openrouter.ai/api/v1/chat/completions",
                          json=payload, headers=headers, timeout=45)
        if r.status_code == 401:
            return "", [], "invalid_key"
        if r.status_code == 429:
            time.sleep(5)
            r = requests.post("https://openrouter.ai/api/v1/chat/completions",
                              json=payload, headers=headers, timeout=45)
        if r.status_code != 200:
            return "", [], f"http_{r.status_code}"
        data = r.json()
        answer = ""
        citations = []
        choices = data.get("choices", [])
        if choices:
            answer = choices[0].get("message", {}).get("content", "")
            # Extract citations from the answer text
            import re
            url_pattern = re.compile(r'https?://[\w\-\.]+\.[a-z]{2,}/\S*')
            citations = url_pattern.findall(answer)
        citations = list(dict.fromkeys(citations))  # dedupe preserving order
        # Fallback: extract URLs from answer text
        if not citations:
            url_pattern = re.findall(r'https?://[^\s\)\]]+', answer)
            citations = list(set(url_pattern))
        return answer, citations, None
    except requests.RequestException as e:
        return "", [], str(e)


def _query_anthropic(query, api_key):
    """Send a query to Anthropic Claude API via OpenRouter with web search. Returns (answer, citations, error)."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "anthropic/claude-sonnet-4:online",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": query}],
    }
    try:
        r = requests.post("https://openrouter.ai/api/v1/chat/completions",
                          json=payload, headers=headers, timeout=45)
        if r.status_code == 401:
            return "", [], "invalid_key"
        if r.status_code == 429:
            time.sleep(5)
            r = requests.post("https://openrouter.ai/api/v1/chat/completions",
                              json=payload, headers=headers, timeout=45)
        if r.status_code != 200:
            return "", [], f"http_{r.status_code}"
        data = r.json()
        answer = ""
        citations = []
        choices = data.get("choices", [])
        if choices:
            answer = choices[0].get("message", {}).get("content", "")
            # Extract citations from the answer text
            import re
            url_pattern = re.compile(r'https?://[\w\-\.]+\.[a-z]{2,}/\S*')
            citations = url_pattern.findall(answer)
        citations = list(dict.fromkeys(citations))  # dedupe preserving order
        return answer, citations, None
    except requests.RequestException as e:
        return "", [], str(e)


def _query_deepseek(query, api_key):
    """Send a query to DeepSeek API. Returns (answer, citations, error)."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": query}],
    }
    try:
        r = requests.post("https://api.deepseek.com/chat/completions",
                          json=payload, headers=headers, timeout=30)
        if r.status_code == 401:
            return "", [], "invalid_key"
        if r.status_code == 429:
            time.sleep(5)
            r = requests.post("https://api.deepseek.com/chat/completions",
                              json=payload, headers=headers, timeout=30)
        if r.status_code != 200:
            return "", [], f"http_{r.status_code}"
        data = r.json()
        answer = ""
        choices = data.get("choices", [])
        if choices:
            answer = choices[0].get("message", {}).get("content", "")
        # No built-in web search — extract URLs from answer text
        citations = list(dict.fromkeys(re.findall(r'https?://[^\s\)\]>]+', answer)))
        return answer, citations, None
    except requests.RequestException as e:
        return "", [], str(e)


def _query_doubao(query, api_key, model_id):
    """Send a query to Doubao (ByteDance Ark) API. Returns (answer, citations, error)."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": query}],
    }
    try:
        r = requests.post("https://ark.cn-beijing.volces.com/api/v3/chat/completions",
                          json=payload, headers=headers, timeout=30)
        if r.status_code == 401:
            return "", [], "invalid_key"
        if r.status_code == 429:
            time.sleep(5)
            r = requests.post("https://ark.cn-beijing.volces.com/api/v3/chat/completions",
                              json=payload, headers=headers, timeout=30)
        if r.status_code != 200:
            return "", [], f"http_{r.status_code}"
        data = r.json()
        answer = ""
        choices = data.get("choices", [])
        if choices:
            answer = choices[0].get("message", {}).get("content", "")
        # No built-in web search — extract URLs from answer text
        citations = list(dict.fromkeys(re.findall(r'https?://[^\s\)\]>]+', answer)))
        return answer, citations, None
    except requests.RequestException as e:
        return "", [], str(e)


def _check_brand_in_result(answer, citations, domain, brand):
    """Check if brand/domain appears in answer or citations. Returns dict with details."""
    domain_citations = [c for c in citations if domain in c]
    brand_lower = brand.lower()
    answer_lower = answer.lower()
    mentioned_in_text = domain in answer_lower or brand_lower in answer_lower
    return {
        "domain_citations": domain_citations,
        "mentioned_in_text": mentioned_in_text,
        "cited": bool(domain_citations) or mentioned_in_text,
        "all_citations": citations,
    }


def _extract_competitors(citations, answer, domain):
    """Extract competitor domains from citations and answer text."""
    competitors = {}
    for c in citations:
        try:
            comp_domain = urlparse(c).netloc.replace("www.", "")
            if comp_domain and comp_domain != domain and "." in comp_domain:
                # Skip common non-competitor domains
                skip = ["google.com", "youtube.com", "wikipedia.org", "reddit.com",
                        "twitter.com", "x.com", "facebook.com", "linkedin.com",
                        "medium.com", "github.com", "stackoverflow.com", "quora.com",
                        "amazon.com", "yelp.com", "bbb.org", "trustpilot.com"]
                if comp_domain not in skip:
                    competitors[comp_domain] = competitors.get(comp_domain, 0) + 1
        except Exception:
            pass
    return competitors


def _classify_framing(answer, brand):
    """Classify how the AI frames the brand in its answer."""
    answer_lower = answer.lower()
    brand_lower = brand.lower()

    if brand_lower not in answer_lower:
        return "not_mentioned"

    # Check for recommendation language (strongest)
    rec_patterns = [
        f"recommend {brand_lower}", f"use {brand_lower}", f"consider {brand_lower}",
        f"try {brand_lower}", f"choose {brand_lower}", f"go with {brand_lower}",
        f"{brand_lower} is the best", f"{brand_lower} is a leading",
        f"{brand_lower} is a top", f"{brand_lower} stands out",
    ]
    for pat in rec_patterns:
        if pat in answer_lower:
            return "recommended"

    # Check for leader framing
    leader_patterns = [
        f"{brand_lower} is a leader", f"{brand_lower} is one of the leading",
        f"{brand_lower} is a major", f"{brand_lower} is a popular",
        f"{brand_lower} is well-known", f"{brand_lower} is widely used",
        f"{brand_lower} is a prominent",
    ]
    for pat in leader_patterns:
        if pat in answer_lower:
            return "leader"

    # Check for option/alternative framing
    option_patterns = [
        f"{brand_lower} is an option", f"{brand_lower} is one option",
        f"{brand_lower} is an alternative", f"alternative.*{brand_lower}",
        f"options.*{brand_lower}", f"include.*{brand_lower}",
        f"{brand_lower} is another",
    ]
    for pat in option_patterns:
        if re.search(pat, answer_lower):
            return "option"

    # Check for niche/experimental framing
    niche_patterns = [
        f"{brand_lower} is a niche", f"{brand_lower} is experimental",
        f"{brand_lower} is a newer", f"{brand_lower} is a small",
        f"{brand_lower} is relatively new", f"{brand_lower} is emerging",
    ]
    for pat in niche_patterns:
        if pat in answer_lower:
            return "niche"

    return "mentioned"


def ai_visibility(url, custom_queries=None, return_data=False):
    """Comprehensive AI Visibility Audit — checks if AI would recommend the brand.

    When return_data=True, returns a dict with scorecard + per-engine visibility
    rates, top competitors, framings, and content gaps. Raises RuntimeError on
    missing API keys instead of sys.exit.
    """
    import os

    parsed = urlparse(url)
    if not parsed.scheme:
        url = "https://" + url
        parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    domain = parsed.netloc.replace("www.", "")
    brand = domain.split(".")[0]

    # Detect available AI engines (using OpenRouter)
    engines = {}
    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    doubao_key = os.environ.get("DOUBAO_API_KEY", "").strip()
    doubao_model = os.environ.get("DOUBAO_MODEL_ID", "").strip()

    if openrouter_key:
        engines["Perplexity"] = ("perplexity", openrouter_key)
        engines["ChatGPT"] = ("openai", openrouter_key)
        engines["Claude"] = ("anthropic", openrouter_key)
    if deepseek_key:
        engines["DeepSeek"] = ("deepseek", deepseek_key)
    if doubao_key and doubao_model:
        engines["Doubao"] = ("doubao", doubao_key)
    elif doubao_key and not doubao_model:
        print(f"  [{WARN}] DOUBAO_API_KEY set but DOUBAO_MODEL_ID missing — skipping Doubao")
        print(f"           Set your endpoint ID: export DOUBAO_MODEL_ID='ep-20240...'")

    if not engines:
        if return_data:
            raise RuntimeError("OPENROUTER_API_KEY not set")
        print(f"\n  [{FAIL}] No AI API keys found. Set at least one:")
        print(f"    export OPENROUTER_API_KEY='your-key'   (recommended — Perplexity+ChatGPT+Claude)")
        print(f"    export DEEPSEEK_API_KEY='sk-...'")
        print(f"    export DOUBAO_API_KEY='...'  + DOUBAO_MODEL_ID='ep-...'")
        print(f"\n  This is a paid feature requiring AI API access.")
        sys.exit(1)

    engine_names = ", ".join(engines.keys())

    print(f"\n{'='*60}")
    print(f"  AI VISIBILITY AUDIT v2")
    print(f"  Target: {base_url}")
    print(f"  Domain: {domain} | Brand: {brand}")
    print(f"  Engines: {engine_names}")
    print(f"{'='*60}")

    # ── Build query sets ──
    # Category 1: Entity definition queries
    entity_queries = [
        f"What is {brand}?",
        f"What does {domain} do?",
        f"Who is {brand} for?",
    ]

    # Category 2: Competitive/recommendation queries
    competitive_queries = [
        f"Best alternatives to {brand}",
        f"{brand} review",
        f"Is {brand} reliable and trustworthy?",
    ]

    # Category 3: Category association queries (derived from site meta)
    category_queries = []
    resp, soup = get_soup(base_url)
    site_description = ""
    if soup:
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            site_description = meta_desc["content"].strip()
        # Also check title for category hints
        title_tag = soup.find("title")
        title_text = title_tag.get_text(strip=True) if title_tag else ""
        if site_description and len(site_description) > 10:
            category_queries.append(f"Best tools for {site_description[:80]}")
        if title_text and brand.lower() in title_text.lower():
            # Extract what comes after brand in title
            parts = title_text.lower().split(brand.lower(), 1)
            if len(parts) > 1 and len(parts[1].strip(" -—|:")) > 5:
                suffix = parts[1].strip(" -—|:").strip()[:60]
                category_queries.append(f"Best {suffix} tools")

    # Category 4: Custom queries from user
    user_queries = list(custom_queries) if custom_queries else []

    # Category 5: Gap detection queries (generic industry queries where brand should appear)
    gap_queries = []
    if site_description:
        # Build queries from site's own description that it should rank for
        gap_queries.append(f"Top {site_description[:50].split(',')[0].strip()} solutions")
    gap_queries.append(f"Best {brand} competitors 2025")

    all_query_groups = {
        "Entity Definition": entity_queries,
        "Competitive": competitive_queries,
        "Category Association": category_queries,
        "Custom": user_queries,
        "Gap Detection": gap_queries,
    }
    # Remove empty groups
    all_query_groups = {k: v for k, v in all_query_groups.items() if v}

    all_queries = []
    query_group_map = {}  # query -> group name
    for group, queries in all_query_groups.items():
        for q in queries:
            all_queries.append(q)
            query_group_map[q] = group

    total_api_calls = len(all_queries) * len(engines) * 3  # 3 runs for stability
    print(f"\n  Total queries: {len(all_queries)} x {len(engines)} engine(s) x 3 runs = {total_api_calls} API calls")
    print(f"  Estimated time: ~{total_api_calls * 2}s\n")

    # ── Query dispatcher ──
    def query_engine(query, engine_type, api_key):
        if engine_type == "perplexity":
            return _query_perplexity(query, api_key)
        elif engine_type == "openai":
            return _query_openai(query, api_key)
        elif engine_type == "anthropic":
            return _query_anthropic(query, api_key)
        elif engine_type == "deepseek":
            return _query_deepseek(query, api_key)
        elif engine_type == "doubao":
            return _query_doubao(query, api_key, doubao_model)
        return "", [], "unknown_engine"

    # ── Run all queries across all engines, 3x each for stability (parallel) ──
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading

    STABILITY_RUNS = 3

    def _make_error_entry():
        return {
            "answer": "", "citations": [], "error": True,
            "brand_result": {"cited": False, "domain_citations": [],
                             "mentioned_in_text": False, "all_citations": []},
            "framing": "not_mentioned",
        }

    # Pre-fill every slot with an error placeholder so downstream scoring can
    # uniformly read all_results[eng][query][run_idx] even if a task is skipped.
    all_results = {
        eng: {q: [_make_error_entry() for _ in range(STABILITY_RUNS)] for q in all_queries}
        for eng in engines
    }
    global_competitors = {}
    all_framings = []

    dead_engines = set()
    dead_lock = threading.Lock()

    def _run_one(eng_name, eng_type, api_key, query, run_idx):
        with dead_lock:
            if eng_name in dead_engines:
                return eng_name, query, run_idx, None
        answer, citations, error = query_engine(query, eng_type, api_key)
        if error == "invalid_key":
            with dead_lock:
                dead_engines.add(eng_name)
            return eng_name, query, run_idx, None
        if error:
            return eng_name, query, run_idx, None
        brand_result = _check_brand_in_result(answer, citations, domain, brand)
        framing = _classify_framing(answer, brand)
        competitors = _extract_competitors(citations, answer, domain)
        return eng_name, query, run_idx, {
            "answer": answer, "citations": citations, "error": False,
            "brand_result": brand_result, "framing": framing,
            "competitors": competitors,
        }

    tasks = [
        (eng_name, eng_type, api_key, query, run_idx)
        for eng_name, (eng_type, api_key) in engines.items()
        for query in all_queries
        for run_idx in range(STABILITY_RUNS)
    ]

    print(f"\n  Running {len(tasks)} API calls in parallel (max 8 concurrent)...")

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_run_one, *t) for t in tasks]
        for fut in as_completed(futures):
            eng_name, query, run_idx, result = fut.result()
            if result is None:
                continue  # keep error placeholder
            all_results[eng_name][query][run_idx] = result
            all_framings.append(result["framing"])
            for comp, count in result.get("competitors", {}).items():
                global_competitors[comp] = global_competitors.get(comp, 0) + count

    # Per-engine, per-query summary
    for eng_name in engines:
        print(f"\n--- Engine: {eng_name} ---")
        if eng_name in dead_engines:
            print(f"  [{FAIL}] Invalid {eng_name} API key. Engine skipped.")
            continue
        for query in all_queries:
            group = query_group_map[query]
            print(f"  [{INFO}] [{group}] \"{query}\"")
            run_results = all_results[eng_name][query]
            valid_runs = [r for r in run_results if not r.get("error")]
            cited_runs = sum(1 for r in valid_runs if r["brand_result"]["cited"])
            if len(valid_runs) == 0:
                print(f"    [{FAIL}] All runs failed")
            elif cited_runs == STABILITY_RUNS:
                print(f"    [{PASS}] STABLE — cited in {cited_runs}/{STABILITY_RUNS} runs")
            elif cited_runs > 0:
                print(f"    [{WARN}] UNSTABLE — cited in {cited_runs}/{STABILITY_RUNS} runs")
            else:
                print(f"    [{FAIL}] NOT CITED in any run")
            framings_this = [r["framing"] for r in valid_runs if r["framing"] != "not_mentioned"]
            if framings_this:
                primary_framing = max(set(framings_this), key=framings_this.count)
                print(f"           Framing: {primary_framing}")

    # ══════════════════════════════════════════════════════════════
    # ANALYSIS & SCORING
    # ══════════════════════════════════════════════════════════════

    print(f"\n{'='*60}")
    print(f"  AI VISIBILITY AUDIT — RESULTS")
    print(f"{'='*60}")

    # ── 1. Prompt Visibility Score (0-20) ──
    print(f"\n--- 1. Prompt Visibility ---")
    total_query_cited = 0
    total_query_count = 0
    per_engine_rates = {}

    for eng_name in engines:
        eng_cited = 0
        eng_total = 0
        for query in all_queries:
            runs = all_results[eng_name].get(query, [])
            valid_runs = [r for r in runs if not r.get("error")]
            if valid_runs:
                eng_total += 1
                # Cited if majority of runs cite it
                cited_count = sum(1 for r in valid_runs if r["brand_result"]["cited"])
                if cited_count > len(valid_runs) / 2:
                    eng_cited += 1
                    total_query_cited += 1
                total_query_count += 1
        rate = (eng_cited / eng_total * 100) if eng_total > 0 else 0
        per_engine_rates[eng_name] = rate
        print(f"  {eng_name}: {eng_cited}/{eng_total} queries cited ({rate:.0f}%)")

    overall_cite_rate = (total_query_cited / total_query_count * 100) if total_query_count > 0 else 0
    visibility_score = round(overall_cite_rate / 5)  # 0-20
    print(f"  Overall: {overall_cite_rate:.0f}% → {visibility_score}/20 pts")

    # ── 2. Entity Clarity Score (0-20) ──
    print(f"\n--- 2. Entity Clarity ---")
    entity_score = 0
    entity_max = 20
    entity_answers = []

    for eng_name in engines:
        for query in entity_queries:
            runs = all_results[eng_name].get(query, [])
            valid_runs = [r for r in runs if not r.get("error")]
            for r in valid_runs:
                if r["brand_result"]["cited"] or r["brand_result"]["mentioned_in_text"]:
                    entity_answers.append(r["answer"][:500])

    if entity_answers:
        # Check consistency: do answers agree on what the brand is?
        # Simple approach: check if key phrases repeat across answers
        brand_lower = brand.lower()
        definitions = []
        for ans in entity_answers:
            ans_lower = ans.lower()
            # Extract the sentence containing the brand definition
            sentences = re.split(r'[.!?\n]', ans)
            for s in sentences:
                s_lower = s.lower().strip()
                if brand_lower in s_lower and ("is " in s_lower or "provides" in s_lower
                                                or "offers" in s_lower or "platform" in s_lower
                                                or "tool" in s_lower or "service" in s_lower):
                    definitions.append(s.strip())
                    break

        if definitions:
            print(f"  Found {len(definitions)} definition(s) across engines:")
            seen_defs = []
            for d in definitions[:6]:
                short = d[:120] + "..." if len(d) > 120 else d
                if short not in seen_defs:
                    seen_defs.append(short)
                    print(f"    \"{short}\"")

            # Score: definitions exist = 8pts, multiple consistent = up to 12 more
            entity_score += 8
            if len(definitions) >= 3:
                entity_score += 6
            if len(definitions) >= 6:
                entity_score += 6
        else:
            print(f"  [{WARN}] No clear definitions found in AI answers")
            entity_score += 2

        # Check for brand confusion
        confusion_terms = ["wallet", "exchange", "cryptocurrency exchange", "trading platform",
                           "social media", "game", "gambling"]
        confused = False
        for ans in entity_answers:
            ans_lower = ans.lower()
            for term in confusion_terms:
                if term in ans_lower and brand_lower in ans_lower:
                    # Check if it's actually describing the brand as this
                    pattern = f"{brand_lower}.*(?:is a|is an).*{term}"
                    if re.search(pattern, ans_lower):
                        print(f"  [{WARN}] Possible brand confusion: AI describes {brand} as a '{term}'")
                        confused = True
                        entity_score = max(entity_score - 5, 0)
                        break
            if confused:
                break
        if not confused:
            print(f"  [{PASS}] No brand confusion detected")
    else:
        print(f"  [{FAIL}] AI engines do not recognize {brand}")
        entity_score = 0

    entity_score = min(entity_score, entity_max)
    print(f"  Entity Clarity: {entity_score}/{entity_max} pts")

    # ── 3. Competitor Position Score (0-20) ──
    print(f"\n--- 3. Competitor Position ---")
    comp_score = 0

    # Show top competitors
    sorted_comps = sorted(global_competitors.items(), key=lambda x: -x[1])[:10]
    if sorted_comps:
        print(f"  Top competitors mentioned alongside queries:")
        for comp, count in sorted_comps:
            print(f"    {comp}: {count} mention(s)")

    # Analyze framing
    framing_counts = {}
    for f in all_framings:
        framing_counts[f] = framing_counts.get(f, 0) + 1

    if framing_counts:
        print(f"\n  Brand framing across all answers:")
        framing_labels = {
            "recommended": "Recommended (strongest)",
            "leader": "Leader/major player",
            "option": "One of several options",
            "mentioned": "Passively mentioned",
            "niche": "Niche/experimental",
            "not_mentioned": "Not mentioned",
        }
        for framing, label in framing_labels.items():
            count = framing_counts.get(framing, 0)
            if count > 0:
                print(f"    {label}: {count}x")

    # Score based on framing quality
    rec_count = framing_counts.get("recommended", 0)
    leader_count = framing_counts.get("leader", 0)
    option_count = framing_counts.get("option", 0)
    mentioned_count = framing_counts.get("mentioned", 0)
    not_mentioned = framing_counts.get("not_mentioned", 0)

    total_framings = len(all_framings) or 1
    positive_ratio = (rec_count + leader_count) / total_framings
    if positive_ratio >= 0.5:
        comp_score = 20
    elif positive_ratio >= 0.3:
        comp_score = 15
    elif (rec_count + leader_count + option_count) / total_framings >= 0.3:
        comp_score = 10
    elif mentioned_count > not_mentioned:
        comp_score = 5
    else:
        comp_score = 0

    print(f"  Competitor Position: {comp_score}/20 pts")

    # ── 4. Answer Stability Score (0-20) ──
    print(f"\n--- 4. Answer Stability ---")
    stable_count = 0
    unstable_count = 0
    absent_count = 0

    for eng_name in engines:
        for query in all_queries:
            runs = all_results[eng_name].get(query, [])
            valid_runs = [r for r in runs if not r.get("error")]
            if not valid_runs:
                absent_count += 1
                continue
            cited_in = sum(1 for r in valid_runs if r["brand_result"]["cited"])
            if cited_in == len(valid_runs):
                stable_count += 1
            elif cited_in > 0:
                unstable_count += 1
            else:
                absent_count += 1

    total_slots = stable_count + unstable_count + absent_count
    print(f"  Stable (all runs cited):   {stable_count}")
    print(f"  Unstable (some runs):      {unstable_count}")
    print(f"  Absent (never cited):      {absent_count}")

    if total_slots > 0:
        stability_ratio = (stable_count + unstable_count * 0.3) / total_slots
        stability_score = round(stability_ratio * 20)
    else:
        stability_score = 0

    print(f"  Answer Stability: {stability_score}/20 pts")

    # ── 5. Content Gap Score (0-20) ──
    print(f"\n--- 5. Content Gaps ---")
    gap_score = 20  # Start full, subtract for each gap found
    gaps_found = []

    for eng_name in engines:
        for query in all_queries:
            group = query_group_map[query]
            runs = all_results[eng_name].get(query, [])
            valid_runs = [r for r in runs if not r.get("error")]
            if not valid_runs:
                continue
            cited_in = sum(1 for r in valid_runs if r["brand_result"]["cited"])
            if cited_in == 0:
                gap_entry = f"[{eng_name}] \"{query}\" ({group})"
                if gap_entry not in gaps_found:
                    gaps_found.append(gap_entry)

    # Deduplicate by query text
    seen_queries = set()
    unique_gaps = []
    for gap in gaps_found:
        # Extract query from gap entry
        q_match = re.search(r'"(.+?)"', gap)
        if q_match:
            q_text = q_match.group(1)
            if q_text not in seen_queries:
                seen_queries.add(q_text)
                unique_gaps.append(gap)

    if unique_gaps:
        print(f"  [{WARN}] {len(unique_gaps)} content gap(s) detected:")
        for gap in unique_gaps[:10]:
            print(f"    • {gap}")
            gap_score -= 3
        if len(unique_gaps) > 10:
            print(f"    ... and {len(unique_gaps) - 10} more")

        print(f"\n  Recommended actions to fill gaps:")
        print(f"    • Create dedicated pages for topics where {brand} is not cited")
        print(f"    • Add FAQ sections answering these exact queries on your site")
        print(f"    • Write comparison pages ({brand} vs [competitor]) for competitive queries")
        print(f"    • Publish content on third-party platforms (blog posts, Reddit, GitHub)")
    else:
        print(f"  [{PASS}] No major content gaps detected!")

    gap_score = max(gap_score, 0)
    print(f"  Content Gap: {gap_score}/20 pts")

    # ══════════════════════════════════════════════════════════════
    # COMPOSITE GEO HEALTH SCORECARD
    # ══════════════════════════════════════════════════════════════

    total_score = visibility_score + entity_score + comp_score + stability_score + gap_score
    total_max = 100

    print(f"\n{'='*60}")
    print(f"  GEO HEALTH SCORECARD")
    print(f"{'='*60}")

    categories = [
        ("Prompt Visibility", visibility_score, 20),
        ("Entity Clarity", entity_score, 20),
        ("Competitor Position", comp_score, 20),
        ("Answer Stability", stability_score, 20),
        ("Content Gap", gap_score, 20),
    ]

    for cat_name, earned, mx in categories:
        pct = (earned / mx * 100) if mx > 0 else 0
        bar_len = int(pct / 5)
        if pct >= 60:
            bar_color = "\033[92m"
        elif pct >= 30:
            bar_color = "\033[93m"
        else:
            bar_color = "\033[91m"
        bar = bar_color + "█" * bar_len + "\033[0m" + "░" * (20 - bar_len)
        print(f"  {_pad(cat_name, 22)} {earned:>2}/{mx}  {bar}  {pct:.0f}%")

    print(f"  {'─'*22} {'─'*5}")
    print(f"  {_pad('GEO HEALTH', 22)} {total_score:>2}/{total_max}")

    # Overall grade
    if total_score >= 80:
        grade = "A — AI engines actively recommend this brand"
        grade_color = "\033[92m"
    elif total_score >= 60:
        grade = "B — Good visibility, some gaps to fill"
        grade_color = "\033[92m"
    elif total_score >= 40:
        grade = "C — Moderate visibility, significant gaps"
        grade_color = "\033[93m"
    elif total_score >= 20:
        grade = "D — Low visibility, major work needed"
        grade_color = "\033[93m"
    else:
        grade = "F — Not visible to AI engines"
        grade_color = "\033[91m"

    print(f"\n  Grade: {grade_color}{grade}\033[0m")

    # Multi-engine comparison
    if len(engines) > 1:
        print(f"\n  Per-Engine Visibility:")
        for eng_name, rate in per_engine_rates.items():
            bar_len = int(rate / 5)
            if rate >= 60:
                bc = "\033[92m"
            elif rate >= 30:
                bc = "\033[93m"
            else:
                bc = "\033[91m"
            bar = bc + "█" * bar_len + "\033[0m" + "░" * (20 - bar_len)
            print(f"    {eng_name:<15} {bar}  {rate:.0f}%")

    print(f"\n  Run periodically to track improvements over time.")
    print(f"  Tip: Use --queries to test your specific category prompts.")
    print(f"{'='*60}\n")

    if return_data:
        top_competitors = sorted(global_competitors.items(), key=lambda x: -x[1])[:10]
        return {
            "url": base_url,
            "domain": domain,
            "brand": brand,
            "engines": list(engines.keys()),
            "scores": {
                "visibility": visibility_score,
                "entity": entity_score,
                "competitor": comp_score,
                "stability": stability_score,
                "content_gap": gap_score,
            },
            "total_score": total_score,
            "max_score": total_max,
            "grade": grade.split(" — ")[0] if " — " in grade else grade,
            "grade_label": grade,
            "per_engine_rates": {k: round(v, 1) for k, v in per_engine_rates.items()},
            "top_competitors": [{"domain": d, "mentions": c} for d, c in top_competitors],
            "framings": framing_counts,
            "content_gaps": unique_gaps[:20],
            "query_count": len(all_queries),
            "stability_runs": STABILITY_RUNS,
        }


# ---------------------------------------------------------------------------
# Entity GEO Audit  (--entity)
# ---------------------------------------------------------------------------

def _check_knowledge_graph(entity_name, entity_type):
    """Check entity presence in Wikipedia, Wikidata, and Google Knowledge Panel signals.
    Returns (score 0-20, details dict)."""
    import urllib.parse
    score = 0
    details = {"wikipedia": False, "wikidata": False, "wikidata_id": None,
               "google_kg": False, "platforms_found": []}

    # 1. Wikipedia check — search API
    try:
        enc = urllib.parse.quote(entity_name)
        url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={enc}&format=json&srlimit=3"
        r = requests.get(url, timeout=10, headers={"User-Agent": "GEO-Checker/1.0"})
        if r.status_code == 200:
            data = r.json()
            results = data.get("query", {}).get("search", [])
            for result in results:
                if entity_name.lower() in result.get("title", "").lower():
                    details["wikipedia"] = True
                    details["platforms_found"].append("Wikipedia")
                    score += 7
                    break
    except Exception:
        pass

    # 2. Wikidata check — search API
    try:
        enc = urllib.parse.quote(entity_name)
        url = f"https://www.wikidata.org/w/api.php?action=wbsearchentities&search={enc}&language=en&format=json&limit=3"
        r = requests.get(url, timeout=10, headers={"User-Agent": "GEO-Checker/1.0"})
        if r.status_code == 200:
            data = r.json()
            results = data.get("search", [])
            for result in results:
                if entity_name.lower() in result.get("label", "").lower():
                    details["wikidata"] = True
                    details["wikidata_id"] = result.get("id")
                    details["platforms_found"].append("Wikidata")
                    score += 7
                    break
    except Exception:
        pass

    # 3. Google Knowledge Panel signal — check if structured org/person data exists
    # We probe Google via a simple search snippet (limited but free)
    try:
        enc = urllib.parse.quote(entity_name)
        url = f"https://kgsearch.googleapis.com/v1/entities:search?query={enc}&limit=3&indent=True&key=none"
        # Without a valid API key this returns 403, but we can try the free tier
        # Fallback: check if entity has a Wikipedia page (strong KG signal)
        if details["wikipedia"]:
            details["google_kg"] = True
            details["platforms_found"].append("Google KG (inferred)")
            score += 6
    except Exception:
        pass

    # If no Wikipedia but has Wikidata, partial KG credit
    if not details["google_kg"] and details["wikidata"]:
        score += 3

    return min(20, score), details


def _check_cross_platform_footprint(entity_name, entity_type):
    """Check entity presence across platforms AI models train on.
    Uses the same probe logic as check_cross_platform() for consistency.
    Returns (score 0-20, details dict)."""
    found = []
    not_found = []

    # Derive a URL-friendly brand slug from entity name
    brand = entity_name.lower().replace(" ", "").replace("-", "").replace("_", "")
    brand_slug = entity_name.lower().replace(" ", "-")

    # Same platform definitions as check_cross_platform() — probe real profile URLs
    platforms = {
        "X / Twitter": {
            "probe_urls": [f"https://x.com/{brand}", f"https://twitter.com/{brand}"],
        },
        "LinkedIn": {
            "probe_urls": [f"https://www.linkedin.com/company/{brand_slug}"]
                if entity_type != "person"
                else [f"https://www.linkedin.com/in/{brand_slug}"],
        },
        "YouTube": {
            "probe_urls": [f"https://www.youtube.com/@{brand}", f"https://www.youtube.com/c/{brand}"],
        },
        "GitHub": {
            "probe_urls": [f"https://github.com/{brand}"],
            "api_url": f"https://api.github.com/search/{'users' if entity_type == 'person' else 'repositories'}?q={entity_name}",
        },
        "Reddit": {
            "probe_urls": [f"https://www.reddit.com/r/{brand}", f"https://www.reddit.com/user/{brand}"],
        },
        "Facebook": {
            "probe_urls": [f"https://www.facebook.com/{brand}"],
        },
        "Medium": {
            "probe_urls": [f"https://medium.com/@{brand}", f"https://{brand}.medium.com"],
        },
        "TikTok": {
            "probe_urls": [f"https://www.tiktok.com/@{brand}"],
        },
    }

    # Same soft-404 detection as check_cross_platform()
    soft_404_phrases = [
        "page not found", "this account doesn", "this page isn",
        "nothing here", "sorry, nobody", "user not found",
        "hmm...this page doesn", "account suspended",
        "content isn't available", "content not available",
        "this content is not available", "page isn't available",
        "this page is not available", "link may be broken",
        "profile not found", "channel not found",
        "this user is not available", "suspended account",
        "no results found", "couldn't find this account",
        "we couldn't find", "does not exist",
    ]

    browser_ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

    for plat_name, plat_info in platforms.items():
        plat_found = False

        # Try GitHub API first if available (more reliable)
        api_url = plat_info.get("api_url")
        if api_url and not plat_found:
            try:
                r = requests.get(api_url, timeout=10, headers={"User-Agent": "GEO-Checker/1.0"})
                if r.status_code == 200:
                    data = r.json()
                    if data.get("total_count", 0) > 0:
                        plat_found = True
            except Exception:
                pass

        # Probe profile URLs (same logic as check_cross_platform)
        if not plat_found:
            for probe_url in plat_info["probe_urls"]:
                try:
                    r = requests.get(probe_url, timeout=8, allow_redirects=True,
                                     headers={"User-Agent": browser_ua})
                    if r.status_code == 200:
                        final_url = r.url.lower()
                        redirected_to_login = any(seg in final_url for seg in [
                            "/login", "/signin", "/sign_in", "/accounts/login",
                        ])
                        text_lower = r.text[:500000].lower() if len(r.text) < 500000 else r.text[:500000].lower()
                        is_404_page = redirected_to_login or any(p in text_lower for p in soft_404_phrases)
                        if not is_404_page:
                            plat_found = True
                            break
                except requests.RequestException:
                    pass

        if plat_found:
            found.append(plat_name)
        else:
            not_found.append(plat_name)

    total_platforms = len(platforms)
    if total_platforms == 0:
        return 0, {"found": found, "not_found": not_found}

    rate = len(found) / total_platforms
    score = round(rate * 20)
    return min(20, score), {"found": found, "not_found": not_found}


def entity_audit(entity_name, entity_type="brand", return_data=False):
    """Audit GEO readiness of a brand, product, or person via AI engine queries.

    When return_data=True, returns a dict with full scorecard, key findings,
    and content gaps. Raises RuntimeError on missing/invalid API key instead
    of sys.exit.
    """
    import os

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        if return_data:
            raise RuntimeError("OPENROUTER_API_KEY not set")
        print(f"\n  [{FAIL}] OPENROUTER_API_KEY environment variable not set.")
        print(f"  This feature requires an OpenRouter API key.")
        print(f"  Set it with: export OPENROUTER_API_KEY='your-openrouter-api-key'")
        print(f"  Get an API key at: https://openrouter.ai/")
        sys.exit(1)

    entity_type = entity_type.lower()
    if entity_type not in ("brand", "product", "person"):
        if return_data:
            raise ValueError("entity_type must be one of: brand, product, person")
        print(f"\n  [{FAIL}] --entity-type must be one of: brand, product, person")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  ENTITY GEO AUDIT: \"{entity_name}\" ({entity_type})")
    print(f"{'='*60}\n")
    print(f"  Engine: OpenAI GPT-4o-mini (web search)")

    # ── Phase 1: Free checks (no API key needed) ──────────────
    print(f"\n  Phase 1: Knowledge Graph & Platform checks...\n")

    kg_score, kg_details = _check_knowledge_graph(entity_name, entity_type)
    for p in kg_details["platforms_found"]:
        print(f"    ✓ Knowledge Graph: Found on {p}")
    if not kg_details["platforms_found"]:
        print(f"    ✗ Knowledge Graph: Not found on Wikipedia or Wikidata")

    plat_score, plat_details = _check_cross_platform_footprint(entity_name, entity_type)
    for p in plat_details["found"]:
        print(f"    ✓ Platform: {p}")
    for p in plat_details["not_found"]:
        print(f"    ✗ Platform: {p}")

    # ── Phase 2: AI engine queries ────────────────────────────
    print(f"\n  Phase 2: AI engine queries...\n")

    # ── Build queries per entity type ──────────────────────────
    identity_queries = []
    category_queries = []
    competitive_queries = []
    gap_queries = []

    if entity_type == "brand":
        identity_queries = [
            f"What is {entity_name}?",
            f"What does {entity_name} do?",
            f"Is {entity_name} a reliable and trustworthy company?",
        ]
        competitive_queries = [
            f"Best alternatives to {entity_name}",
            f"{entity_name} review",
            f"How does {entity_name} compare to its competitors?",
        ]
        category_queries = [
            f"What industry is {entity_name} in?",
            f"What is {entity_name} known for?",
        ]
        gap_queries = [
            f"Top companies in the same space as {entity_name}",
            f"Best tools or services like {entity_name}",
        ]
    elif entity_type == "product":
        identity_queries = [
            f"What is {entity_name}?",
            f"What does {entity_name} do?",
            f"Is {entity_name} worth it?",
        ]
        competitive_queries = [
            f"Best alternatives to {entity_name}",
            f"{entity_name} pros and cons",
            f"How does {entity_name} compare to competitors?",
        ]
        category_queries = [
            f"What category of product is {entity_name}?",
            f"What problem does {entity_name} solve?",
        ]
        gap_queries = [
            f"Best products similar to {entity_name}",
            f"Top tools in the same category as {entity_name}",
        ]
    elif entity_type == "person":
        identity_queries = [
            f"Who is {entity_name}?",
            f"What is {entity_name} known for?",
            f"What are {entity_name}'s main contributions?",
        ]
        competitive_queries = [
            f"Top experts in the same field as {entity_name}",
            f"Leaders similar to {entity_name}",
        ]
        category_queries = [
            f"What field or industry is {entity_name} associated with?",
            f"What is {entity_name}'s area of expertise?",
        ]
        gap_queries = [
            f"Most influential people in {entity_name}'s field",
            f"Key thought leaders like {entity_name}",
        ]

    # ── Run queries ────────────────────────────────────────────
    STABILITY_RUNS = 3
    entity_lower = entity_name.lower()

    all_answers = []  # flat list of all answer strings for sentiment analysis

    def run_queries(queries, label):
        """Run a set of queries with stability runs, return list of (query, [answers])."""
        results = []
        for q in queries:
            answers = []
            for run in range(STABILITY_RUNS):
                answer, citations, error = _query_openai(q, api_key)
                if error == "invalid_key":
                    if return_data:
                        raise RuntimeError("Invalid OPENROUTER_API_KEY")
                    print(f"  [{FAIL}] Invalid OpenRouter API key. Check your OPENROUTER_API_KEY.")
                    sys.exit(1)
                if error:
                    answers.append("")
                else:
                    answers.append(answer)
                    all_answers.append(answer)
                time.sleep(1)
            results.append((q, answers))
            print(f"    ✓ {label}: \"{q[:50]}{'...' if len(q) > 50 else ''}\"")
        return results

    identity_results = run_queries(identity_queries, "Identity")
    category_results = run_queries(category_queries, "Category")
    competitive_results = run_queries(competitive_queries, "Competitive")
    gap_results = run_queries(gap_queries, "Gap")

    print(f"\n  Analysis complete. Scoring...\n")

    # ── 1. Entity Recognition (0-20) ──────────────────────────
    recognition_score = 0
    recognized_count = 0
    total_identity_runs = 0
    not_found_phrases = [
        "i don't have", "i'm not sure", "i couldn't find", "no information",
        "i don't know", "not familiar with", "i cannot find", "doesn't appear",
        "does not appear", "no results", "unknown", "not widely known",
    ]

    for q, answers in identity_results:
        for ans in answers:
            total_identity_runs += 1
            if not ans:
                continue
            ans_lower = ans.lower()
            is_not_found = any(p in ans_lower for p in not_found_phrases)
            has_entity = entity_lower in ans_lower
            if has_entity and not is_not_found:
                recognized_count += 1

    if total_identity_runs > 0:
        rec_rate = recognized_count / total_identity_runs
        recognition_score = round(rec_rate * 20)

    # ── 2. Entity Clarity (0-20) ──────────────────────────────
    clarity_score = 0
    confusion_detected = False
    first_run_answers = [answers[0] for _, answers in identity_results if answers[0]]

    if len(first_run_answers) >= 2:
        primary_answers = identity_results[0][1] if identity_results else []
        primary_answers = [a for a in primary_answers if a]

        def extract_key_phrases(text):
            sentences = re.split(r'[.!?]', text.lower())
            return [s.strip() for s in sentences if entity_lower in s and len(s.strip()) > 20]

        all_key_phrases = []
        for ans in primary_answers:
            all_key_phrases.extend(extract_key_phrases(ans))

        consistency_count = 0
        if len(primary_answers) >= 2:
            entity_mention_runs = sum(1 for a in primary_answers if entity_lower in a.lower())
            consistency_count = entity_mention_runs

        if entity_type in ("brand", "product"):
            for ans in primary_answers:
                ans_lower = ans.lower()
                if "not to be confused" in ans_lower or "should not be confused" in ans_lower:
                    confusion_detected = True
                if "different from" in ans_lower and entity_lower in ans_lower:
                    confusion_detected = True
        elif entity_type == "person":
            for ans in primary_answers:
                if "also known as" in ans.lower() or "not to be confused" in ans.lower():
                    confusion_detected = True

        if primary_answers:
            base = min(8, round((len(primary_answers) / STABILITY_RUNS) * 8))
            consistency_bonus = min(8, round((consistency_count / STABILITY_RUNS) * 8))
            confusion_penalty = 6 if confusion_detected else 0
            clarity_score = max(0, min(20, base + consistency_bonus - confusion_penalty + (4 if all_key_phrases else 0)))
    elif len(first_run_answers) == 1:
        clarity_score = 8

    # ── 3. Category Association (0-20) ────────────────────────
    category_score = 0
    category_associations = []

    for q, answers in category_results:
        for ans in answers:
            if not ans:
                continue
            if entity_lower in ans.lower():
                category_associations.append(ans)

    if category_associations:
        assoc_rate = len(category_associations) / (len(category_queries) * STABILITY_RUNS)
        category_score = round(assoc_rate * 20)

    # ── 4. Competitive Position (0-20) ────────────────────────
    comp_position_score = 0
    all_framings = []

    for q, answers in competitive_results:
        for ans in answers:
            if not ans:
                continue
            framing = _classify_framing(ans, entity_name)
            all_framings.append(framing)
            if entity_lower in ans.lower():
                all_framings.append("present")

    framing_scores = {
        "recommended": 20, "leader": 16, "option": 12,
        "mentioned": 8, "present": 8, "niche": 6, "not_mentioned": 0,
    }
    if all_framings:
        best_framing = max(all_framings, key=lambda f: framing_scores.get(f, 0))
        avg_score = sum(framing_scores.get(f, 0) for f in all_framings) / len(all_framings)
        comp_position_score = round(framing_scores.get(best_framing, 0) * 0.6 + avg_score * 0.4)
        comp_position_score = min(20, comp_position_score)

    # ── 5. Sentiment & Framing (0-20) ─────────────────────────
    sentiment_score = 0
    positive_signals = [
        "excellent", "outstanding", "highly recommended", "best", "top",
        "leading", "innovative", "trusted", "reliable", "widely used",
        "popular", "well-known", "well-regarded", "respected", "acclaimed",
        "pioneering", "influential", "groundbreaking", "notable", "renowned",
    ]
    negative_signals = [
        "controversial", "criticized", "problematic", "unreliable", "scam",
        "fraud", "poor", "worst", "avoid", "complaint", "lawsuit",
        "scandal", "failed", "bankrupt", "shut down", "discontinued",
    ]
    action_signals = [
        f"use {entity_lower}", f"try {entity_lower}", f"consider {entity_lower}",
        f"recommend {entity_lower}", f"choose {entity_lower}", f"go with {entity_lower}",
        f"check out {entity_lower}", f"look into {entity_lower}",
    ]

    pos_count = 0
    neg_count = 0
    action_count = 0
    total_analyzed = 0

    for ans in all_answers:
        if not ans:
            continue
        ans_lower = ans.lower()
        total_analyzed += 1
        for sig in positive_signals:
            if sig in ans_lower:
                pos_count += 1
                break
        for sig in negative_signals:
            if sig in ans_lower:
                neg_count += 1
                break
        for sig in action_signals:
            if sig in ans_lower:
                action_count += 1
                break

    if total_analyzed > 0:
        pos_rate = pos_count / total_analyzed
        neg_rate = neg_count / total_analyzed
        action_rate = action_count / total_analyzed
        sentiment_score = round(pos_rate * 12 + action_rate * 8 - neg_rate * 8)
        sentiment_score = max(0, min(20, sentiment_score))

    if total_analyzed == 0:
        sentiment_label = "unknown"
    elif neg_count > pos_count:
        sentiment_label = "negative" if neg_count > pos_count * 2 else "mixed"
    elif pos_count > 0 and action_count > 0:
        sentiment_label = "strongly positive"
    elif pos_count > 0:
        sentiment_label = "positive"
    else:
        sentiment_label = "neutral"

    # ── 6. Content Gap Analysis (0-20) ────────────────────────
    gap_score = 20
    content_gaps = []

    for q, answers in gap_results:
        mentioned_in_any = False
        for ans in answers:
            if ans and entity_lower in ans.lower():
                mentioned_in_any = True
                break
        if not mentioned_in_any:
            content_gaps.append(q)
            gap_score -= 5

    for q, answers in competitive_results:
        mentioned_in_any = False
        for ans in answers:
            if ans and entity_lower in ans.lower():
                mentioned_in_any = True
                break
        if not mentioned_in_any:
            content_gaps.append(q)
            gap_score -= 3

    gap_score = max(0, gap_score)

    # ── Composite Score & Report ──────────────────────────────
    scores = {
        "Entity Recognition": recognition_score,
        "Entity Clarity": clarity_score,
        "Category Association": category_score,
        "Competitive Position": comp_position_score,
        "Sentiment & Framing": sentiment_score,
        "Content Gap": gap_score,
        "Knowledge Graph": kg_score,
        "Platform Footprint": plat_score,
    }
    total_score = sum(scores.values())
    max_score = 160
    pct = round((total_score / max_score) * 100)

    if pct >= 90:
        grade = "A+"
    elif pct >= 80:
        grade = "A"
    elif pct >= 70:
        grade = "B"
    elif pct >= 60:
        grade = "C"
    elif pct >= 50:
        grade = "D"
    else:
        grade = "F"

    # Print scorecard
    print(f"  {'─'*50}")
    print(f"  ENTITY GEO SCORECARD")
    print(f"  {'─'*50}")

    for cat, sc in scores.items():
        bar_pct = sc / 20
        bar_len = round(bar_pct * 20)
        if bar_pct >= 0.7:
            bc = "\033[92m"
        elif bar_pct >= 0.4:
            bc = "\033[93m"
        else:
            bc = "\033[91m"
        bar = bc + "█" * bar_len + "\033[0m" + "░" * (20 - bar_len)
        print(f"    {_pad(cat, 24)} {sc:>2}/20  {bar}  {round(bar_pct*100):>3}%")

    print(f"    {'─'*44}")
    print(f"    {_pad('ENTITY GEO SCORE', 24)} {total_score:>3}/{max_score}")
    print(f"\n    Grade: {grade} ({pct}%)")

    # ── Key Findings ──────────────────────────────────────────
    print(f"\n  {'─'*50}")
    print(f"  KEY FINDINGS")
    print(f"  {'─'*50}")

    # Knowledge Graph finding
    if kg_score >= 14:
        print(f"    [{PASS}] Strong Knowledge Graph presence ({', '.join(kg_details['platforms_found'])})")
    elif kg_score >= 7:
        print(f"    [{WARN}] Partial Knowledge Graph presence ({', '.join(kg_details['platforms_found'])})")
        if not kg_details["wikipedia"]:
            fix(f"Create a Wikipedia article for \"{entity_name}\". Wikipedia is the #1 source\n"
                f"AI models use for entity recognition. Ensure it meets Wikipedia's notability\n"
                f"guidelines (third-party coverage in reliable sources).")
        if not kg_details["wikidata"]:
            fix(f"Create a Wikidata entry for \"{entity_name}\" at https://www.wikidata.org.\n"
                f"Wikidata is the structured knowledge base behind Google Knowledge Panel,\n"
                f"Wikipedia infoboxes, and many AI training pipelines.\n"
                f"Include: description, official website, social profiles, instance-of type.")
    else:
        print(f"    [{FAIL}] Not found in Knowledge Graph (Wikipedia, Wikidata)")
        fix(f"Establish \"{entity_name}\" as a recognized entity:\n"
            f"1. Create a Wikidata entry at https://www.wikidata.org with structured data\n"
            f"   (description, official website, social profiles, instance-of type)\n"
            f"2. If eligible, create a Wikipedia article with third-party reliable sources\n"
            f"3. Add JSON-LD Organization/Person schema to your website with sameAs links\n"
            f"   pointing to Wikidata, Wikipedia, and social profiles\n"
            f"4. Ensure consistent name/description across all platforms")

    # Platform Footprint finding
    if plat_score >= 14:
        print(f"    [{PASS}] Strong platform footprint ({len(plat_details['found'])}/{len(plat_details['found']) + len(plat_details['not_found'])} platforms)")
    elif plat_score >= 8:
        print(f"    [{WARN}] Moderate platform footprint ({len(plat_details['found'])}/{len(plat_details['found']) + len(plat_details['not_found'])} platforms)")
        missing = plat_details["not_found"]
        if missing:
            fix(f"Establish presence on missing platforms: {', '.join(missing)}\n"
                f"AI models train on data from these platforms. Each platform you're present on\n"
                f"increases the chance AI engines recognize and recommend \"{entity_name}\".\n"
                f"Priority: GitHub (for tech), LinkedIn (for professional), YouTube (for reach).")
    else:
        print(f"    [{FAIL}] Weak platform footprint ({len(plat_details['found'])}/{len(plat_details['found']) + len(plat_details['not_found'])} platforms)")
        missing = plat_details["not_found"]
        fix(f"Urgently establish presence on major platforms: {', '.join(missing)}\n"
            f"AI models learn about entities from cross-platform signals. Without presence\n"
            f"on platforms like GitHub, LinkedIn, YouTube, and Reddit, AI engines have\n"
            f"very little data to learn about \"{entity_name}\".\n"
            f"Steps:\n"
            f"1. Create profiles on each missing platform with consistent branding\n"
            f"2. Publish content regularly — AI training data favors active accounts\n"
            f"3. Cross-link all profiles (helps AI connect them as one entity)")

    # Recognition finding
    if recognition_score >= 16:
        print(f"    [{PASS}] AI consistently recognizes \"{entity_name}\"")
    elif recognition_score >= 8:
        print(f"    [{WARN}] AI partially recognizes \"{entity_name}\" — inconsistent across queries")
        if entity_type == "person":
            fix(f"Strengthen AI recognition of \"{entity_name}\":\n"
                f"1. Publish authored content on platforms AI trains on (Medium, LinkedIn, GitHub)\n"
                f"2. Get quoted or featured in industry publications and news articles\n"
                f"3. Ensure your personal website has clear JSON-LD Person schema\n"
                f"4. Maintain consistent bio/description across all platforms")
        else:
            fix(f"Strengthen AI recognition of \"{entity_name}\":\n"
                f"1. Publish a clear \"About\" page with JSON-LD Organization schema\n"
                f"2. Get listed in industry directories and comparison sites\n"
                f"3. Earn mentions in third-party articles and reviews\n"
                f"4. Create a llms.txt file at your site root explaining what {entity_name} is")
    else:
        print(f"    [{FAIL}] AI does not reliably recognize \"{entity_name}\"")
        if entity_type == "person":
            fix(f"AI engines do not recognize \"{entity_name}\". To fix this:\n"
                f"1. Build a personal website with comprehensive bio and JSON-LD Person schema\n"
                f"2. Publish regularly on Medium, LinkedIn, and/or a personal blog\n"
                f"3. Contribute to open-source projects on GitHub\n"
                f"4. Get featured in interviews, podcasts, or industry publications\n"
                f"5. Create a Wikipedia page if notability criteria are met\n"
                f"6. Create a Wikidata entry with structured facts about your career")
        else:
            fix(f"AI engines do not recognize \"{entity_name}\". To fix this:\n"
                f"1. Create a comprehensive website with clear About, Product, and FAQ pages\n"
                f"2. Add JSON-LD Organization schema with name, description, sameAs links\n"
                f"3. Create a llms.txt file explaining what {entity_name} is and does\n"
                f"4. Get listed on review platforms (G2, Capterra, Trustpilot, Product Hunt)\n"
                f"5. Publish content on Medium, LinkedIn, and your own blog\n"
                f"6. Create Wikipedia and Wikidata entries if notability criteria are met")

    # Clarity finding
    if clarity_score >= 16:
        print(f"    [{PASS}] Entity definition is clear and consistent across runs")
    elif clarity_score >= 8:
        print(f"    [{WARN}] Entity definition varies between queries — may indicate ambiguity")
        fix(f"AI gives inconsistent descriptions of \"{entity_name}\". To improve clarity:\n"
            f"1. Use the exact same tagline/description on every platform and page\n"
            f"2. Lead your homepage, About page, and llms.txt with a clear one-sentence definition\n"
            f"3. Ensure JSON-LD schema description matches your official tagline\n"
            f"4. If the name is ambiguous, add disambiguation content (e.g., \"{entity_name} (the company)\")")
    else:
        print(f"    [{FAIL}] Entity definition is unclear or confused with other entities")
        if confusion_detected:
            fix(f"AI actively confuses \"{entity_name}\" with other entities. Urgent fixes:\n"
                f"1. Add explicit disambiguation to your About page and JSON-LD description\n"
                f"2. Create a FAQ addressing \"What is {entity_name}?\" directly\n"
                f"3. Publish comparison/differentiation content vs commonly confused entities\n"
                f"4. Ensure your Wikidata entry has correct instance-of and distinct-from claims\n"
                f"5. Use consistent, unique branding language that sets you apart")
        else:
            fix(f"AI cannot clearly define \"{entity_name}\". To establish a clear identity:\n"
                f"1. Write a clear, concise definition and use it everywhere consistently\n"
                f"2. Structure your homepage to answer \"What is {entity_name}?\" in the first paragraph\n"
                f"3. Add FAQ schema with identity questions and clear answers\n"
                f"4. Create llms.txt with an unambiguous description at the top")

    # Category finding
    if category_score >= 14:
        print(f"    [{PASS}] Strong category/domain association detected")
    elif category_score >= 8:
        print(f"    [{WARN}] Weak category association — AI may not map entity to its core domain")
        fix(f"Strengthen category association for \"{entity_name}\":\n"
            f"1. Explicitly state your category/industry on your homepage and About page\n"
            f"   (e.g., \"{entity_name} is a [category] that...\")\n"
            f"2. Publish content using category keywords throughout (blog posts, guides)\n"
            f"3. Get listed in category-specific directories and comparison sites\n"
            f"4. Ensure JSON-LD schema uses the most specific @type for your category")
    else:
        print(f"    [{FAIL}] AI does not clearly associate entity with a specific category")
        fix(f"AI cannot determine what category \"{entity_name}\" belongs to. To fix:\n"
            f"1. Lead every platform bio with: \"{entity_name} is a [specific category]...\"\n"
            f"2. Create a \"What is {entity_name}\" page optimized for your core category terms\n"
            f"3. Publish comparison content: \"{entity_name} vs [category competitors]\"\n"
            f"4. Get featured in \"Best [category]\" listicles and roundup articles\n"
            f"5. Add industry/category keywords to your JSON-LD schema and meta descriptions\n"
            f"6. Create topical content clusters around your core category")

    # Competitive position finding
    best_framing_label = "unknown"
    if all_framings:
        framing_counts = {}
        for f in all_framings:
            if f != "present":
                framing_counts[f] = framing_counts.get(f, 0) + 1
        if framing_counts:
            best_framing_label = max(framing_counts, key=framing_counts.get)
    if entity_type == "person":
        if comp_position_score >= 14:
            print(f"    [{PASS}] Mentioned among top experts/leaders in field")
        elif comp_position_score >= 8:
            print(f"    [{WARN}] Mentioned but not prominently positioned among peers")
            fix(f"To elevate \"{entity_name}\" among field leaders:\n"
                f"1. Publish thought leadership content (articles, research, talks)\n"
                f"2. Speak at industry conferences and get talks published on YouTube\n"
                f"3. Contribute to high-profile open-source projects or publications\n"
                f"4. Get quoted as an expert in news articles and industry reports\n"
                f"5. Build a track record of public contributions AI can reference")
        else:
            print(f"    [{FAIL}] Not mentioned among leaders in field")
            fix(f"\"{entity_name}\" is not recognized as a leader in their field. To fix:\n"
                f"1. Publish original research, guides, or frameworks in your area of expertise\n"
                f"2. Create a personal website showcasing key contributions and publications\n"
                f"3. Get featured in \"Top [field] experts\" or \"People to follow\" lists\n"
                f"4. Build public presence: conference talks, podcast appearances, Twitter/X threads\n"
                f"5. Contribute to Wikipedia articles in your field (as a cited source, not self-editing)\n"
                f"6. Maintain active GitHub, LinkedIn, and Medium profiles with regular posts")
    else:
        print(f"    [{INFO}] Competitive framing: {best_framing_label}")
        if best_framing_label in ("not_mentioned", "niche", "unknown"):
            fix(f"AI does not position \"{entity_name}\" strongly against competitors. To improve:\n"
                f"1. Create comparison pages: \"{entity_name} vs [Competitor]\" for top 3-5 rivals\n"
                f"2. Get featured in third-party comparison articles and \"best of\" roundups\n"
                f"3. Earn reviews on G2, Capterra, Trustpilot — AI engines weight review platforms\n"
                f"4. Publish case studies showing concrete results vs alternatives\n"
                f"5. Target \"best [category]\" and \"[category] comparison\" search queries")
        elif best_framing_label == "option":
            fix(f"AI mentions \"{entity_name}\" as one option among many. To move to \"recommended\":\n"
                f"1. Earn more reviews and testimonials on authoritative platforms\n"
                f"2. Publish differentiation content highlighting unique strengths\n"
                f"3. Get featured as a top pick (not just listed) in comparison articles\n"
                f"4. Create \"Why {entity_name}\" content with specific advantages over alternatives")

    # Sentiment finding
    print(f"    [{INFO}] Overall AI sentiment: {sentiment_label}")
    if action_count > 0:
        print(f"    [{PASS}] AI uses recommendation language (\"use\", \"try\", \"consider\")")
    if sentiment_label in ("negative", "mixed"):
        fix(f"AI sentiment toward \"{entity_name}\" is {sentiment_label}. To improve:\n"
            f"1. Address negative signals: respond to criticism, fix reported issues\n"
            f"2. Earn positive reviews and testimonials on authoritative platforms\n"
            f"3. Publish case studies, success stories, and positive press coverage\n"
            f"4. Ensure third-party content about {entity_name} is accurate and up-to-date\n"
            f"5. If outdated negative content exists, publish fresh positive content to outweigh it")
    elif sentiment_label == "neutral" and total_analyzed > 0:
        fix(f"AI describes \"{entity_name}\" neutrally — no strong positive or recommendation signals.\n"
            f"To earn recommendation language (\"use X\", \"try X\", \"consider X\"):\n"
            f"1. Earn reviews that use recommendation language on G2, Capterra, Product Hunt\n"
            f"2. Get featured in \"best of\" and \"recommended\" lists in your category\n"
            f"3. Publish testimonials and endorsements from recognized authorities\n"
            f"4. Create content showing measurable results and clear advantages")

    # Content gaps
    if content_gaps:
        print(f"\n  {'─'*50}")
        print(f"  CONTENT GAPS (entity not mentioned for these queries)")
        print(f"  {'─'*50}")
        for gap in content_gaps:
            print(f"    [{WARN}] \"{gap}\"")
        if entity_type == "person":
            fix(f"Create content targeting these gap queries:\n" +
                "\n".join(f"  • Write an article, talk, or post about: \"{g}\"" for g in content_gaps) +
                f"\n\nPublish on platforms AI trains on: Medium, LinkedIn, personal blog, YouTube.\n"
                f"Each published piece increases the chance AI associates \"{entity_name}\" with these topics.")
        else:
            fix(f"Create content targeting these gap queries:\n" +
                "\n".join(f"  • Create a page or article about: \"{g}\"" for g in content_gaps) +
                f"\n\nTarget these as blog posts, landing pages, or FAQ entries.\n"
                f"Ensure each page mentions \"{entity_name}\" prominently and uses relevant category keywords.\n"
                f"Get these pages linked from authoritative sources for faster AI indexing.")
    else:
        print(f"    [{PASS}] No content gaps detected — entity appears across all tested queries")

    print(f"\n{'='*60}\n")

    if return_data:
        return {
            "entity": entity_name,
            "entity_type": entity_type,
            "scores": scores,
            "total_score": total_score,
            "max_score": max_score,
            "percent": pct,
            "grade": grade,
            "knowledge_graph": {
                "wikipedia": kg_details["wikipedia"],
                "wikidata": kg_details["wikidata"],
                "wikidata_id": kg_details["wikidata_id"],
                "google_kg": kg_details["google_kg"],
                "platforms_found": kg_details["platforms_found"],
            },
            "platforms": {
                "found": plat_details["found"],
                "not_found": plat_details["not_found"],
            },
            "sentiment": sentiment_label,
            "best_framing": best_framing_label,
            "content_gaps": content_gaps,
            "recognition_rate": round(recognition_score / 20 * 100, 1),
            "stability_runs": STABILITY_RUNS,
        }


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
_ZH.update({
    # ── Category names (score table display) ──
    "AI Answer Formats": "AI 回答格式",
    "AI Crawl Readiness": "AI 抓取就绪度",
    "AI Optimization": "AI 优化",
    "Answer Engine Schema": "问答引擎 Schema",
    "Authority & Trust": "权威性与信任度",
    "Brand Entity KG": "品牌实体知识图谱",
    "Content Accessibility": "内容可访问性",
    "Content Quality": "内容质量",
    "Content Structure": "内容结构",
    "Cross-Platform": "跨平台分发",
    "Direct Answer Snippets": "直接回答片段",
    "FAQ Readiness": "FAQ 就绪度",
    "Heading Hierarchy": "标题层级结构",
    "Meta Tags": "Meta 标签",
    "Mobile & Weight": "移动端与页面体积",
    "Multi-Page": "多页面一致性",
    "Multilingual": "多语言支持",
    "Outbound & Media": "外链与媒体",
    "Per-Page Content": "单页内容评分",
    "Platform Registration": "平台注册",
    "Question Headings": "问句式标题",
    "Readability & Trust": "可读性与来源信任",
    "Schema & Knowledge": "Schema 与知识面板",
    "Sitemap": "站点地图",
    "Social Signals": "社交信号",
    "Structured Data": "结构化数据",
    "Technical Crawlability": "技术可抓取性",
    "Trust & Safety": "信任与安全",
    "URL Normalization": "URL 规范化",

    # ── Section headers ──
    ".well-known Discovery": ".well-known 发现",
    "Search Engine & AI Platform Registration": "搜索引擎与 AI 平台注册",
    "Content Quality for AI": "面向 AI 的内容质量",
    "Authority & Trust Signals": "权威性与信任信号",
    "Brand Entity in Knowledge Graphs": "品牌实体在知识图谱中的表现",
    "Trust & Safety Signals": "信任与安全信号",
    "AI-Specific Optimization": "AI 专项优化",
    "AI Answer Format Optimization": "AI 回答格式优化",
    "Schema Breadcrumbs & Knowledge Panel": "Schema 面包屑与知识面板",
    "Mobile-Friendliness & Page Weight": "移动端适配与页面体积",
    "Outbound Links & Media": "外链与媒体资源",
    "Multilingual Content Depth": "多语言内容深度",
    "Cross-Platform Content Distribution": "跨平台内容分发",
    "Multi-Page Sampling": "多页面抽样检测",
    "Per-Page AEO Content Score": "单页 AEO 内容评分",
    "AEO (Answer Engine Optimization) Audit": "AEO（问答引擎优化）审计",
    "1. FAQ Readiness": "1. FAQ 就绪度",
    "2. Question-Pattern Headings": "2. 问句式标题",
    "3. Direct Answer Snippets": "3. 直接回答片段",
    "4. Answer Engine Schema": "4. 问答引擎 Schema",
    "5. Content Structure for AI Extraction": "5. 面向 AI 提取的内容结构",
    "6. Readability & Source Trust": "6. 可读性与来源信任",
    "7. Heading Hierarchy": "7. 标题层级结构",
    "8. Per-Page AEO Content Score": "8. 单页 AEO 内容评分",

    # ── UI chrome / structural ──
    "GEO Readiness Report for:": "GEO 就绪度报告：",
    "Mode:": "模式：",
    "Diagnose + Fix Recommendations": "诊断 + 修复建议",
    "Diagnose Only": "仅诊断",
    "AI VISIBILITY SCORE": "AI 可见度评分",
    "Category Breakdown:": "分类明细：",
    "TOTAL": "总计",
    "Category": "类别",
    "Legend: PASS = good | WARN = could improve | FAIL = missing/bad": "图例：PASS = 良好 | WARN = 待改进 | FAIL = 缺失/异常",
    "FIX = recommended action to resolve the issue": "FIX = 建议采取的修复操作",
    "Tip: Run with --fix to see recommended solutions": "提示：使用 --fix 参数运行可查看修复建议",
    "CONTENT GAP SUGGESTIONS": "内容缺口建议",
    "Based on your weakest categories, here are content strategies": "根据您得分最低的类别，以下是提升",
    "to improve your AI visibility:": "AI 可见度的内容策略：",
    "Priority improvements:": "优先改进项：",
    "AEO SCORE": "AEO 评分",
    "Target:": "目标：",
    "GEO COMPETITIVE COMPARISON": "GEO 竞争对比",
    "AI CITATION SHARE": "AI 引用份额",
    "Winner:": "获胜者：",
    "Lead:": "领先：",
    "Category Advantages:": "类别优势：",
    "Weakest Signal": "最弱信号",
    "Average": "平均",
    "AI VISIBILITY AUDIT": "AI 可见度审计",
    "GEO HEALTH SCORECARD": "GEO 健康度记分卡",
    "Engines:": "引擎：",
    "Per-Engine Visibility:": "各引擎可见度：",
    "Citation leader:": "引用领先者：",
    "CITATION SHARE RESULTS": "引用份额结果",
    "FIX recommendations are shown inline above.": "FIX 修复建议已在上方对应位置显示。",

    # ── Status messages ──
    "Site uses HTTPS": "站点已启用 HTTPS",
    "Site does not use HTTPS — AI engines prefer secure sites": "站点未使用 HTTPS —— AI 引擎更青睐安全站点",
    "robots.txt found": "robots.txt 已找到",
    "robots.txt not found": "robots.txt 未找到",
    "robots.txt references a sitemap": "robots.txt 中引用了站点地图",
    "AI bots not mentioned (inherit wildcard rules):": "以下 AI 爬虫未单独提及（继承通配符规则）：",
    "AI bots explicitly BLOCKED:": "以下 AI 爬虫被明确阻止：",
    "/ai.txt found — strategic AI crawler policy declared": "/ai.txt 已找到 —— 已声明 AI 抓取策略",
    "llms.txt found": "llms.txt 已找到",
    "llms-full.txt found": "llms-full.txt 已找到",
    ".well-known/llms.txt found": ".well-known/llms.txt 已找到",
    "Contains descriptive text": "包含描述性文本",
    "No sections (## headings) — consider organizing content into sections": "无章节（## 标题）—— 建议将内容组织为分节结构",
    "link(s) to resources found": "个资源链接已找到",
    "section(s) found (## headings)": "个章节已找到（## 标题）",
    "No llms.txt found": "未找到 llms.txt",
    "Sitemap found": "站点地图已找到",
    "Sitemap includes <lastmod> timestamps": "站点地图包含 <lastmod> 时间戳",
    "No sitemap found": "未找到站点地图",
    "Google Search Console verification tag found": "Google Search Console 验证标签已找到",
    "Bing Webmaster Tools verification tag found": "Bing Webmaster Tools 验证标签已找到",
    "No Yandex Webmaster verification tag — relevant if targeting international AI platforms": "未找到 Yandex Webmaster 验证标签 —— 若面向国际 AI 平台则需关注",
    "IndexNow endpoint found": "IndexNow 端点已找到",
    "Found JSON-LD block(s)": "找到 JSON-LD 代码块",
    "No structured data (JSON-LD/Microdata) found": "未找到结构化数据（JSON-LD / Microdata）",
    "Granular schema types present:": "已使用细粒度 Schema 类型：",
    "<title> found:": "<title> 已找到：",
    "Meta description found": "Meta 描述已找到",
    "Canonical URL set:": "Canonical URL 已设置：",
    "Open Graph tags present:": "Open Graph 标签已设置：",
    "Twitter Card tags present:": "Twitter Card 标签已设置：",
    "Language declared:": "语言声明：",
    "No hreflang tags — add these if your site supports multiple languages": "无 hreflang 标签 —— 若站点支持多语言请添加",
    "Homepage has": "首页包含",
    "words in initial HTML": "个单词（初始 HTML）",
    "Content-to-HTML ratio:": "内容与 HTML 的比例：",
    "Heading structure found": "标题结构已找到",
    "Content is rendered server-side": "内容为服务端渲染",
    "No restrictive meta robots tag found": "未发现限制性 meta robots 标签",
    "No restrictive X-Robots-Tag header": "未发现限制性 X-Robots-Tag 头",
    "No paywall/login-wall indicators detected": "未检测到付费墙/登录墙",
    "Good semantic HTML structure": "良好的语义化 HTML 结构",
    "images have alt text": "张图片已添加 alt 文本",
    "internal links — good for AI crawl discovery": "个内部链接 —— 有利于 AI 抓取发现",
    "Response time:": "响应时间：",
    "Readability: Flesch-Kincaid grade": "可读性：Flesch-Kincaid 等级",
    "FAQ content detected — strong signal for AI-generated answers": "检测到 FAQ 内容 —— 对 AI 生成回答有强信号作用",
    "quotable statistics found — good for AI citations": "个可引用的统计数据 —— 有利于 AI 引用",
    "No explicit source attributions — citing sources increases AI trust in your content": "未发现明确的来源引用 —— 引用来源可提升 AI 对您内容的信任度",
    "Structured lists found": "找到结构化列表",
    "Canonical URL is self-referencing (correct)": "Canonical URL 自引用（正确）",
    "No redirects — direct access": "无重定向 —— 直接访问",
    "HTTP/2 supported — faster crawling": "支持 HTTP/2 —— 抓取更快",
    "No RSS/Atom feed found — feeds help AI engines monitor content freshness": "未找到 RSS/Atom 订阅源 —— 订阅源帮助 AI 引擎追踪内容更新",
    "Machine-readable / integration endpoints:": "机器可读 / 集成端点：",
    "Strong security headers": "安全响应头设置良好",
    "humans.txt found — authorship transparency": "humans.txt 已找到 —— 作者信息透明",
    "Author markup found in structured data (JSON-LD)": "结构化数据（JSON-LD）中找到作者标记",
    "Bio/about page found at": "个人/关于页面已找到，地址为",
    "Credential signals in bio:": "简介中的资质信号：",
    "No external bylines detected on bio page": "个人简介页未检测到外部署名",
    "Checking entity:": "正在检查实体：",
    "No Wikipedia page found for": "未找到相关 Wikipedia 页面：",
    "No Wikidata entity found for": "未找到相关 Wikidata 实体：",
    "Privacy policy found:": "隐私政策已找到：",
    "Terms of service found:": "服务条款已找到：",
    "Contact page found:": "联系页面已找到：",
    "Legal/DMCA/imprint page found:": "法律声明/DMCA/印记页面已找到：",
    "Partial business identity:": "部分企业身份信息：",
    "Content freshness signals found:": "内容时效性信号已找到：",
    "Healthy sitewide update cadence": "全站更新频率良好",
    "Inconsistent site name across tags:": "各标签中站点名称不一致：",
    "Machine-readable endpoint found:": "机器可读端点已找到：",
    "Twitter/X card tags found:": "Twitter/X Card 标签已找到：",
    "sameAs social links in JSON-LD": "JSON-LD 中的 sameAs 社交链接",
    "definition-style sentence(s) found — highly citable by AI": "个定义式语句 —— AI 引用度极高",
    "No comparison tables — consider adding tables for feature comparisons, pricing, etc.": "未找到对比表格 —— 建议添加功能对比、价格对比等表格",
    "Step-by-step instructional content detected — great for 'how to' AI answers": "检测到分步教程内容 —— 非常适合 AI 的「怎么做」类回答",
    "Pros/cons or advantages/disadvantages content detected": "检测到优缺点/利弊分析内容",
    "Summary/key takeaways section found — AI engines prefer concise summaries": "找到摘要/关键要点部分 —— AI 引擎偏好简洁的总结",
    "question-pattern heading(s) — add more for chat-style queries": "个问句式标题 —— 建议增加更多以适配对话式查询",
    "AI answer format score:": "AI 回答格式评分：",
    "No breadcrumb navigation or schema found": "未找到面包屑导航或 Schema",
    "Organization/Business schema found:": "Organization/Business Schema 已找到：",
    "Organization name: present": "组织名称：已填写",
    "Website URL: present": "网站 URL：已填写",
    "Logo image: present": "Logo 图片：已填写",
    "Description: present": "描述：已填写",
    "Optional fields present:": "可选字段已填写：",
    "Optional fields missing:": "可选字段缺失：",
    "Viewport meta tag found:": "Viewport meta 标签已找到：",
    "Uses width=device-width (responsive)": "使用 width=device-width（响应式）",
    "HTML page weight:": "HTML 页面体积：",
    "Inline resources within acceptable range": "内联资源在可接受范围内",
    "Cache headers found:": "缓存头已找到：",
    "Both trailing slash and non-trailing slash return 200 — ensure canonical is set": "带尾斜杠和不带尾斜杠均返回 200 —— 请确保设置 canonical",
    "serve content — duplicate content risk": "均提供内容 —— 存在重复内容风险",
    "URL case handling is consistent": "URL 大小写处理一致",
    "outbound link(s) to": "个外链指向",
    "unique domain(s)": "个独立域名",
    "Links to authoritative sources:": "指向权威来源的链接：",
    "No video content detected": "未检测到视频内容",
    "Multi-format coverage:": "多格式覆盖：",
    "non-text format(s) detected — more formats = more AI surface area": "种非文本格式 —— 格式越多，AI 可见面越广",
    "No tables found on homepage": "首页未找到表格",
    "First paragraph": "首段",
    "lacks extractable facts — add a definition or key statistic up front": "缺少可提取的事实 —— 建议在开头添加定义或关键数据",
    "No hreflang tags — skipping multilingual check": "无 hreflang 标签 —— 跳过多语言检查",
    "linked on site:": "在站内被链接：",
    "not detected": "未检测到",
    "Limited cross-platform presence:": "跨平台覆盖有限：",
    "Platforms where your brand is visible to AI training:": "您的品牌在以下平台对 AI 训练可见：",
    "trains:": "训练数据来源：",
    "Sampling": "正在抽样",
    "internal page(s)...": "个内部页面……",
    "Low word count (<100 words) on": "低字数（<100 词）的页面共",
    "Duplicate meta descriptions found across pages:": "多个页面存在重复的 meta 描述：",
    "Duplicate <title> tags found across pages:": "多个页面存在重复的 <title> 标签：",
    "All sampled pages maintain consistent GEO standards": "所有抽样页面均保持一致的 GEO 标准",
    "No internal pages to sample": "无内部页面可供抽样",

    # ── Content gap suggestions ──
    "Create a FAQ page with FAQPage schema answering top questions about your product/service": "创建 FAQ 页面并使用 FAQPage Schema，解答关于您产品/服务的常见问题",
    "Add HowTo schema to tutorial or setup guide pages": "在教程或安装指南页面添加 HowTo Schema",
    "Use Product schema with reviews, pricing, and availability on product pages": "在产品页面使用 Product Schema，包含评价、价格和库存信息",
    "Write long-form pillar content (2000+ words) covering your core topic comprehensively": "撰写 2000 字以上的长篇支柱内容，全面覆盖核心主题",
    "Add an 'Industry Statistics' page with original data — AI engines heavily cite pages with numbers": "添加「行业数据」页面并提供原创数据 —— AI 引擎大量引用含数据的页面",
    "Create comparison articles ('X vs Y') — these match competitive queries AI users ask": "创建对比文章（X vs Y）—— 匹配 AI 用户常见的竞品对比查询",
    "Add a 'What is [your product]?' section with a clear 1-2 sentence definition": "添加「什么是[您的产品]？」部分，提供简明的一两句话定义",
    "Structure blog posts as Q&A: use question headings followed by direct answers": "将博客文章结构化为问答形式：使用问句标题，紧跟直接回答",
    "Add 'Key Takeaways' or 'TL;DR' sections — AI engines extract these as summaries": "添加「关键要点」或「TL;DR」部分 —— AI 引擎会将其提取为摘要",
    "Write meta descriptions as self-contained answers (80-160 chars) — AI uses these as fallback snippets": "将 meta 描述写成独立完整的回答（80-160 字符）—— AI 会将其作为备选摘要",
    "Add Open Graph tags so AI engines can extract your preferred title and description": "添加 Open Graph 标签，以便 AI 引擎提取您偏好的标题和描述",
    "Reduce JavaScript dependency — AI crawlers can't execute JS; ensure content is in raw HTML": "减少 JavaScript 依赖 —— AI 爬虫无法执行 JS，请确保内容在原始 HTML 中可见",
    "Add alt text to all images describing what they show — AI uses this for context": "为所有图片添加描述性 alt 文本 —— AI 利用 alt 文本理解图片内容",
    "Create or improve your Wikipedia page — AI engines use Wikipedia as a primary knowledge source": "创建或完善您的 Wikipedia 页面 —— AI 引擎将 Wikipedia 作为主要知识来源",
    "Claim and complete your Google Business Profile, Crunchbase, and LinkedIn company pages": "认领并完善您的 Google 商家资料、Crunchbase 和 LinkedIn 公司页面",
    "Get featured on industry-specific directories and 'best of' lists": "争取出现在行业垂直目录和「精选推荐」榜单中",
    "Add author bios with credentials and links to external profiles (LinkedIn, Twitter)": "添加作者简介，包含资质信息及外部个人主页链接（LinkedIn、Twitter）",
    "Publish guest posts on authoritative sites in your industry with backlinks": "在行业权威网站发布嘉宾文章并附带反向链接",
    "Add an 'About Us' page with team expertise, founding story, and mission statement": "添加「关于我们」页面，包含团队专长、创业故事和使命宣言",
    "Add clearly linked Privacy Policy, Terms of Service, and Contact pages": "添加清晰链接的隐私政策、服务条款和联系方式页面",
    "Display business identity: address, phone, registration number where applicable": "展示企业身份信息：地址、电话、工商注册号等（如适用）",
    "Link to active social media profiles from your site (header or footer)": "在网站页头或页脚链接到活跃的社交媒体主页",
    "Publish regularly on LinkedIn, Twitter/X — AI engines cross-reference social presence": "定期在 LinkedIn、Twitter/X 上发布内容 —— AI 引擎会交叉核实社交媒体存在",
    "Create /llms.txt describing your site's purpose and content for AI crawlers": "创建 /llms.txt，向 AI 爬虫描述您网站的用途和内容",
    "Add /llms-full.txt with comprehensive site documentation for deeper AI indexing": "添加 /llms-full.txt，提供完整的站点文档以促进 AI 深度索引",
    "Create a robots.txt that explicitly allows AI crawler access": "创建 robots.txt 并明确允许 AI 爬虫访问",
    "Add an ai.txt or .well-known/ai.txt to declare your AI data usage preferences": "添加 ai.txt 或 .well-known/ai.txt 以声明您的 AI 数据使用偏好",
    "Ensure each page has a unique title and meta description — duplicate content confuses AI": "确保每个页面都有唯一的标题和 meta 描述 —— 重复内容会干扰 AI 判断",
    "Diversify content across pages; avoid repeating the same paragraphs on multiple URLs": "在各页面差异化内容，避免多个 URL 出现相同段落",
    "Link to authoritative external sources — AI engines trust pages that cite credible references": "链接到权威的外部来源 —— AI 引擎信任引用可靠参考资料的页面",
    "Embed diverse media (images, videos, infographics) — richer content gets cited more": "嵌入多样化媒体（图片、视频、信息图）—— 内容越丰富，被引用越多",

    # ── Fix recommendations ──
    "Install an SSL/TLS certificate (free via Let's Encrypt) and redirect all HTTP traffic to HTTPS.": "安装 SSL/TLS 证书（可通过 Let's Encrypt 免费获取），并将所有 HTTP 流量重定向到 HTTPS。",
    "Create a robots.txt file at your site root.": "在网站根目录创建 robots.txt 文件。",
    "Ensure at least one common AI bot is not blocked by robots.txt.": "确保 robots.txt 未屏蔽至少一个常见的 AI 爬虫。",
    "Add your sitemap URL to robots.txt:": "将站点地图 URL 添加到 robots.txt：",
    "Add a Sitemap reference in robots.txt so AI crawlers find it immediately:": "在 robots.txt 中添加 Sitemap 引用，以便 AI 爬虫能立即找到它：",
    "Create and submit a sitemap.xml": "创建并提交 sitemap.xml",
    "Register with Google Search Console": "注册 Google Search Console",
    "Register with Bing Webmaster Tools": "注册 Bing Webmaster Tools",
    "Add structured data to help AI engines understand your content.": "添加结构化数据，帮助 AI 引擎理解您的内容。",
    "Add a meta description tag.": "添加 meta description 标签。",
    "Set a canonical URL.": "设置 canonical URL。",
    "Add Open Graph meta tags.": "添加 Open Graph meta 标签。",
    "Add alt text to images.": "为图片添加 alt 文本。",
    "Move inline CSS to external stylesheets": "将内联 CSS 移至外部样式表",
    "Move inline JS to external scripts with defer/async": "将内联 JS 移至外部脚本并使用 defer/async 加载",
    "Remove unused HTML/comments": "移除无用的 HTML 代码和注释",
    "Enable server-side compression (gzip/brotli)": "启用服务器端压缩（gzip/brotli）",
    "Reduce page weight:": "减小页面体积：",
    "Simplify content: shorter sentences, plain language, bullet points, active voice.": "简化内容：使用更短的句子、通俗的语言、项目符号列表和主动语态。",
    "Add source attributions to increase credibility:": "添加来源引用以提高可信度：",
    "Add comparison tables where applicable (pricing, features, vs. competitors):": "在适当位置添加对比表格（定价、功能、竞品比较）：",
    "AI engines frequently cite tabular data in comparison answers.": "AI 引擎在生成对比类回答时经常引用表格数据。",
    "Add more question-pattern headings that match how people prompt AI engines:": "添加更多与用户向 AI 引擎提问方式匹配的疑问句式标题：",
    "Follow each with a short, direct answer so AI engines can extract it.": "在每个问题标题后紧跟一个简短、直接的回答，以便 AI 引擎提取。",
    "Add breadcrumb navigation to help AI engines understand your site structure:": "添加面包屑导航，帮助 AI 引擎理解您的网站结构：",
    "Add more fields to strengthen knowledge panel eligibility:": "补充更多字段以增强知识面板的收录资格：",
    "Organize your llms.txt with sections like:": "按以下分区组织您的 llms.txt：",
    "Front-load facts into your first paragraph so AI engines can extract it directly:": "将关键事实前置到第一段，以便 AI 引擎直接提取：",
    "Aim for one definition-style sentence and one concrete stat in the first 25-120 words.": "力求在前 25–120 个词中包含一个定义式语句和一个具体数据。",
    "Write unique meta descriptions for each page. Duplicate descriptions": "为每个页面撰写独特的 meta description。重复的描述",
    "confuse AI engines about which page to cite for a given topic.": "会让 AI 引擎无法判断针对某一主题应引用哪个页面。",
    "Write unique <title> tags for each page. Identical titles cause keyword": "为每个页面撰写独特的 <title> 标签。相同的标题会导致关键词",
    "cannibalization — AI engines can't tell which page to cite for a given query.": "自相蚕食——AI 引擎无法判断针对某一查询应引用哪个页面。",
    "Pages with <100 words have too little content for AI engines. Add substantive, unique text.": "少于 100 词的页面内容过少，不利于 AI 引擎引用。请添加有实质内容的独特文本。",
    "Content overlap / possible cannibalization between pages:": "页面之间存在内容重叠/可能的关键词自相蚕食：",
    "Consolidate into one canonical page and 301-redirect the others.": "合并为一个权威页面，并将其他页面进行 301 重定向。",
    "Differentiate each page with distinct angles, examples, and keywords.": "通过不同的角度、案例和关键词来区分各个页面。",
    "Use rel=canonical to point near-duplicates to the primary page.": "使用 rel=canonical 将近似重复页面指向主页面。",
    "Cannibalization dilutes your AI visibility — pick the strongest page to surface.": "关键词自相蚕食会稀释您的 AI 可见度——选择最有优势的页面来展示。",
    "A Wikipedia page is one of the strongest entity signals for AI engines.": "维基百科页面是 AI 引擎识别实体的最强信号之一。",
    "Wikidata is free to edit and AI engines (especially Google Knowledge Graph) ingest it": "Wikidata 可免费编辑，且 AI 引擎（尤其是 Google Knowledge Graph）会主动采集其数据",
    "Mark up key terms and abbreviations:": "标注关键术语和缩写：",
    "This helps AI engines understand and define terms in your content.": "这有助于 AI 引擎理解和定义您内容中的术语。",
    "Diversify your content formats so AI engines encounter you in more contexts:": "丰富您的内容形式，让 AI 引擎在更多场景中接触到您：",
    "Set up a 301 redirect so one version redirects to the other:": "设置 301 重定向，将其中一个版本跳转到另一个版本：",
    "Then set the canonical URL to match the preferred version.": "然后将 canonical URL 设置为首选版本。",
    "Expand your brand presence on platforms that AI models train on:": "在 AI 模型训练所用的平台上扩展您的品牌影响力：",
    "Being present increases the probability of your brand being cited in AI answers,": "在这些平台上建立存在感，可以提高您的品牌在 AI 回答中被引用的概率，",
    "regardless of which source the AI pulls from.": "无论 AI 最终从哪个来源提取信息。",
    "Add missing trust signals so AI engines can verify who is behind the site:": "补充缺失的信任信号，以便 AI 引擎验证网站的运营主体：",
    "Use the same brand name everywhere.": "在所有平台上使用统一的品牌名称。",
    "No AI API keys found. Set at least one:": "未找到 AI API 密钥。请至少设置一个：",
    "This is a paid feature requiring AI API access.": "此为付费功能，需要 AI API 访问权限。",
    "Tip: Set an AI API key to see Citation Share analysis": "提示：设置 AI API 密钥即可查看引用份额分析",
    "see recommendations above": "请参阅上方建议",

    # ══════════════════════════════════════════════════════════
    # --ai-visibility mode
    # ══════════════════════════════════════════════════════════
    "AI VISIBILITY AUDIT v2": "AI 可见度审计 v2",
    "AI VISIBILITY AUDIT — RESULTS": "AI 可见度审计 — 结果",
    "Entity Definition": "实体定义",
    "Gap Detection": "缺口检测",
    "Total queries:": "查询总数：",
    "engine(s) x 3 runs =": "个引擎 x 3 次运行 =",
    "API calls": "次 API 调用",
    "Estimated time:": "预计耗时：",
    "Engine:": "引擎：",
    "All runs failed": "所有运行均失败",
    "STABLE — cited in": "稳定 — 被引用于",
    "UNSTABLE — cited in": "不稳定 — 被引用于",
    "runs": "次运行",
    "NOT CITED in any run": "在所有运行中均未被引用",
    "Framing:": "定位：",
    "Invalid": "无效",
    "API key. Skipping this engine.": "API 密钥。跳过此引擎。",
    "--- 1. Prompt Visibility ---": "--- 1. 提示词可见性 ---",
    "queries cited": "个查询被引用",
    "--- 2. Entity Clarity ---": "--- 2. 实体清晰度 ---",
    "Found": "找到",
    "definition(s) across engines:": "个跨引擎定义：",
    "No clear definitions found in AI answers": "AI 回答中未找到明确定义",
    "Possible brand confusion: AI describes": "可能存在品牌混淆：AI 将",
    "as a '": "描述为 '",
    "No brand confusion detected": "未检测到品牌混淆",
    "Entity Clarity:": "实体清晰度：",
    "--- 3. Competitor Position ---": "--- 3. 竞争定位 ---",
    "Top competitors mentioned alongside queries:": "查询中同时提及的主要竞争对手：",
    "mention(s)": "次提及",
    "Brand framing across all answers:": "所有回答中的品牌定位分析：",
    "Recommended (strongest)": "推荐（最强）",
    "Leader/major player": "领导者/主要参与者",
    "One of several options": "多个选项之一",
    "Passively mentioned": "被动提及",
    "Niche/experimental": "小众/实验性",
    "Not mentioned": "未被提及",
    "Competitor Position:": "竞争定位：",
    "--- 4. Answer Stability ---": "--- 4. 回答稳定性 ---",
    "Stable (all runs cited):": "稳定（所有运行均引用）：",
    "Unstable (some runs):": "不稳定（部分运行引用）：",
    "Absent (never cited):": "缺失（从未引用）：",
    "Answer Stability:": "回答稳定性：",
    "--- 5. Content Gaps ---": "--- 5. 内容缺口 ---",
    "content gap(s) detected:": "个内容缺口已检测到：",
    "Recommended actions to fill gaps:": "填补缺口的建议操作：",
    "Create dedicated pages for topics where": "为以下主题创建专门页面，其中",
    "is not cited": "未被引用",
    "Add FAQ sections answering these exact queries on your site": "在您的网站上添加 FAQ 栏目，回答这些具体问题",
    "Write comparison pages": "撰写对比页面",
    "for competitive queries": "用于竞争性查询",
    "Publish content on third-party platforms (blog posts, Reddit, GitHub)": "在第三方平台发布内容（博客文章、Reddit、GitHub）",
    "No major content gaps detected!": "未检测到重大内容缺口！",
    "Content Gap:": "内容缺口：",
    "Prompt Visibility": "提示词可见性",
    "Competitor Position": "竞争定位",
    "Answer Stability": "回答稳定性",
    "A — AI engines actively recommend this brand": "A — AI 引擎主动推荐该品牌",
    "B — Good visibility, some gaps to fill": "B — 可见性良好，存在部分缺口待填补",
    "C — Moderate visibility, significant gaps": "C — 可见性一般，存在较大缺口",
    "D — Low visibility, major work needed": "D — 可见性低，需要大量优化工作",
    "F — Not visible to AI engines": "F — 对 AI 引擎不可见",
    "Run periodically to track improvements over time.": "建议定期运行以跟踪改进情况。",
    "Tip: Use --queries to test your specific category prompts.": "提示：使用 --queries 测试您自定义的品类提示词。",

    # ══════════════════════════════════════════════════════════
    # --entity mode
    # ══════════════════════════════════════════════════════════
    "OPENAI_API_KEY environment variable not set.": "未设置 OPENAI_API_KEY 环境变量。",
    "This feature requires an OpenAI API key.": "此功能需要 OpenAI API key。",
    "ENTITY GEO AUDIT": "实体 GEO 审计",
    "Engine: OpenAI GPT-4o-mini (web search)": "引擎：OpenAI GPT-4o-mini（网络搜索）",
    "Phase 1: Knowledge Graph & Platform checks...": "阶段 1：知识图谱与平台检查……",
    "Phase 2: AI engine queries...": "阶段 2：AI 引擎查询……",
    "Analysis complete. Scoring...": "分析完成。正在评分……",
    "Knowledge Graph: Found on": "知识图谱：已在以下平台找到",
    "Knowledge Graph: Not found on Wikipedia or Wikidata": "知识图谱：未在 Wikipedia 或 Wikidata 上找到",
    "ENTITY GEO SCORECARD": "实体 GEO 评分卡",
    "Entity Recognition": "实体识别",
    "Category Association": "类别关联度",
    "Competitive Position": "竞争地位",
    "Sentiment & Framing": "情感与定位",
    "Knowledge Graph": "知识图谱",
    "Platform Footprint": "平台覆盖",
    "ENTITY GEO SCORE": "实体 GEO 总分",
    "Content Gap": "内容缺口",
    "Entity Clarity": "实体清晰度",
    "KEY FINDINGS": "主要发现",
    "Strong Knowledge Graph presence": "知识图谱覆盖良好",
    "Partial Knowledge Graph presence": "知识图谱覆盖部分",
    "Not found in Knowledge Graph (Wikipedia, Wikidata)": "未在知识图谱中找到（Wikipedia、Wikidata）",
    "Strong platform footprint": "平台覆盖良好",
    "Moderate platform footprint": "平台覆盖一般",
    "Weak platform footprint": "平台覆盖薄弱",
    "AI consistently recognizes": "AI 始终能识别",
    "AI partially recognizes": "AI 部分识别",
    "— inconsistent across queries": "—— 不同查询间结果不一致",
    "AI does not reliably recognize": "AI 无法可靠识别",
    "Entity definition is clear and consistent across runs": "实体定义清晰，各次查询结果一致",
    "Entity definition varies between queries — may indicate ambiguity": "实体定义在不同查询间有差异 —— 可能存在歧义",
    "Entity definition is unclear or confused with other entities": "实体定义不清晰或与其他实体混淆",
    "Strong category/domain association detected": "检测到强类别/领域关联",
    "Weak category association — AI may not map entity to its core domain": "类别关联较弱 —— AI 可能无法将实体映射到核心领域",
    "AI does not clearly associate entity with a specific category": "AI 未将实体与特定类别清晰关联",
    "Mentioned among top experts/leaders in field": "在领域顶级专家/领袖中被提及",
    "Mentioned but not prominently positioned among peers": "被提及但在同行中位置不突出",
    "Not mentioned among leaders in field": "未在领域领袖中被提及",
    "Competitive framing:": "竞争定位：",
    "Overall AI sentiment:": "AI 整体情感倾向：",
    "AI uses recommendation language": "AI 使用推荐性语言",
    "strongly positive": "强烈正面",
    "positive": "正面",
    "neutral": "中性",
    "negative": "负面",
    "mixed": "褒贬不一",
    "CONTENT GAPS (entity not mentioned for these queries)": "内容缺口（以下查询中未提及该实体）",
    "No content gaps detected — entity appears across all tested queries": "未检测到内容缺口 —— 实体出现在所有测试查询中",
    "Create content targeting these gap queries:": "创建针对这些缺口查询的内容：",

    # ══════════════════════════════════════════════════════════
    # --authority-audit mode
    # ══════════════════════════════════════════════════════════
    "Authority & Reputation Audit": "权威性与声誉审计",
    "1. Online Reviews": "1. 在线评价",
    "— profile found": "—— 已找到资料页",
    "— possible profile found": "—— 可能找到资料页",
    "— no profile detected": "—— 未检测到资料页",
    "— could not check (timeout/blocked)": "—— 无法检查（超时/被阻止）",
    "Review/Rating structured data found on site": "站点上发现评价/评分结构化数据",
    "review page from site": "评价页面（来自站点）",
    "Review presence: STRONG": "评价覆盖：强",
    "Review presence: MODERATE": "评价覆盖：中等",
    "No review presence detected on major platforms": "在主要平台上未检测到评价信息",
    "2. Awards, Accreditations & Affiliations": "2. 奖项、资质认证与合作关系",
    "Award/accreditation signals found in content:": "在内容中发现奖项/资质认证信号：",
    "No award/accreditation keywords detected in homepage content": "首页内容中未检测到奖项/资质认证关键词",
    "Award/certification structured data found": "发现奖项/认证结构化数据",
    "No award-specific schema markup": "无奖项专用 Schema 标记",
    "Trust/certification badge images found": "发现信任/认证徽章图片",
    "No trust badge images detected": "未检测到信任徽章图片",
    "Awards/accreditations: STRONG": "奖项/资质认证：强",
    "Awards/accreditations: MODERATE": "奖项/资质认证：中等",
    "Awards/accreditations: WEAK": "奖项/资质认证：弱",
    "3. Google Website Authority": "3. Google 网站权威性",
    "Checking Google index presence...": "正在检查 Google 索引情况……",
    "Google indexed pages:": "Google 已索引页面数：",
    "Domain not indexed by Google": "该域名未被 Google 索引",
    "Checking Knowledge Panel readiness...": "正在检查知识面板就绪度……",
    "Organization schema:": "Organization Schema：",
    "No Wikipedia/Wikidata links — consider creating entries for brand recognition": "无 Wikipedia/Wikidata 链接——建议创建条目以提升品牌辨识度",
    "Google authority signals: STRONG": "Google 权威性信号：强",
    "Google authority signals: MODERATE": "Google 权威性信号：中等",
    "Google authority signals: WEAK": "Google 权威性信号：弱",
    "4. Authoritative List Mentions": "4. 权威榜单提及",
    "— no mentions": "—— 无提及",
    "— package found:": "—— 已找到软件包：",
    "— not found": "—— 未找到",
    "— could not check": "—— 无法检查",
    "— company page found": "—— 已找到公司页面",
    "— not detected (may require login)": "—— 未检测到（可能需要登录）",
    "repo(s) found, top:": "个仓库，排名第一：",
    "— found": "—— 已找到",
    "— no profile found": "—— 未找到资料页",
    "authoritative domain(s) (.gov/.edu/.org)": "个权威域名（.gov/.edu/.org）",
    "Authoritative mentions: STRONG": "权威提及：强",
    "Authoritative mentions: MODERATE": "权威提及：中等",
    "Authoritative mentions: WEAK": "权威提及：弱",
    "Authority Score:": "权威性评分：",
    "A — Excellent": "A — 优秀",
    "B — Good": "B — 良好",
    "C — Needs improvement": "C — 有待改进",
    "D — Weak": "D — 薄弱",
    "F — Critical gaps": "F — 存在严重缺陷",
    "Breakdown:": "明细：",
    "Online Reviews:": "在线评价：",
    "Awards/Accreditations:": "奖项/资质认证：",
    "Google Authority:": "Google 权威性：",
    "Authoritative Mentions:": "权威提及：",

    # ══════════════════════════════════════════════════════════
    # --crawl-check / --crawl-test mode
    # ══════════════════════════════════════════════════════════
    "AI/LLM Crawl Activity Report": "AI/LLM 抓取活动报告",
    "No log files matched:": "未匹配到日志文件：",
    "Files matched:": "匹配文件：",
    "MB total": "MB（合计）",
    "Log period:": "日志时段：",
    "Total lines:": "总行数：",
    "Parsed:": "已解析：",
    "AI/LLM bot requests:": "AI/LLM 爬虫请求数：",
    "No AI/LLM crawler activity detected in this log file.": "在此日志文件中未检测到 AI/LLM 爬虫活动。",
    "This could mean:": "这可能意味着：",
    "AI bots haven't discovered your site yet": "AI 爬虫尚未发现您的站点",
    "The log file doesn't cover enough time": "日志文件覆盖的时间段不够长",
    "Bots are blocked by robots.txt or firewall": "爬虫被 robots.txt 或防火墙阻止",
    "Your CDN/proxy strips bot user agents": "您的 CDN/代理剥离了爬虫 User-Agent",
    "Bot Activity Breakdown": "爬虫活动明细",
    "Critical Bots NOT Detected": "关键爬虫未检测到",
    "Optional Bots NOT Detected": "可选爬虫未检测到",
    "bot(s)": "个爬虫",
    "Not seen:": "未检测到：",
    "AI Crawl Accessibility Test": "AI 抓取可访问性测试",
    "robots.txt Rules for AI Bots": "AI 爬虫的 robots.txt 规则",
    "robots.txt not found — all bots allowed by default": "robots.txt 未找到——默认允许所有爬虫",
    "— BLOCKED by robots.txt": "—— 被 robots.txt 阻止",
    "— allowed": "—— 已允许",
    "Simulated Bot Access Test": "模拟爬虫访问测试",
    "Sending requests to": "正在发送请求到",
    "with AI bot user agents...": "使用 AI 爬虫 User-Agent……",
    "(Checks if your server/CDN/WAF blocks bot traffic)": "（检查您的服务器/CDN/WAF 是否阻止爬虫流量）",
    "Baseline (browser):": "基准（浏览器）：",
    "— BLOCKED by server/WAF": "—— 被服务器/WAF 阻止",
    "suspiciously small vs baseline": "与基准相比可疑地小",
    "request failed:": "请求失败：",
    "All tested bots can access your site successfully.": "所有测试的爬虫均可成功访问您的站点。",
    "Common Crawl Index Check": "Common Crawl 索引检查",
    "page(s) in Common Crawl index": "个页面在 Common Crawl 索引中",
    "Domain not found in Common Crawl index": "在 Common Crawl 索引中未找到该域名",
    "Could not reach Common Crawl index — their servers may be slow, try again later": "无法连接 Common Crawl 索引——其服务器可能较慢，请稍后重试",
    "Your site appears accessible to all major AI crawlers.": "您的站点对所有主要 AI 爬虫均可访问。",
    "Issues found:": "发现的问题：",
    "bot(s) blocked by robots.txt,": "个爬虫被 robots.txt 阻止，",
    "bot(s) blocked by server/WAF": "个爬虫被服务器/WAF 阻止",

    # AI_CRAWLERS powers values
    "ChatGPT training data": "ChatGPT 训练数据",
    "ChatGPT live browsing": "ChatGPT 实时浏览",
    "Claude training data": "Claude 训练数据",
    "Anthropic crawling": "Anthropic 爬取",
    "Perplexity AI answers": "Perplexity AI 回答",
    "Google AI training": "Google AI 训练",
    "Bing link preview (Teams/Outlook)": "Bing 链接预览（Teams/Outlook）",
    "Common Crawl (used by many LLMs)": "Common Crawl（被众多 LLM 使用）",
    "Knowledge graph extraction": "知识图谱提取",
    "Apple Intelligence / Siri": "Apple Intelligence / Siri",
    "Apple search / Siri": "Apple 搜索 / Siri",
    "Cohere models": "Cohere 模型",
    "You.com AI search": "You.com AI 搜索",
    "SEO analytics (AI-adjacent)": "SEO 分析（AI 相关）",

    # ══════════════════════════════════════════════════════════
    # --citation-check mode
    # ══════════════════════════════════════════════════════════
    "PERPLEXITY_API_KEY environment variable not set.": "PERPLEXITY_API_KEY 环境变量未设置。",
    "This is a paid feature. Set your API key to use it:": "这是一项付费功能。请设置 API 密钥后使用：",
    "AI Citation Check (Powered by Perplexity)": "AI 引用检查（由 Perplexity 驱动）",
    "Sending brand-relevant queries to Perplexity AI...": "正在向 Perplexity AI 发送品牌相关查询……",
    "appears in AI-generated citations...": "是否出现在 AI 生成的引用中……",
    "Invalid API key. Check your PERPLEXITY_API_KEY.": "API 密钥无效。请检查 PERPLEXITY_API_KEY。",
    "Rate limited. Waiting before next query...": "已被限流。正在等待后重试……",
    "CITED!": "被引用！",
    "citation(s) from": "条引用来自",
    "MENTIONED in answer (no direct citation link)": "在回答中被提及（无直接引用链接）",
    "Not cited.": "未被引用。",
    "other source(s) cited instead.": "个其他来源被引用。",
    "AI CITATION REPORT": "AI 引用报告",
    "No queries completed successfully.": "无查询成功完成。",
    "Citation Rate:": "引用率：",
    "Direct Links:": "直接链接：",
    "citation(s) pointing to": "条引用指向",
    "A — Excellent AI visibility": "A — AI 可见度优秀",
    "B — Good AI visibility": "B — AI 可见度良好",
    "C — Moderate AI visibility": "C — AI 可见度中等",
    "D — Low AI visibility": "D — AI 可见度偏低",
    "F — Not visible to AI engines": "F — 对 AI 引擎不可见",
    "AI Visibility:": "AI 可见度：",
    "Query Results:": "查询结果：",
    "CITED": "已引用",
    "NOT CITED": "未引用",
    "Recommendations to improve AI citation rate:": "提高 AI 引用率的建议：",
    "Ensure your site has comprehensive, authoritative content about your brand": "确保您的站点拥有关于品牌的全面、权威内容",
    "Add structured data (JSON-LD) with Organization schema": "添加包含 Organization Schema 的结构化数据（JSON-LD）",
    "Create an llms.txt file to help AI engines understand your site": "创建 llms.txt 文件以帮助 AI 引擎了解您的站点",
    "Build presence on platforms AI models reference (Wikipedia, Reddit, GitHub)": "在 AI 模型引用的平台上建立影响力（Wikipedia、Reddit、GitHub）",
    "Publish original research, data, and expert content that AI engines want to cite": "发布 AI 引擎乐于引用的原创研究、数据和专家内容",
    "Ensure AI crawlers (GPTBot, ClaudeBot, PerplexityBot) are not blocked in robots.txt": "确保 robots.txt 未屏蔽 AI 爬虫（GPTBot、ClaudeBot、PerplexityBot）",
    "Results reflect Perplexity AI's current knowledge. Other AI engines": "结果反映 Perplexity AI 当前的知识。其他 AI 引擎",
    "(ChatGPT, Gemini, Claude) may differ. Run periodically to track changes.": "（ChatGPT、Gemini、Claude）的结果可能不同。建议定期运行以跟踪变化。",
})


def main():
    global SHOW_FIX
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
                             "Sends brand-relevant queries to Perplexity and checks if your domain "
                             "appears in AI-generated answer citations. "
                             "Requires OPENROUTER_API_KEY environment variable.")
    parser.add_argument("--ai-visibility", metavar="URL",
                        help="[PAID] Comprehensive AI Visibility Audit. Checks if AI engines would "
                             "recommend your brand for relevant queries. Tests entity clarity, "
                             "competitor positioning, answer stability, and content gaps across "
                             "multiple AI engines. Requires OPENROUTER_API_KEY environment variable.")
    parser.add_argument("--queries", metavar="QUERY", nargs="+",
                        help="Custom queries for --ai-visibility. Test specific prompts relevant "
                             "to your niche. Example: --queries 'best AI payment tools' 'x402 tools'")
    parser.add_argument("--aeo-visibility", metavar="URL",
                        help="AEO (Answer Engine Optimization) audit. Checks how well a page "
                             "is optimized to appear in AI-generated answers: FAQ readiness, "
                             "question-pattern headings, direct answer snippets, answer engine "
                             "schema (FAQPage/HowTo/QAPage), content structure, readability, "
                             "and heading hierarchy. Free — no API keys required.")
    parser.add_argument("--entity", metavar="NAME",
                        help="[PAID] Audit GEO readiness of a brand, product, or person by name. "
                             "Queries AI engines to assess entity recognition, clarity, competitive "
                             "position, sentiment, and content gaps. Requires OPENROUTER_API_KEY environment variable.")
    parser.add_argument("--entity-type", metavar="TYPE", default="brand",
                        choices=["brand", "product", "person"],
                        help="Entity type for --entity audit: brand, product, or person (default: brand)")
    parser.add_argument("--report", nargs="?", const="pdf", default=None,
                        choices=["pdf", "json", "html"],
                        metavar="FORMAT",
                        help="Also save the run's output as a report at "
                             "~/geo_reports/<timestamp>/report.<ext>. "
                             "Default format is pdf. Pass 'json' for a machine-readable "
                             "score document or 'html' for a styled standalone page. "
                             "Examples: --report | --report json | --report html")
    parser.add_argument("--lang", choices=["en", "zh"], default="en",
                        help="Output language: en (English) or zh (Chinese)")
    args = parser.parse_args()

    SHOW_FIX = args.fix

    report_format = args.report  # None | "pdf" | "json" | "html"
    capture_output = report_format in ("pdf", "html")
    report_buffer = io.StringIO() if capture_output else None
    original_stdout = None
    if capture_output:
        original_stdout = sys.stdout
        sys.stdout = _TeeStream(original_stdout, report_buffer)

    try:
        _dispatch(args, parser)
    finally:
        if capture_output:
            sys.stdout = original_stdout
        if report_format:
            import os
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            report_dir = os.path.expanduser(f"~/geo_reports/{timestamp}")
            text_output = report_buffer.getvalue() if report_buffer else ""

            if report_format == "pdf":
                report_path = os.path.join(report_dir, "report.pdf")
                try:
                    _write_text_pdf(report_path, text_output)
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
        # Merge all patterns into one combined list of files
        import glob as glob_mod
        import os
        all_files = []
        for pattern in args.crawl_check:
            resolved = resolve_log_paths(pattern)
            all_files.extend(resolved)
        # Deduplicate while preserving order
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
            # Pass a synthetic pattern string for display, then feed files directly
            display = " ".join(args.crawl_check)
            crawl_check_files(unique_files, display)
    elif args.url:
        generate_score(args.url)
    else:
        parser.error("Provide a URL or a mode flag: --compare, --crawl-check, --crawl-test, --citation-check, --ai-visibility, --aeo-visibility, --entity")


if __name__ == "__main__":
    main()
