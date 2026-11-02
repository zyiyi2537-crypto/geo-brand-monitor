"""All 25 `check_*` functions — the core inspection logic.

Migrated from backend/geo_checker/__main__.py lines 215-3141, which
already carried the i18n-aware emit_check/emit_fix calls (merged from root
/geo_checker.py during the fork's i18n work).

These functions share global state via the `state` module (`_scores`,
`_page_cache`, `SHOW_FIX`). Concurrent invocation within the same process
would race; see backend/geo/services/geo_checker.py::_geo_checker_lock.

Keeping all 25 in a single file (rather than splitting to checks/*.py) so
that `instrument_checks(checks_module)` in advanced_runners can wrap every
function in one pass for timing telemetry.
"""

import json
import re
import subprocess
import time
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

from .constants import AI_BOTS, AI_CRAWLERS, PASS, WARN, FAIL, INFO, FIX
from .io import fetch, get_soup, get_text_content, flesch_kincaid_grade
from .output import emit_check, emit_fix, fix, print
from .state import track_score


def check_https(url):
    print("\n--- HTTPS ---")
    parsed = urlparse(url)
    if parsed.scheme == "https":
        emit_check(PASS, "result.checks.https.uses_https", "Site uses HTTPS")
        track_score("HTTPS", 5, 5)
        return True
    else:
        emit_check(
            FAIL,
            "result.checks.https.not_https",
            "Site does not use HTTPS — AI engines prefer secure sites",
        )
        emit_fix("result.fixes.https.enable_https", "Install an SSL/TLS certificate (free via Let's Encrypt) and redirect all HTTP traffic to HTTPS.\nExample nginx: return 301 https://$host$request_uri;")
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
        emit_check(FAIL, "result.checks.robots.not_found", f"robots.txt not found at {url}", {"url": url})
        emit_fix("result.fixes.robots.create", "Create a robots.txt file at the root of your site.\nMinimal example:\n  User-agent: *\n  Allow: /\n  Sitemap: https://yoursite.com/sitemap.xml")
        track_score("robots.txt", 0, 8)
        return

    emit_check(PASS, "result.checks.robots.found", f"robots.txt found ({len(resp.text)} bytes)", {"bytes": len(resp.text)})
    track_score("robots.txt", 3, 3)
    lines = resp.text.splitlines()

    has_sitemap_ref = any(line.strip().lower().startswith("sitemap:") for line in lines)
    if has_sitemap_ref:
        emit_check(PASS, "result.checks.robots.sitemap_ref_present", "robots.txt references a sitemap")
        track_score("robots.txt", 2, 2)
    else:
        emit_check(WARN, "result.checks.robots.sitemap_ref_missing", "robots.txt does not reference a sitemap")
        emit_fix("result.fixes.robots.add_sitemap_directive", "Add a Sitemap directive to your robots.txt:\n  Sitemap: https://yoursite.com/sitemap.xml")
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
        emit_check(WARN, "result.checks.robots.wildcard_blocks_all", "Wildcard user-agent blocks all crawlers (Disallow: /)")
        emit_fix("result.fixes.robots.unblock_wildcard", "Change 'Disallow: /' under 'User-agent: *' to 'Allow: /' if you want AI crawlers to index your site.\nYou can selectively block specific bots while allowing others.")
    if blocked:
        emit_check(WARN, "result.checks.robots.bots_blocked", f"AI bots explicitly BLOCKED: {', '.join(blocked)}", {"bots": ", ".join(blocked)})
        emit_fix("result.fixes.robots.unblock_bots", "To allow these AI bots, remove or modify their Disallow directives in robots.txt.\nExample to allow GPTBot:\n  User-agent: GPTBot\n  Allow: /")
    if allowed:
        emit_check(PASS, "result.checks.robots.bots_with_directives", f"AI bots with directives (not blocked): {', '.join(allowed)}", {"bots": ", ".join(allowed)})
    if not_mentioned:
        emit_check(INFO, "result.checks.robots.bots_inherit_wildcard", f"AI bots not mentioned (inherit wildcard rules): {', '.join(not_mentioned)}", {"bots": ", ".join(not_mentioned)})

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
            emit_check(PASS, "result.checks.robots.ai_txt_found",
                       f"{ai_path} found — strategic AI crawler policy declared", {"path": ai_path})
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
        emit_check(INFO, "result.checks.robots.ai_txt_not_found",
                   "No ai.txt or .well-known/ai.txt found — emerging standard for AI-specific policies")
        emit_fix("result.fixes.robots.add_ai_txt",
                 "Consider an ai.txt file at your site root (spec: spawning.ai/ai-txt) to declare\n"
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
            emit_check(PASS, "result.checks.llms.found", f"{filename} found ({len(lines)} lines, {len(text)} bytes)", {"filename": filename, "lines": len(lines), "bytes": len(text)})

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
                emit_check(PASS, "result.checks.llms.title_present", f"Title: {title_line.strip()}", {"title": title_line.strip()})
                llms_score += 0.5
            else:
                emit_check(WARN, "result.checks.llms.title_missing", "No markdown title (# heading) — recommended by llms.txt spec")
                emit_fix("result.fixes.llms.add_title", f"Add a title as the first line of {filename}:\n  # Your Site Name", {"filename": filename})

            if has_description:
                emit_check(PASS, "result.checks.llms.description_present", "Contains descriptive text")
            else:
                emit_check(WARN, "result.checks.llms.description_missing", "No descriptive text found — should explain what the site/org does")
                emit_fix("result.fixes.llms.add_description", "Add a paragraph below the title explaining what your site/org does:\n  # Your Site\n  A brief description of your site and what it offers.")

            if has_sections:
                section_count = sum(1 for l in lines if l.strip().startswith("## "))
                emit_check(PASS, "result.checks.llms.sections_found", f"{section_count} section(s) found (## headings)", {"count": section_count})
                llms_score += 0.5
            else:
                emit_check(WARN, "result.checks.llms.sections_missing", "No sections (## headings) — consider organizing content into sections")
                emit_fix("result.fixes.llms.add_sections", "Organize your llms.txt with sections like:\n  ## Documentation\n  ## API Reference\n  ## Blog")

            if has_links:
                link_count = sum(1 for l in lines if "](http" in l or "](/" in l or "http://" in l or "https://" in l)
                emit_check(PASS, "result.checks.llms.links_found", f"{link_count} link(s) to resources found", {"count": link_count})
                llms_score += 0.5
            else:
                emit_check(WARN, "result.checks.llms.links_missing", "No links found — llms.txt should link to key resources")
                emit_fix("result.fixes.llms.add_links", "Add markdown links to your key pages:\n  - [Documentation](https://yoursite.com/docs)\n  - [API Reference](https://yoursite.com/api)")

            if has_blockquotes:
                emit_check(PASS, "result.checks.llms.blockquotes_present", "Blockquote descriptions (>) present")

            if len(text) < 100:
                emit_check(WARN, "result.checks.llms.too_short", f"File is very short ({len(text)} bytes) — may be a placeholder", {"bytes": len(text)})
                emit_fix("result.fixes.llms.expand_content", "Expand the file with meaningful content about your site, its purpose, key pages, and resources.")
        else:
            emit_check(FAIL, "result.checks.llms.file_not_found", f"{filename} not found", {"filename": filename})
            if filename == "llms.txt":
                emit_fix("result.fixes.llms.create_file", "Create an llms.txt file at your site root. Example structure:\n  # Your Site Name\n  A brief description of your site.\n  \n  ## Documentation\n  > Overview of your docs\n  - [Getting Started](https://yoursite.com/docs/start)\n  \n  ## API\n  > API reference\n  - [API Docs](https://yoursite.com/api)")
            elif filename == "llms-full.txt":
                emit_fix("result.fixes.llms.create_full_file", "Create llms-full.txt with expanded content — a more detailed version of llms.txt\nwith full descriptions, complete resource listings, and deeper context for AI models.")

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
            emit_check(INFO, "result.checks.well_known.file_not_found", f"{path} not found — {description}", {"path": path, "description": description})
            continue

        ctype = (resp.headers.get("Content-Type") or "").lower()
        body = resp.text.lstrip()
        looks_html = ctype.startswith("text/html") or body[:15].lower().startswith(("<!doctype", "<html"))

        if path.endswith(".json"):
            if looks_html:
                emit_check(INFO, "result.checks.well_known.file_not_found", f"{path} not found — {description} (server returned HTML fallback)", {"path": path, "description": description})
                continue
            try:
                data = json.loads(resp.text)
            except json.JSONDecodeError:
                emit_check(WARN, "result.checks.well_known.invalid_json", f"{path} exists but contains invalid JSON", {"path": path})
                emit_fix("result.fixes.well_known.fix_invalid_json", f"Validate and fix the JSON in {path} — use a JSON linter to check for syntax errors.", {"path": path})
                found_any = True
                wk_found += 1
                continue
            found_any = True
            wk_found += 1
            emit_check(PASS, "result.checks.well_known.file_found", f"{path} found — {description}", {"path": path, "description": description})
            if path.endswith("ai-plugin.json"):
                name = data.get("name_for_human", data.get("name", "unknown"))
                print(f"         Plugin name: {name}")
        else:
            found_any = True
            wk_found += 1
            emit_check(PASS, "result.checks.well_known.file_found", f"{path} found — {description}", {"path": path, "description": description})

    if not found_any:
        print(f"  [{INFO}] No .well-known AI discovery files found")
        emit_fix("result.fixes.well_known.add_security_txt", "Consider adding .well-known/security.txt (RFC 9116) as a trust signal:\n  Contact: mailto:security@yoursite.com\n  Preferred-Languages: en\n  Canonical: https://yoursite.com/.well-known/security.txt")

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
            emit_check(PASS, "result.checks.sitemap.found", f"Sitemap found at {path} ({url_count} <loc> entries)", {"path": path, "count": url_count})
            track_score("Sitemap", 4, 4)

            has_lastmod = "<lastmod>" in resp.text
            if has_lastmod:
                emit_check(PASS, "result.checks.sitemap.lastmod_present", "Sitemap includes <lastmod> timestamps")
                track_score("Sitemap", 3, 3)
            else:
                emit_check(WARN, "result.checks.sitemap.lastmod_missing", "Sitemap missing <lastmod> timestamps — helps AI engines know content freshness")
                emit_fix("result.fixes.sitemap.add_lastmod", "Add <lastmod> to each <url> entry in your sitemap:\n  <url>\n    <loc>https://yoursite.com/page</loc>\n    <lastmod>2025-01-15</lastmod>\n  </url>")
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
        emit_check(FAIL, "result.checks.sitemap.not_found", "No sitemap.xml found")
        emit_fix("result.fixes.sitemap.create_file", "Create a sitemap.xml at your site root. Example:\n  <?xml version=\"1.0\" encoding=\"UTF-8\"?>\n  <urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">\n    <url>\n      <loc>https://yoursite.com/</loc>\n      <lastmod>2025-01-15</lastmod>\n    </url>\n  </urlset>\nMost CMS platforms (WordPress, Next.js, etc.) can auto-generate sitemaps.")
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
        emit_check(FAIL, "result.checks.platform_reg.fetch_failed", "Could not fetch homepage")
        track_score("Platform Registration", 0, 7)
        return

    # Google Search Console verification
    google_verify = soup.find("meta", attrs={"name": "google-site-verification"})
    if google_verify and google_verify.get("content"):
        emit_check(PASS, "result.checks.platform_reg.gsc_verified", "Google Search Console verification tag found")
    else:
        # Check for verification file
        gsc_resp = fetch(urljoin(base_url, "/google*.html"), timeout=5)
        # Can't glob on server, so just note the absence
        emit_check(WARN, "result.checks.platform_reg.gsc_missing", "No Google Search Console verification tag found")
        emit_fix("result.fixes.search_reg.google_console", "Register your site with Google Search Console (https://search.google.com/search-console):\n  1. Add your property (URL prefix or domain)\n  2. Verify ownership via meta tag, DNS, or HTML file\n  3. Submit your sitemap.xml under Sitemaps\n  4. Monitor indexing status and fix any crawl errors\nThis is critical — Google's AI Overviews and SGE pull from the Google index.")

    # Bing Webmaster Tools verification
    bing_verify = soup.find("meta", attrs={"name": "msvalidate.01"})
    if bing_verify and bing_verify.get("content"):
        emit_check(PASS, "result.checks.platform_reg.bing_verified", "Bing Webmaster Tools verification tag found")
    else:
        emit_check(WARN, "result.checks.platform_reg.bing_missing", "No Bing Webmaster Tools verification tag found")
        emit_fix("result.fixes.search_reg.bing_webmaster", "Register your site with Bing Webmaster Tools (https://www.bing.com/webmasters):\n  1. Add your site and verify ownership\n  2. Submit your sitemap.xml\n  3. This is essential — Bing's index powers Microsoft Copilot, ChatGPT (via Bing search),\n     and other AI assistants that use Bing as their search backend.")

    # Yandex verification (feeds into some AI systems)
    yandex_verify = soup.find("meta", attrs={"name": "yandex-verification"})
    if yandex_verify and yandex_verify.get("content"):
        emit_check(PASS, "result.checks.platform_reg.yandex_verified", "Yandex Webmaster verification tag found")
    else:
        emit_check(INFO, "result.checks.platform_reg.yandex_missing", "No Yandex Webmaster verification tag — relevant if targeting international AI platforms")

    # IndexNow support — check for key file
    indexnow_found = False
    # Check for IndexNow key in common locations
    for key_path in ["/.well-known/indexnow", "/indexnow"]:
        inow_url = urljoin(base_url, key_path)
        inow_resp = fetch(inow_url, timeout=5)
        if inow_resp and inow_resp.status_code == 200 and len(inow_resp.text.strip()) > 0:
            indexnow_found = True
            emit_check(PASS, "result.checks.platform_reg.indexnow_endpoint", f"IndexNow endpoint found at {key_path} — enables instant index notifications", {"path": key_path})
            break

    # Also check for IndexNow meta tag or key file pattern
    if not indexnow_found:
        # Some sites host the key as a text file at root
        indexnow_meta = soup.find("meta", attrs={"name": "indexnow"})
        if indexnow_meta:
            indexnow_found = True
            emit_check(PASS, "result.checks.platform_reg.indexnow_meta", "IndexNow meta tag found")

    if not indexnow_found:
        emit_check(INFO, "result.checks.platform_reg.indexnow_missing", "No IndexNow integration detected")
        emit_fix("result.fixes.search_reg.indexnow", "Set up IndexNow for instant indexing by Bing, Yandex, and others:\n  1. Generate an API key at https://www.indexnow.org/\n  2. Host the key file at your site root: https://yoursite.com/{key}.txt\n  3. Notify search engines when content changes:\n     POST https://api.indexnow.org/indexnow\n     {\"host\": \"yoursite.com\", \"key\": \"your-key\", \"urlList\": [\"https://yoursite.com/updated-page\"]}\n  4. Many CMS plugins (WordPress, etc.) support IndexNow automatically.")

    # Check for Pinterest verification (some AI visual search)
    pinterest_verify = soup.find("meta", attrs={"name": "p:domain_verify"})
    if pinterest_verify:
        emit_check(PASS, "result.checks.platform_reg.pinterest_verified", "Pinterest domain verification found")

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
        registered_text = ", ".join(registered)
        emit_check(PASS, "result.checks.platform_reg.summary_registered", f"Registered: {registered_text}", {"platforms": registered_text})
    if not_registered:
        missing_text = ", ".join(not_registered)
        emit_check(WARN, "result.checks.platform_reg.summary_missing", f"Not detected: {missing_text}", {"platforms": missing_text})

        emit_fix("result.fixes.search_reg.submit_all", "Having files like sitemap.xml and robots.txt is not enough on its own.\nYou must also register and submit them to each platform:\n  \n  Google Search Console → Submit sitemap → Powers Google AI Overviews / SGE\n  Bing Webmaster Tools  → Submit sitemap → Powers Copilot, ChatGPT (Bing backend)\n  IndexNow              → Auto-notify   → Instant indexing for Bing, Yandex, Naver\n  \nWithout registration, search engines may find your sitemap eventually via crawling,\nbut submission ensures faster, more reliable indexing.")

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
        emit_check(FAIL, "result.checks.structured_data.fetch_failed", "Could not fetch homepage")
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
        emit_check(PASS, "result.checks.structured_data.jsonld_found", f"Found {len(json_ld_scripts)} JSON-LD block(s)", {"count": len(json_ld_scripts)})
        track_score("Structured Data", 3, 3)
        parsed_types = 0
        all_collected = []
        for i, script in enumerate(json_ld_scripts):
            try:
                data = json.loads(script.string)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    _collect_types(item, all_collected)
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
            emit_check(PASS, "result.checks.structured_data.granular_types", f"Granular schema types present: {labels}", {"types": labels})

            # Extra credit for Product with reviews
            product_has_reviews = False
            for name, obj in all_collected:
                if name == "Product":
                    if obj.get("review") or obj.get("aggregateRating") or obj.get("reviews"):
                        product_has_reviews = True
                        break
            if "Product" in present_granular:
                if product_has_reviews:
                    emit_check(PASS, "result.checks.structured_data.product_reviews", "Product schema includes reviews/ratings — strong AI signal")
                else:
                    emit_check(WARN, "result.checks.structured_data.product_no_reviews", "Product schema present but no review/aggregateRating field")
                    emit_fix("result.fixes.structured.add_product_reviews", "Add review and aggregateRating to your Product schema:\n"
                        "  \"aggregateRating\": {\"@type\": \"AggregateRating\", \"ratingValue\": \"4.6\", \"reviewCount\": \"128\"},\n"
                        "  \"review\": [{\"@type\": \"Review\", \"author\": ..., \"reviewRating\": ...}]")

            granular_score = min(len(present_granular), 4)
            track_score("Structured Data", granular_score, 4)
        elif present_generic:
            emit_check(WARN, "result.checks.structured_data.generic_only", f"Only generic schema types found ({', '.join(sorted(present_generic))}) — add granular types for richer AI extraction", {"types": ", ".join(sorted(present_generic))})
            emit_fix("result.fixes.structured.upgrade_to_granular", "Upgrade from generic WebPage/CreativeWork to specific types:\n"
                "  \u2022 How-to content \u2192 HowTo with step list\n"
                "  \u2022 Q&A pages     \u2192 FAQPage with Question/Answer pairs\n"
                "  \u2022 Products      \u2192 Product with offers + aggregateRating\n"
                "  \u2022 Recipes       \u2192 Recipe with ingredients and instructions\n"
                "  \u2022 Articles      \u2192 NewsArticle or BlogPosting\n"
                "Granular types give AI engines far more extractable facts than WebPage.")
            track_score("Structured Data", 1, 4)
        else:
            emit_check(INFO, "result.checks.structured_data.nonstandard_types", "Non-standard @types detected — consider using schema.org granular types")
            track_score("Structured Data", 1, 4)
    else:
        emit_check(WARN, "result.checks.structured_data.jsonld_missing", "No JSON-LD structured data found — helps AI engines understand your content")
        track_score("Structured Data", 0, 7)
        emit_fix("result.fixes.structured.add_organization_jsonld", "Add JSON-LD structured data to your <head>. Example for an Organization:\n  <script type=\"application/ld+json\">\n  {\n    \"@context\": \"https://schema.org\",\n    \"@type\": \"Organization\",\n    \"name\": \"Your Company\",\n    \"url\": \"https://yoursite.com\",\n    \"description\": \"What your company does\"\n  }\n  </script>\nUse Google's Rich Results Test to validate: https://search.google.com/test/rich-results")

    has_schema_ref = 'schema.org' in resp.text
    if has_schema_ref and not json_ld_scripts:
        emit_check(INFO, "result.checks.structured_data.schema_ref_only", "schema.org references found (possibly microdata or RDFa)")


# ---------------------------------------------------------------------------
# 7. Meta Tags
# ---------------------------------------------------------------------------
def check_meta_tags(base_url):
    print("\n--- Meta Tags ---")
    resp, soup = get_soup(base_url)
    if not soup:
        emit_check(FAIL, "result.checks.meta.fetch_failed", "Could not fetch homepage")
        track_score("Meta Tags", 0, 7)
        return

    meta_score = 0
    title = soup.find("title")
    if title and title.string and title.string.strip():
        title_text = title.string.strip()[:80]
        emit_check(PASS, "result.checks.meta.title_found", f"<title> found: \"{title_text}\"", {"title": title_text})
        meta_score += 1.5
    else:
        emit_check(FAIL, "result.checks.meta.title_missing", "Missing <title> tag")
        emit_fix("result.fixes.meta.add_title", "Add a <title> tag in your <head>:\n  <title>Your Page Title — Your Brand</title>\nKeep it under 60 characters and include your primary keyword.")

    desc = soup.find("meta", attrs={"name": "description"})
    if desc and desc.get("content", "").strip():
        content = desc["content"].strip()
        emit_check(PASS, "result.checks.meta.description_found", f"Meta description found ({len(content)} chars)", {"chars": len(content)})
        meta_score += 1.5
        if len(content) < 50:
            emit_check(WARN, "result.checks.meta.description_too_short", "Meta description is very short — aim for 120-160 characters")
            emit_fix("result.fixes.meta.expand_description", "Expand your meta description to 120-160 characters. Include a clear value proposition and primary keywords.")
    else:
        emit_check(FAIL, "result.checks.meta.description_missing", "Missing meta description")
        emit_fix("result.fixes.meta.add_description", "Add a meta description in your <head>:\n  <meta name=\"description\" content=\"A 120-160 character summary of your page content, including key topics and value proposition.\">\nThis is often what AI engines use when summarizing your site.")

    canonical = soup.find("link", rel="canonical")
    if canonical and canonical.get("href"):
        emit_check(PASS, "result.checks.meta.canonical_found", f"Canonical URL set: {canonical['href']}", {"url": canonical['href']})
        meta_score += 1
    else:
        emit_check(WARN, "result.checks.meta.canonical_missing", "No canonical URL — can cause duplicate content issues for AI engines")
        emit_fix("result.fixes.meta.add_canonical", "Add a canonical link in your <head>:\n  <link rel=\"canonical\" href=\"https://yoursite.com/current-page\" />\nThis tells AI engines which version of a page is the authoritative one.")

    required_og = ["og:title", "og:description", "og:image", "og:url", "og:type"]
    present_og = {
        tag.get("property"): (tag.get("content") or "").strip()
        for tag in soup.find_all("meta", property=re.compile(r"^og:"))
        if tag.get("property")
    }
    found_og = [name for name in required_og if present_og.get(name)]
    missing_og = [name for name in required_og if not present_og.get(name)]
    if found_og:
        emit_check(PASS, "result.checks.meta.og_tags_found", f"Open Graph tags present: {', '.join(found_og)}", {"tags": ", ".join(found_og)})
    if missing_og:
        emit_check(WARN, "result.checks.meta.og_tags_missing", f"Missing Open Graph tags: {', '.join(missing_og)} — shown by AI engines and link previews", {"missing": ", ".join(missing_og)})
        emit_fix("result.fixes.meta.add_og", "Add the missing Open Graph tags in your <head>:\n  <meta property=\"og:title\" content=\"Page Title\" />\n  <meta property=\"og:description\" content=\"Page description\" />\n  <meta property=\"og:type\" content=\"website\" />\n  <meta property=\"og:url\" content=\"https://yoursite.com/page\" />\n  <meta property=\"og:image\" content=\"https://yoursite.com/image.jpg\" />\nog:image is what makes your logo/thumbnail appear when links are shared.")
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
        emit_check(PASS, "result.checks.meta.twitter_cards_found", f"Twitter Card tags present: {', '.join(found_tw)}", {"tags": ", ".join(found_tw)})
    if missing_tw:
        emit_check(INFO, "result.checks.meta.twitter_cards_missing", f"Missing Twitter Card tags: {', '.join(missing_tw)} — improves X/Twitter link previews", {"missing": ", ".join(missing_tw)})
        emit_fix("result.fixes.meta.add_twitter_cards", "Add Twitter Card meta tags in your <head>:\n  <meta name=\"twitter:card\" content=\"summary_large_image\" />\n  <meta name=\"twitter:title\" content=\"Page Title\" />\n  <meta name=\"twitter:description\" content=\"Page description\" />\n  <meta name=\"twitter:image\" content=\"https://yoursite.com/image.jpg\" />")

    html_tag = soup.find("html")
    if html_tag and html_tag.get("lang"):
        emit_check(PASS, "result.checks.meta.lang_declared", f"Language declared: {html_tag['lang']}", {"lang": html_tag['lang']})
        meta_score += 1
    else:
        emit_check(WARN, "result.checks.meta.lang_missing", "No lang attribute on <html> — helps AI engines understand content language")
        emit_fix("result.fixes.meta.add_lang", "Add a lang attribute to your <html> tag:\n  <html lang=\"en\">")

    hreflangs = soup.find_all("link", rel="alternate", hreflang=True)
    if hreflangs:
        langs = [tag.get("hreflang") for tag in hreflangs]
        emit_check(PASS, "result.checks.meta.hreflang_found", f"Hreflang tags found for: {', '.join(langs)}", {"langs": ", ".join(langs)})
        meta_score += 1
    else:
        emit_check(INFO, "result.checks.meta.hreflang_missing", "No hreflang tags — add these if your site supports multiple languages")
        emit_fix("result.fixes.meta.add_hreflang", "If your site is multilingual, add hreflang tags:\n  <link rel=\"alternate\" hreflang=\"en\" href=\"https://yoursite.com/en/page\" />\n  <link rel=\"alternate\" hreflang=\"es\" href=\"https://yoursite.com/es/page\" />\n  <link rel=\"alternate\" hreflang=\"x-default\" href=\"https://yoursite.com/page\" />")

    track_score("Meta Tags", meta_score, 7)


# ---------------------------------------------------------------------------
# 8. Content Accessibility
# ---------------------------------------------------------------------------
def check_content_accessibility(base_url):
    print("\n--- Content Accessibility ---")
    resp, soup = get_soup(base_url)
    if not soup:
        emit_check(FAIL, "result.checks.content_access.fetch_failed", "Could not fetch homepage")
        track_score("Content Accessibility", 0, 6)
        return

    ca_score = 0
    text = get_text_content(soup)
    word_count = len(text.split())

    if word_count > 200:
        emit_check(PASS, "result.checks.content_access.words_ok", f"Homepage has {word_count} words in initial HTML", {"count": word_count})
        ca_score += 2
    elif word_count > 50:
        emit_check(WARN, "result.checks.content_access.words_low", f"Homepage has only {word_count} words in initial HTML — may rely too heavily on JavaScript rendering", {"count": word_count})
        emit_fix("result.fixes.content_access.enable_ssr", "Ensure key content is rendered server-side (SSR/SSG) so AI crawlers can read it.\nIf using React/Vue/Angular, switch to Next.js/Nuxt.js/Angular Universal for server-side rendering.")
        ca_score += 1
    else:
        emit_check(FAIL, "result.checks.content_access.words_js_only", f"Homepage has only {word_count} words — likely JS-rendered, invisible to most AI crawlers", {"count": word_count})
        emit_fix("result.fixes.content_access.client_rendered_workarounds", "Your page content is likely rendered client-side via JavaScript. AI crawlers cannot execute JS.\nSolutions:\n  1. Use server-side rendering (SSR) — Next.js, Nuxt.js, etc.\n  2. Use static site generation (SSG) — pre-render pages at build time.\n  3. Add a pre-rendering service (e.g., Prerender.io) to serve static HTML to bots.")

    html_size = len(resp.text)
    text_size = len(text.encode("utf-8"))
    if html_size > 0:
        ratio = (text_size / html_size) * 100
        if ratio >= 15:
            emit_check(PASS, "result.checks.content_access.ratio_good", f"Content-to-HTML ratio: {ratio:.1f}% (good)", {"ratio": f"{ratio:.1f}"})
            ca_score += 2
        elif ratio >= 5:
            emit_check(WARN, "result.checks.content_access.ratio_low", f"Content-to-HTML ratio: {ratio:.1f}% — low ratio means lots of boilerplate vs. real content", {"ratio": f"{ratio:.1f}"})
            ca_score += 1
            emit_fix("result.fixes.content_access.reduce_html_bloat", "Reduce HTML bloat: minimize inline CSS/JS, remove unused markup, and move scripts to external files.\nEnsure the page body contains substantive, unique content — not just navigation and footers.")
        else:
            emit_check(FAIL, "result.checks.content_access.ratio_very_low", f"Content-to-HTML ratio: {ratio:.1f}% — very low, mostly boilerplate/code", {"ratio": f"{ratio:.1f}"})
            emit_fix("result.fixes.content_access.improve_text_ratio", "Extremely low content ratio. Likely causes:\n  1. Heavy inline CSS/JS frameworks — externalize them.\n  2. Client-side rendering — switch to SSR/SSG.\n  3. Content hidden in JavaScript state — ensure HTML contains readable text.")

    headings = soup.find_all(re.compile(r"^h[1-6]$"))
    if headings:
        h_tags = [h.name for h in headings]
        h_summary = {tag: h_tags.count(tag) for tag in sorted(set(h_tags))}
        summary_str = ", ".join(f"{k}: {v}" for k, v in h_summary.items())
        emit_check(PASS, "result.checks.content_access.headings_found", f"Heading structure found ({summary_str})", {"summary": summary_str})
        ca_score += 2
        if headings[0].name != "h1":
            emit_check(WARN, "result.checks.content_access.first_heading_not_h1", f"First heading is <{headings[0].name}>, not <h1> — clear hierarchy helps AI engines", {"tag": headings[0].name})
            emit_fix("result.fixes.content_access.add_h1", "Ensure the first heading on the page is an <h1> tag containing the primary topic.\nUse a logical hierarchy: h1 > h2 > h3 (don't skip levels).")
    else:
        emit_check(WARN, "result.checks.content_access.headings_missing", "No heading tags found — structured headings help AI engines parse content")
        emit_fix("result.fixes.content_access.add_headings", "Add heading tags to structure your content:\n  <h1>Main Page Topic</h1>\n  <h2>Subtopic</h2>\n  <h3>Detail</h3>\nHeadings help AI engines understand content hierarchy and extract key topics.")

    track_score("Content Accessibility", ca_score, 6)


# ---------------------------------------------------------------------------
# 9. AI Crawl Readiness
# ---------------------------------------------------------------------------
def check_ai_crawl_readiness(base_url):
    print("\n--- AI Crawl Readiness ---")
    resp, soup = get_soup(base_url)
    if not soup:
        emit_check(FAIL, "result.checks.crawl_ready.fetch_failed", "Could not fetch homepage")
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
            emit_check(FAIL, "result.checks.crawl_ready.spa_empty", "Likely a client-side rendered SPA with minimal server-side content")
            print(f"         AI crawlers cannot execute JavaScript — consider SSR/SSG")
            emit_fix("result.fixes.crawl_ready.enable_ssr", "Enable server-side rendering in your framework:\n  Next.js: use getServerSideProps() or generateStaticParams()\n  Nuxt.js: set ssr: true in nuxt.config\n  React: consider migrating to Next.js or Remix")
        elif is_likely_spa:
            emit_check(PASS, "result.checks.crawl_ready.spa_with_ssr", "SPA framework detected but server-side content is present (SSR/SSG)")
            acr_score += 2
        else:
            emit_check(PASS, "result.checks.crawl_ready.ssr_content", "Content is rendered server-side")
            acr_score += 2

    robots_meta = soup.find("meta", attrs={"name": "robots"})
    if robots_meta:
        robots_content = robots_meta.get("content", "").lower()
        if "noindex" in robots_content:
            emit_check(FAIL, "result.checks.crawl_ready.meta_noindex", "Meta robots contains 'noindex' — page will be excluded from AI training data")
            emit_fix("result.fixes.crawl_ready.remove_noindex", "Remove 'noindex' from the meta robots tag if you want AI engines to index this page:\n  <meta name=\"robots\" content=\"index, follow\" />")
        if "nofollow" in robots_content:
            emit_check(WARN, "result.checks.crawl_ready.meta_nofollow", "Meta robots contains 'nofollow' — AI crawlers won't follow links on this page")
            emit_fix("result.fixes.crawl_ready.remove_nofollow", "Remove 'nofollow' if you want AI crawlers to discover linked pages:\n  <meta name=\"robots\" content=\"index, follow\" />")
        if "noai" in robots_content or "noimageai" in robots_content:
            emit_check(WARN, "result.checks.crawl_ready.meta_noai", f"Meta robots contains AI-specific opt-out directive: {robots_content}", {"content": robots_content})
            emit_fix("result.fixes.crawl_ready.remove_noai", "The 'noai' / 'noimageai' directive opts your content out of AI training.\nRemove it if you want AI engines to include your content in their responses.")
        if "noindex" not in robots_content and "noai" not in robots_content:
            emit_check(PASS, "result.checks.crawl_ready.meta_allows_index", f"Meta robots allows indexing: {robots_content}", {"content": robots_content})
            acr_score += 1
    else:
        emit_check(PASS, "result.checks.crawl_ready.meta_no_restriction", "No restrictive meta robots tag found")
        acr_score += 1

    x_robots = resp.headers.get("X-Robots-Tag", "")
    if x_robots:
        if "noindex" in x_robots.lower() or "noai" in x_robots.lower():
            emit_check(FAIL, "result.checks.crawl_ready.xrobots_restrict", f"X-Robots-Tag header restricts AI: {x_robots}", {"header": x_robots})
            emit_fix("result.fixes.crawl_ready.remove_xrobots", "Remove the restrictive X-Robots-Tag header from your server config.\nNginx: remove 'add_header X-Robots-Tag \"noindex\";'\nApache: remove 'Header set X-Robots-Tag \"noindex\"'")
        else:
            emit_check(INFO, "result.checks.crawl_ready.xrobots_present", f"X-Robots-Tag header present: {x_robots}", {"header": x_robots})
    else:
        emit_check(PASS, "result.checks.crawl_ready.xrobots_clean", "No restrictive X-Robots-Tag header")
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
        emit_check(WARN, "result.checks.crawl_ready.paywall_detected", f"Possible gated content detected (classes/ids: {', '.join(paywall_classes)})", {"classes": ", ".join(paywall_classes)})
        print(f"         Gated content is invisible to AI crawlers")
        emit_fix("result.fixes.crawl_ready.paywall_workarounds", "AI crawlers cannot see content behind paywalls/login walls.\nConsider:\n  1. Providing a generous free preview or summary above the gate.\n  2. Using 'metered' access so bots see full content on first visit.\n  3. Adding structured data (JSON-LD) with key facts outside the gate.")
    else:
        emit_check(PASS, "result.checks.crawl_ready.no_paywall", "No paywall/login-wall indicators detected")
        acr_score += 1

    semantic_tags = ["article", "main", "section", "nav", "aside", "header", "footer"]
    found_semantic = [tag for tag in semantic_tags if soup.find(tag)]
    if len(found_semantic) >= 3:
        emit_check(PASS, "result.checks.crawl_ready.semantic_good", f"Good semantic HTML structure ({', '.join(found_semantic)})", {"tags": ", ".join(found_semantic)})
        acr_score += 1
    elif found_semantic:
        emit_check(WARN, "result.checks.crawl_ready.semantic_limited", f"Limited semantic HTML ({', '.join(found_semantic)}) — more semantic tags help AI parse content", {"tags": ", ".join(found_semantic)})
        emit_fix("result.fixes.crawl_ready.add_semantic_html5", "Replace generic <div> containers with semantic HTML5 tags:\n  <header> for site header/nav\n  <main> for primary content\n  <article> for self-contained content\n  <section> for thematic groupings\n  <aside> for sidebar/related content\n  <footer> for footer")
    else:
        emit_check(FAIL, "result.checks.crawl_ready.semantic_missing", "No semantic HTML tags found — AI crawlers rely on semantic structure")
        emit_fix("result.fixes.crawl_ready.replace_divs", "Your page uses only <div> tags. Replace them with semantic HTML5 elements:\n  <header>, <nav>, <main>, <article>, <section>, <aside>, <footer>\nThis helps AI engines understand the role of each content block.")

    images = soup.find_all("img")
    if images:
        with_alt = sum(1 for img in images if img.get("alt", "").strip())
        total = len(images)
        pct = (with_alt / total * 100) if total > 0 else 0
        if pct >= 80:
            emit_check(PASS, "result.checks.crawl_ready.alt_good", f"{with_alt}/{total} images have alt text ({pct:.0f}%)", {"with_alt": with_alt, "total": total, "pct": f"{pct:.0f}"})
            acr_score += 1
        elif pct >= 50:
            emit_check(WARN, "result.checks.crawl_ready.alt_medium", f"{with_alt}/{total} images have alt text ({pct:.0f}%) — aim for >80%", {"with_alt": with_alt, "total": total, "pct": f"{pct:.0f}"})
            emit_fix("result.fixes.crawl_ready.add_alt_text", "Add descriptive alt text to all <img> tags:\n  <img src=\"photo.jpg\" alt=\"Description of what the image shows\" />\nGood alt text is specific: 'Team meeting in conference room' not 'image1'.")
        else:
            emit_check(FAIL, "result.checks.crawl_ready.alt_poor", f"Only {with_alt}/{total} images have alt text ({pct:.0f}%) — AI crawlers need alt text", {"with_alt": with_alt, "total": total, "pct": f"{pct:.0f}"})
            emit_fix("result.fixes.crawl_ready.add_alt_text_majority", "Most images are missing alt text. Add descriptive alt attributes to every <img>:\n  <img src=\"photo.jpg\" alt=\"Descriptive text about the image content\" />\nFor decorative images, use alt=\"\" (empty but present).")
    else:
        emit_check(INFO, "result.checks.crawl_ready.no_images", "No images found on homepage")

    links = soup.find_all("a", href=True)
    parsed_base = urlparse(base_url)
    internal_links = [
        l for l in links
        if urlparse(urljoin(base_url, l["href"])).netloc == parsed_base.netloc
    ]
    if len(internal_links) >= 10:
        emit_check(PASS, "result.checks.crawl_ready.internal_links_good", f"{len(internal_links)} internal links — good for AI crawl discovery", {"count": len(internal_links)})
    elif len(internal_links) >= 3:
        emit_check(WARN, "result.checks.crawl_ready.internal_links_few", f"Only {len(internal_links)} internal links — more internal links help AI engines discover content", {"count": len(internal_links)})
        emit_fix("result.fixes.crawl_ready.add_internal_links", "Add more internal links to help AI crawlers discover your content.\nInclude links to key pages in your navigation, footer, and within content body.\nUse descriptive anchor text: 'Read our pricing guide' not 'click here'.")
    else:
        emit_check(FAIL, "result.checks.crawl_ready.internal_links_none", f"Very few internal links ({len(internal_links)}) — AI crawlers rely on links to find content", {"count": len(internal_links)})
        emit_fix("result.fixes.crawl_ready.add_internal_links_homepage", "Your homepage has very few internal links. AI crawlers use links to discover pages.\nAdd:\n  1. A navigation menu linking to key sections\n  2. Featured content links in the body\n  3. A footer with links to important pages\n  4. Contextual links within content")

    start = time.time()
    fetch(urljoin(base_url, "/?_geo_timing_check"), timeout=10)
    elapsed = time.time() - start
    if elapsed < 1:
        emit_check(PASS, "result.checks.crawl_ready.response_fast", f"Response time: {elapsed:.2f}s", {"seconds": f"{elapsed:.2f}"})
        acr_score += 1
    elif elapsed < 3:
        emit_check(WARN, "result.checks.crawl_ready.response_slow", f"Response time: {elapsed:.2f}s — slow responses may cause AI crawlers to skip pages", {"seconds": f"{elapsed:.2f}"})
        emit_fix("result.fixes.crawl_ready.improve_response_time", "Improve response time:\n  1. Enable server-side caching (Redis, Varnish, CDN)\n  2. Optimize database queries\n  3. Use a CDN (Cloudflare, Fastly, CloudFront)\n  4. Enable gzip/brotli compression")
    else:
        emit_check(FAIL, "result.checks.crawl_ready.response_timeout", f"Response time: {elapsed:.2f}s — too slow for reliable AI crawling", {"seconds": f"{elapsed:.2f}"})
        emit_fix("result.fixes.crawl_ready.critical_response_time", "Response time is critically slow. AI crawlers may time out.\nImmediate actions:\n  1. Add a CDN in front of your origin server\n  2. Enable page caching at the server level\n  3. Profile your server-side code for bottlenecks\n  4. Consider static site generation for content pages")

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
        emit_check(FAIL, "result.checks.content_quality.fetch_failed", "Could not fetch homepage")
        track_score("Content Quality", 0, 7)
        return

    cq_score = 0
    text = get_text_content(soup)

    grade = flesch_kincaid_grade(text)
    if grade is not None:
        grade_str = f"{grade:.1f}"
        if 6 <= grade <= 12:
            emit_check(PASS, "result.checks.content_quality.readability_good", f"Readability: Flesch-Kincaid grade {grade_str} (accessible)", {"grade": grade_str})
            cq_score += 2
        elif grade < 6:
            emit_check(INFO, "result.checks.content_quality.readability_simple", f"Readability: Flesch-Kincaid grade {grade_str} (very simple)", {"grade": grade_str})
            cq_score += 1.5
        else:
            emit_check(WARN, "result.checks.content_quality.readability_complex", f"Readability: Flesch-Kincaid grade {grade_str} (complex) — simpler text ranks better in AI answers", {"grade": grade_str})
            emit_fix("result.fixes.content_quality.simplify", "Simplify your content for better AI readability:\n  1. Use shorter sentences (under 20 words)\n  2. Replace jargon with plain language\n  3. Break complex ideas into bullet points\n  4. Use active voice instead of passive\n  5. Target a grade 8-10 reading level")

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
        emit_check(PASS, "result.checks.content_quality.faq_detected", "FAQ content detected — strong signal for AI-generated answers")
        cq_score += 2
    elif faq_indicators == 1:
        emit_check(INFO, "result.checks.content_quality.faq_partial", "Possible FAQ-like content — consider adding FAQPage structured data")
        cq_score += 1
        emit_fix("result.fixes.content_quality.add_faq_schema", "Add FAQPage schema to boost AI answer ranking:\n  <script type=\"application/ld+json\">\n  {\n    \"@context\": \"https://schema.org\",\n    \"@type\": \"FAQPage\",\n    \"mainEntity\": [{\n      \"@type\": \"Question\",\n      \"name\": \"What is your product?\",\n      \"acceptedAnswer\": {\n        \"@type\": \"Answer\",\n        \"text\": \"Our product is...\"\n      }\n    }]\n  }\n  </script>")
    else:
        emit_check(INFO, "result.checks.content_quality.faq_missing", "No FAQ content detected — FAQ pages rank well in AI-generated answers")
        emit_fix("result.fixes.content_quality.add_faq_section", "Consider adding an FAQ section to your page. Format questions as headings:\n  <h2>Frequently Asked Questions</h2>\n  <h3>What does your product do?</h3>\n  <p>Clear, concise answer...</p>\nThen add FAQPage structured data (JSON-LD) for each Q&A pair.")

    stat_patterns = re.findall(r'\d+(?:\.\d+)?%|\$\d+|\d+(?:,\d{3})+', text)
    if len(stat_patterns) >= 3:
        emit_check(PASS, "result.checks.content_quality.stats_good", f"{len(stat_patterns)} quotable statistics found — good for AI citations", {"count": len(stat_patterns)})
        cq_score += 1
    elif stat_patterns:
        emit_check(INFO, "result.checks.content_quality.stats_few", f"{len(stat_patterns)} statistic(s) found — more specific data improves AI citation likelihood", {"count": len(stat_patterns)})
    else:
        emit_check(WARN, "result.checks.content_quality.stats_missing", "No quotable statistics found — specific numbers/data help AI engines cite your content")
        emit_fix("result.fixes.content_quality.add_statistics", "Add concrete, quotable statistics to your content:\n  '95% of customers report improved performance'\n  'Over 10,000 companies use our platform'\n  'Reduces processing time by 3.5x'\nAI engines prefer citing specific data points over vague claims.")

    source_patterns = re.findall(
        r'(?:according to|source:|study by|research from|data from|report by|published in)\s',
        text, re.IGNORECASE
    )
    if source_patterns:
        emit_check(PASS, "result.checks.content_quality.sources_cited", f"{len(source_patterns)} source attribution(s) found — increases trust for AI engines", {"count": len(source_patterns)})
        cq_score += 1
    else:
        emit_check(INFO, "result.checks.content_quality.sources_missing", "No explicit source attributions — citing sources increases AI trust in your content")
        emit_fix("result.fixes.content_quality.add_attributions", "Add source attributions to increase credibility:\n  'According to [Source Name], ...'\n  'Data from our 2025 industry report shows...'\n  'A study by [Institution] found...'\nAI engines weight attributed claims higher than unattributed ones.")

    lists = soup.find_all(["ul", "ol"])
    list_items = soup.find_all("li")
    if len(list_items) >= 5:
        emit_check(PASS, "result.checks.content_quality.lists_good", f"Structured lists found ({len(lists)} lists, {len(list_items)} items)", {"lists": len(lists), "items": len(list_items)})
        cq_score += 1
    elif list_items:
        emit_check(INFO, "result.checks.content_quality.lists_few", f"Some list content ({len(list_items)} items) — structured lists help AI extract key points", {"items": len(list_items)})
    else:
        emit_check(WARN, "result.checks.content_quality.lists_missing", "No list elements — structured lists help AI engines extract key points")
        emit_fix("result.fixes.content_quality.add_lists", "Add structured lists to make content easily extractable by AI:\n  <ul>\n    <li>Key feature or benefit</li>\n    <li>Another important point</li>\n  </ul>\nUse <ol> for steps/processes and <ul> for features/benefits.")

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
            emit_check(PASS, "result.checks.content_quality.first_para_good", f"First paragraph ({wc} words) contains extractable facts: {', '.join(facts)}", {"words": wc, "facts": ", ".join(facts)})
            cq_score += 0.5
        elif facts:
            emit_check(INFO, "result.checks.content_quality.first_para_length", f"First paragraph has facts ({', '.join(facts)}) but is {wc} words — aim for 25-120", {"words": wc, "facts": ", ".join(facts)})
            emit_fix("result.fixes.content_quality.tighten_first_para", "Tighten your opening paragraph to 25-120 words so AI engines can lift it as a snippet.")
        else:
            emit_check(WARN, "result.checks.content_quality.first_para_no_facts", f"First paragraph ({wc} words) lacks extractable facts — add a definition or key statistic up front", {"words": wc})
            emit_fix("result.fixes.content_quality.frontload_facts", "Front-load facts into your first paragraph so AI engines can extract it directly:\n"
                "  'GEO is the practice of optimizing content for AI-powered search engines.\n"
                "   Over 70% of search users now consult an AI assistant before clicking a link.'\n"
                "Aim for one definition-style sentence and one concrete stat in the first 25-120 words.")
    else:
        emit_check(INFO, "result.checks.content_quality.first_para_missing", "Could not identify a substantive first paragraph — AI engines rely on early content for extraction")
        emit_fix("result.fixes.content_quality.add_opening_para", "Place a substantive opening paragraph high in the page body (inside <main> or <article>)\nthat answers 'what is this about?' with a definition and/or a concrete number.")

    track_score("Content Quality", min(cq_score, 7), 7)


# ---------------------------------------------------------------------------
# 11. Technical Crawlability
# ---------------------------------------------------------------------------
def check_technical_crawlability(base_url):
    print("\n--- Technical Crawlability ---")
    resp, soup = get_soup(base_url)
    if not soup:
        emit_check(FAIL, "result.checks.tech_crawl.fetch_failed", "Could not fetch homepage")
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
                        emit_check(WARN, "result.checks.tech_crawl.canonical_chain", f"Canonical chain detected: {base_url} -> {canonical_url} -> {canon2_url}", {"from": base_url, "via": canonical_url, "to": canon2_url})
                        emit_fix("result.fixes.tech_crawl.fix_canonical_chain", "Fix the canonical chain — each page's canonical should point directly to the final URL, not through intermediaries.\nSet the canonical on each page to its own URL or the ultimate target.")
                    else:
                        emit_check(PASS, "result.checks.tech_crawl.canonical_resolves", "Canonical URL resolves correctly")
                        tc_score += 1.5
                else:
                    emit_check(PASS, "result.checks.tech_crawl.canonical_resolves", "Canonical URL resolves correctly")
                    tc_score += 1.5
            else:
                emit_check(FAIL, "result.checks.tech_crawl.canonical_broken", f"Canonical URL {canonical_url} returns error", {"url": canonical_url})
                emit_fix("result.fixes.tech_crawl.broken_canonical", f"The canonical URL {canonical_url} is broken. Either fix the target page or update the canonical to a working URL.", {"canonical_url": canonical_url})
        else:
            emit_check(PASS, "result.checks.tech_crawl.canonical_self", "Canonical URL is self-referencing (correct)")
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
                emit_check(WARN, "result.checks.tech_crawl.redirect_chain", f"Redirect chain with {num_redirects} hops: {chain} -> {redir_resp.url}", {"hops": num_redirects, "chain": chain, "final": redir_resp.url})
                print(f"         Long redirect chains can cause AI crawlers to give up")
                emit_fix("result.fixes.tech_crawl.reduce_redirects", "Reduce the redirect chain to a single hop (A -> B, not A -> B -> C -> D).\nUpdate your server config to redirect directly to the final destination URL.")
            elif num_redirects > 0:
                emit_check(PASS, "result.checks.tech_crawl.redirect_ok", f"{num_redirects} redirect(s) — within acceptable range", {"count": num_redirects})
                tc_score += 1
        else:
            emit_check(PASS, "result.checks.tech_crawl.no_redirect", "No redirects — direct access")
            tc_score += 1
    except requests.RequestException:
        emit_check(WARN, "result.checks.tech_crawl.redirect_test_failed", "Could not test redirect chain")

    try:
        import subprocess
        result = subprocess.run(
            ["curl", "-sI", "--http2", "-o", "/dev/null", "-w", "%{http_version}", base_url],
            capture_output=True, text=True, timeout=10
        )
        http_version = result.stdout.strip()
        if http_version in ("2", "3"):
            emit_check(PASS, "result.checks.tech_crawl.http2_supported", f"HTTP/{http_version} supported — faster crawling", {"version": http_version})
            tc_score += 1
        elif http_version:
            emit_check(INFO, "result.checks.tech_crawl.http1_only", f"HTTP/{http_version} — consider upgrading to HTTP/2 or HTTP/3 for faster crawling", {"version": http_version})
            emit_fix("result.fixes.tech_crawl.enable_http2", "Enable HTTP/2 on your server for faster crawling:\n  Nginx: listen 443 ssl http2;\n  Apache: Protocols h2 http/1.1\n  Or use a CDN like Cloudflare which enables HTTP/2 automatically.")
    except Exception:
        emit_check(INFO, "result.checks.tech_crawl.http_unknown", "Could not determine HTTP version")

    feed_url = None
    feeds = soup.find_all("link", type=re.compile(r"(rss|atom)\+xml", re.IGNORECASE))
    if feeds:
        feed_urls_list = [f.get("href", "N/A") for f in feeds]
        feeds_text = ", ".join(feed_urls_list[:3])
        emit_check(PASS, "result.checks.tech_crawl.feed_declared", f"RSS/Atom feed(s) found: {feeds_text}", {"feeds": feeds_text})
        tc_score += 1.5
        first_href = feeds[0].get("href")
        if first_href:
            feed_url = urljoin(base_url, first_href)
    else:
        # issue #13: 6 个 feed 路径并发 fetch(原来串行 6 × 5s timeout
        # 最坏 30s)。对不存在 feed 的站点 baidu 这种 2-5s/404,并发后
        # bound by 最慢一个,典型 2-3s。保留 break-on-first-match 语义:
        # 按原列表顺序 pick 第一个命中的。
        feed_paths = ["/feed", "/feed.xml", "/rss.xml", "/atom.xml", "/rss", "/blog/feed"]
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=len(feed_paths)) as _pool:
            _feed_responses = {
                p: _pool.submit(fetch, urljoin(base_url, p), 5) for p in feed_paths
            }
            _feed_responses = {p: f.result() for p, f in _feed_responses.items()}
        for feed_path in feed_paths:
            feed_resp = _feed_responses[feed_path]
            if feed_resp and feed_resp.status_code == 200 and ("<rss" in feed_resp.text or "<feed" in feed_resp.text):
                emit_check(PASS, "result.checks.tech_crawl.feed_found_at_path", f"Feed found at {feed_path}", {"path": feed_path})
                feed_url = urljoin(base_url, feed_path)
                tc_score += 1.5
                break
        if not feed_url:
            emit_check(INFO, "result.checks.tech_crawl.feed_missing", "No RSS/Atom feed found — feeds help AI engines monitor content freshness")
            emit_fix("result.fixes.tech_crawl.add_rss_feed", "Add an RSS or Atom feed for your content and link to it in <head>:\n  <link rel=\"alternate\" type=\"application/rss+xml\" title=\"RSS\" href=\"/feed.xml\" />\nMost CMS platforms generate feeds automatically. For static sites, tools like eleventy-rss can help.")

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
                        emit_check(PASS, "result.checks.tech_crawl.feed_full_content", f"Feed provides full content (avg {int(avg)} words/item) — AI-friendly", {"avg_words": int(avg)})
                        tc_score += 0.5
                    elif avg >= 80:
                        emit_check(INFO, "result.checks.tech_crawl.feed_excerpts", f"Feed provides excerpts (avg {int(avg)} words/item) — consider full content", {"avg_words": int(avg)})
                        emit_fix("result.fixes.tech_crawl.feed_full_content", "Publish full content in your feed rather than excerpts. AI agents that consume feeds\n"
                            "programmatically prefer complete text they can extract without following every link:\n"
                            "  WordPress: Settings \u2192 Reading \u2192 'Full text' in feed\n"
                            "  Custom: include <content:encoded> with the full post body")
                    else:
                        emit_check(WARN, "result.checks.tech_crawl.feed_headlines_only", f"Feed items are very short (avg {int(avg)} words) — mostly headlines", {"avg_words": int(avg)})
                        emit_fix("result.fixes.tech_crawl.feed_expand_content", "Your feed publishes only headlines/snippets. Switch to full content so AI agents\n"
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
    # issue #13: 10 个 API 路径并发 fetch(原来串行 10 × 5s timeout
    # 最坏 50s)。对 baidu 这种 10 × 404 ≈ 20s 串行,并发后 ~3s。
    # 保留 break-after-3-matches 语义:按原列表顺序取前 3 个命中。
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=len(api_probes)) as _pool:
        _api_responses = {
            p: _pool.submit(fetch, urljoin(base_url, p), 5) for p, _ in api_probes
        }
        _api_responses = {p: f.result() for p, f in _api_responses.items()}
    machine_readable_found = []
    for path, label in api_probes:
        r = _api_responses[path]
        if r and r.status_code == 200 and len(r.text.strip()) > 100:
            machine_readable_found.append((path, label))
            if len(machine_readable_found) >= 3:
                break
    if machine_readable_found:
        paths_text = ", ".join(p for p, _ in machine_readable_found[:3])
        emit_check(PASS, "result.checks.tech_crawl.machine_readable", f"Machine-readable / integration endpoints: {paths_text}", {"paths": paths_text})
        tc_score += 0.5
    else:
        emit_check(INFO, "result.checks.tech_crawl.no_machine_readable", "No API / integration / webhook documentation detected")
        emit_fix("result.fixes.tech_crawl.add_api_docs", "Publish machine-readable data feeds and integration docs so AI agents can consume\n"
            "your data programmatically:\n"
            "  \u2022 /openapi.json (or /swagger.json) for a public API\n"
            "  \u2022 /webhooks for event subscription documentation\n"
            "  \u2022 /integrations or /developers as a landing page linking SDKs, API keys, examples")

    track_score("Technical Crawlability", min(tc_score, 5), 5)


# ---------------------------------------------------------------------------
# 12. Authority & Trust Signals
# ---------------------------------------------------------------------------
def check_authority_trust(base_url):
    print("\n--- Authority & Trust Signals ---")
    resp, soup = get_soup(base_url)
    if not resp:
        emit_check(FAIL, "result.checks.authority.fetch_failed", "Could not fetch homepage")
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
        emit_check(PASS, "result.checks.authority.security_headers_strong", f"Strong security headers ({found_sec_headers}/4): {', '.join(present)}", {"count": found_sec_headers, "headers": ", ".join(present)})
        at_score += 2
    elif found_sec_headers >= 1:
        present = [h for h in security_headers if resp.headers.get(h)]
        missing = [h for h in security_headers if not resp.headers.get(h)]
        emit_check(WARN, "result.checks.authority.security_headers_partial", f"Some security headers present ({found_sec_headers}/4): {', '.join(present)}", {"count": found_sec_headers, "headers": ", ".join(present)})
        at_score += 1
        print(f"         Missing: {', '.join(missing)}")
        emit_fix("result.fixes.authority.add_security_headers", "Add missing security headers to your server config:\n  Strict-Transport-Security: max-age=31536000; includeSubDomains\n  Content-Security-Policy: default-src 'self'\n  X-Content-Type-Options: nosniff\n  X-Frame-Options: DENY")
    else:
        emit_check(FAIL, "result.checks.authority.security_headers_missing", "No security headers found — reduces trust signal for AI engines")
        emit_fix("result.fixes.authority.add_security_headers_nginx", "Add security headers to your server response. In nginx:\n  add_header Strict-Transport-Security \"max-age=31536000; includeSubDomains\" always;\n  add_header Content-Security-Policy \"default-src 'self'\" always;\n  add_header X-Content-Type-Options \"nosniff\" always;\n  add_header X-Frame-Options \"DENY\" always;")

    humans_url = urljoin(base_url, "/humans.txt")
    humans_resp = fetch(humans_url)
    if humans_resp and humans_resp.status_code == 200 and len(humans_resp.text.strip()) > 0:
        emit_check(PASS, "result.checks.authority.humans_txt_found", "humans.txt found — authorship transparency")
        at_score += 1
    else:
        emit_check(INFO, "result.checks.authority.humans_txt_missing", "No humans.txt — optional authorship transparency file")
        emit_fix("result.fixes.authority.add_humans_txt", "Create a humans.txt at your site root to signal authorship:\n  /* TEAM */\n  Name: Your Name\n  Role: Lead Developer\n  Contact: email@example.com\n  \n  /* SITE */\n  Last update: 2025/01/15\n  Standards: HTML5, CSS3\nSee humanstxt.org for the full spec.")

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
            emit_check(PASS, "result.checks.authority.author_jsonld", "Author markup found in structured data (JSON-LD)")
            at_score += 2
        elif author_meta or author_link:
            emit_check(PASS, "result.checks.authority.author_meta", "Author information found (meta/link tag)")
            at_score += 1.5
        elif author_tag:
            emit_check(INFO, "result.checks.authority.author_class_only", "Author class detected in HTML — consider adding schema.org Person markup")
            emit_fix("result.fixes.authority.upgrade_author_jsonld", "Upgrade your author attribution with JSON-LD:\n  \"author\": {\n    \"@type\": \"Person\",\n    \"name\": \"Author Name\",\n    \"url\": \"https://authorsite.com\"\n  }")
        else:
            emit_check(WARN, "result.checks.authority.author_missing", "No author attribution found — authorship signals boost AI trust (E-E-A-T)")
            emit_fix("result.fixes.authority.add_author", "Add author information to boost E-E-A-T signals:\n  1. Add <meta name=\"author\" content=\"Author Name\">\n  2. Or add author to your JSON-LD structured data:\n     \"author\": {\"@type\": \"Person\", \"name\": \"Author Name\"}\n  3. For blog posts, display author name, bio, and credentials visibly on the page.")

        # E-E-A-T depth: look for a bio/about/team page and assess credentials
        bio_url = None
        bio_text = ""
        for path in ["/about", "/about-us", "/team", "/authors", "/our-team", "/people"]:
            candidate = urljoin(base_url, path)
            r = fetch(candidate, timeout=8)
            if r and r.status_code == 200 and len(r.content) > 500:
                try:
                    s = BeautifulSoup(r.content, "html.parser")
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
            emit_check(PASS, "result.checks.authority.bio_page_found", f"Bio/about page found at {urlparse(bio_url).path}", {"path": urlparse(bio_url).path})
            at_score += 0.5
            bio_lower = bio_text.lower()
            found_creds = [k for k in credential_keywords if k in bio_lower]
            if found_creds:
                creds_text = ", ".join(sorted(set(found_creds))[:5])
                emit_check(PASS, "result.checks.authority.credentials_found", f"Credential signals in bio: {creds_text}", {"credentials": creds_text})
                at_score += 1
            else:
                emit_check(INFO, "result.checks.authority.credentials_weak", "Bio page has little credential language — add credentials/experience")
                emit_fix("result.fixes.authority.strengthen_bio", "Strengthen your bio/about page with explicit E-E-A-T signals:\n"
                    "  \u2022 Credentials (PhD, MD, certifications)\n"
                    "  \u2022 Years of experience and roles (\"10 years at X as...\")\n"
                    "  \u2022 Notable prior affiliations (\"formerly at Google\", \"ex-McKinsey\")\n"
                    "  \u2022 External bylines, publications, or press coverage")

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
                    bylines_text = ", ".join(sorted(external_bylines))
                    emit_check(PASS, "result.checks.authority.external_bylines", f"External byline/profile links: {bylines_text}", {"bylines": bylines_text})
                    at_score += 0.5
                else:
                    emit_check(INFO, "result.checks.authority.no_external_bylines", "No external bylines detected on bio page")
                    emit_fix("result.fixes.authority.add_external_bylines", "Link to external bylines (Medium, Substack, trade press, Google Scholar, ORCID)\n"
                        "from your bio/about page. Independent bylines carry more E-E-A-T weight than self-claims.")
            except Exception:
                pass
        else:
            emit_check(WARN, "result.checks.authority.no_bio_page", "No author bio / about / team page found")
            emit_fix("result.fixes.authority.create_about_page", "Create a substantive /about or /team page (200+ words) documenting who is behind\n"
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

    seen_c = set()
    candidates = [c for c in candidates if c and not (c.lower() in seen_c or seen_c.add(c.lower()))]
    brand = candidates[0]
    print(f"  Checking entity: \"{brand}\" (domain: {domain})")

    import urllib.parse
    score = 0
    wiki_page = None
    wikidata_id = None

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
        emit_check(PASS, "result.checks.brand_kg.wikipedia_found",
                   f"Wikipedia page found: \"{wiki_page}\"", {"title": wiki_page})
        score += 2
        try:
            enc = urllib.parse.quote(wiki_page)
            br = requests.get(
                f"https://en.wikipedia.org/w/api.php?action=query&list=backlinks&bltitle={enc}&bllimit=50&format=json",
                timeout=10, headers={"User-Agent": "GEO-Checker/1.0"},
            )
            if br.status_code == 200:
                backlink_count = len(br.json().get("query", {}).get("backlinks", []))
                if backlink_count >= 20:
                    emit_check(PASS, "result.checks.brand_kg.backlinks_strong",
                               f"Wikipedia backlinks: {backlink_count}+ pages link to this entity — strong authority",
                               {"count": backlink_count})
                    score += 1
                elif backlink_count >= 5:
                    emit_check(INFO, "result.checks.brand_kg.backlinks_moderate",
                               f"Wikipedia backlinks: {backlink_count} pages link to this entity",
                               {"count": backlink_count})
                    score += 0.5
                else:
                    emit_check(INFO, "result.checks.brand_kg.backlinks_weak",
                               f"Only {backlink_count} Wikipedia backlink(s) — entity is recognized but niche",
                               {"count": backlink_count})
        except requests.RequestException:
            pass
    else:
        emit_check(WARN, "result.checks.brand_kg.wikipedia_not_found",
                   f"No Wikipedia page found for \"{brand}\"", {"brand": brand})
        emit_fix("result.fixes.brand_kg.create_wikipedia",
                 "A Wikipedia page is one of the strongest entity signals for AI engines. If you're\n"
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
        emit_check(PASS, "result.checks.brand_kg.wikidata_found",
                   f"Wikidata entity found: {wikidata_id}", {"id": wikidata_id})
        score += 2
    else:
        emit_check(WARN, "result.checks.brand_kg.wikidata_not_found",
                   f"No Wikidata entity found for \"{brand}\"", {"brand": brand})
        emit_fix("result.fixes.brand_kg.create_wikidata",
                 "Wikidata is free to edit and AI engines (especially Google Knowledge Graph) ingest it\n"
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
        emit_check(FAIL, "result.checks.trust_safety.fetch_failed", "Could not fetch homepage")
        track_score("Trust & Safety", 0, 6)
        return

    ts_score = 0

    home_links = {a.get("href", "").lower(): (a.get_text(strip=True) or "").lower()
                  for a in soup.find_all("a", href=True)}

    def _anchor_match(keywords):
        for href, text in home_links.items():
            combined = f"{href} {text}"
            if any(k in combined for k in keywords):
                return href
        return None

    # Path sets for 4 trust pages.
    privacy_paths = ["/privacy", "/privacy-policy", "/privacy.html", "/legal/privacy",
                     "/policies/privacy", "/privacypolicy"]
    terms_paths = ["/terms", "/terms-of-service", "/tos", "/terms-of-use",
                   "/terms.html", "/legal/terms"]
    contact_paths = ["/contact", "/contact-us", "/contactus", "/get-in-touch",
                     "/support", "/help"]
    legal_paths = ["/dmca", "/copyright", "/legal", "/legal-notice", "/imprint"]

    # Fetch all 23 candidate URLs concurrently instead of 4 serial probes.
    # Serial was ~55 s on baidu (23 × ~2.4 s average); parallel is ~3 s.
    # _page_cache writes are GIL-safe; a duplicate fetch on miss is harmless.
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
        emit_check(PASS, "result.checks.trust_safety.privacy_found",
                   f"Privacy policy found: {privacy_found}", {"path": privacy_found})
        ts_score += 1.5
    else:
        emit_check(FAIL, "result.checks.trust_safety.privacy_missing",
                   "No privacy policy page detected")
        emit_fix("result.fixes.trust_safety.add_privacy",
                 "Publish a Privacy Policy at /privacy (or /privacy-policy). AI engines treat missing\n"
                 "privacy policies as a trust red flag — required by GDPR, CCPA, and most ad networks.")

    # 2. Terms of service
    terms_found = _first_match(terms_paths) or _anchor_match(["terms", "tos"])
    if terms_found:
        emit_check(PASS, "result.checks.trust_safety.terms_found",
                   f"Terms of service found: {terms_found}", {"path": terms_found})
        ts_score += 1
    else:
        emit_check(WARN, "result.checks.trust_safety.terms_missing",
                   "No terms of service page detected")
        emit_fix("result.fixes.trust_safety.add_terms",
                 "Publish Terms of Service at /terms. This is a basic trust signal AI engines\n"
                 "and search platforms expect from legitimate sites.")

    # 3. Contact page
    contact_found = _first_match(contact_paths) or _anchor_match(["contact", "get in touch"])
    if contact_found:
        emit_check(PASS, "result.checks.trust_safety.contact_found",
                   f"Contact page found: {contact_found}", {"path": contact_found})
        ts_score += 1
    else:
        emit_check(WARN, "result.checks.trust_safety.contact_missing",
                   "No contact page detected")
        emit_fix("result.fixes.trust_safety.add_contact",
                 "Add a /contact page with at least an email address and/or form. AI engines rank\n"
                 "sites with clear contact paths higher for trust-sensitive queries.")

    # 4. DMCA / copyright / legal
    legal_found = _first_match(legal_paths) or _anchor_match(["dmca", "copyright", "imprint", "legal notice"])
    if legal_found:
        emit_check(PASS, "result.checks.trust_safety.legal_found",
                   f"Legal/DMCA/imprint page found: {legal_found}", {"path": legal_found})
        ts_score += 0.5
    else:
        emit_check(INFO, "result.checks.trust_safety.legal_missing",
                   "No DMCA / legal / imprint page detected")
        emit_fix("result.fixes.trust_safety.add_legal",
                 "Add a /dmca or /legal page. In the EU an 'Impressum' (imprint) is legally required;\n"
                 "elsewhere a DMCA agent page protects you from copyright liability and boosts trust.")

    # 5. Business identity: address / phone / email / registration in footer or schema
    homepage_text = get_text_content(soup)
    footer = soup.find("footer")
    footer_text = footer.get_text(" ", strip=True) if footer else ""

    email_re = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
    phone_re = re.compile(r"(?:\+?\d{1,3}[\s\-.])?\(?\d{2,4}\)?[\s\-.]\d{3,4}[\s\-.]\d{3,4}")
    address_hint = re.compile(
        r"\b\d{1,5}\s+\w+(?:\s+\w+){0,5}\s+"
        r"(?:street|st\.?|road|rd\.?|avenue|ave\.?|boulevard|blvd\.?|lane|ln\.?|drive|dr\.?|suite|ste\.?|floor|fl\.?)\b",
        re.IGNORECASE,
    )
    registration_re = re.compile(
        r"\b(?:LLC|Inc\.?|Corp\.?|Ltd\.?|GmbH|AG|S\.?A\.?|S\.?L\.?|SARL|Pty|BV|Oy)\b"
        r"|\b(?:EIN|VAT|ABN|SIREN|SIRET|company\s+(?:no|number)|reg(?:istration)?\s+(?:no|number)|CIN)\b",
        re.IGNORECASE,
    )

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
        emit_check(PASS, "result.checks.trust_safety.identity_strong",
                   f"Strong business identity in footer/schema: {', '.join(identity_signals)}",
                   {"signals": ", ".join(identity_signals)})
        ts_score += 2
    elif len(identity_signals) >= 1:
        emit_check(WARN, "result.checks.trust_safety.identity_partial",
                   f"Partial business identity: {', '.join(identity_signals)}",
                   {"signals": ", ".join(identity_signals)})
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
        emit_fix("result.fixes.trust_safety.add_identity_signals",
                 "Add missing trust signals so AI engines can verify who is behind the site:\n  "
                 + "\n  ".join(f"- {m}" for m in missing))
    else:
        emit_check(FAIL, "result.checks.trust_safety.identity_missing",
                   "No business identity signals found (email, phone, address, or legal entity)")
        emit_fix("result.fixes.trust_safety.add_business_identity",
                 "AI engines cannot verify who runs this site. Add in the footer and/or Organization JSON-LD:\n"
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
        emit_check(FAIL, "result.checks.ai_opt.fetch_failed", "Could not fetch homepage")
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
        emit_check(PASS, "result.checks.ai_opt.freshness_found", "Content freshness signals found:")
        ao_score += 2
        for sig in freshness_signals[:5]:
            print(f"         {sig}")
    else:
        emit_check(WARN, "result.checks.ai_opt.freshness_missing", "No content freshness signals — add dateModified to JSON-LD or <time> elements")
        emit_fix("result.fixes.ai_opt.add_freshness", "Add freshness signals so AI engines know your content is current:\n  1. Add dateModified to your JSON-LD: \"dateModified\": \"2025-01-15\"\n  2. Use <time> tags: <time datetime=\"2025-01-15\">January 15, 2025</time>\n  3. Set Last-Modified HTTP header on your server")

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
        emit_check(INFO, "result.checks.ai_opt.sitemap_cadence", f"Sitemap contains {len(parsed_dates)} <lastmod> entries (median age: {median_days} days, {fresh_90}/{len(ages_days)} updated in last 90d)", {"total": len(parsed_dates), "median_days": median_days, "fresh_90": fresh_90, "count": len(ages_days)})
        if fresh_ratio >= 0.5 or median_days <= 90:
            emit_check(PASS, "result.checks.ai_opt.cadence_healthy", "Healthy sitewide update cadence")
            ao_score += 1
        elif fresh_ratio >= 0.2:
            emit_check(WARN, "result.checks.ai_opt.cadence_moderate", "Moderate cadence — less than half of pages updated in the last 90 days")
            emit_fix("result.fixes.ai_opt.increase_cadence", "Increase content refresh cadence. AI engines prefer sites that update regularly — stale pages\n"
                "drop out of training windows and retrieval indexes.")
        else:
            emit_check(WARN, "result.checks.ai_opt.cadence_low", f"Low cadence — most pages are stale (median {median_days} days old)", {"median_days": median_days})
            emit_fix("result.fixes.ai_opt.refresh_stale_content", "Most of your content hasn't been touched in months. Refresh high-value pages periodically\n"
                "(update stats, add recent examples, bump dateModified) so AI engines see ongoing maintenance.")
    else:
        emit_check(INFO, "result.checks.ai_opt.cadence_unknown", "Could not analyze sitewide update cadence (no parseable <lastmod> in sitemap)")

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
        names_str = ", ".join(site_names)
        emit_check(WARN, "result.checks.ai_opt.brand_inconsistent", f"Inconsistent site name across tags: {names_str}", {"names": names_str})
        emit_fix("result.fixes.ai_opt.unify_brand_name", f"Use the same brand name everywhere. Ensure og:site_name, the title tag suffix,\nand JSON-LD Organization name all use the exact same string.\nPick one: {' or '.join(repr(n) for n in site_names)}", {"names": " or ".join(repr(n) for n in site_names)})
    elif site_names:
        name = list(site_names)[0]
        text = get_text_content(soup)
        occurrences = text.lower().count(name.lower())
        if occurrences >= 2:
            emit_check(PASS, "result.checks.ai_opt.brand_consistent", f"Brand entity \"{name}\" used consistently ({occurrences} occurrences)", {"name": name, "count": occurrences})
            ao_score += 1.5
        else:
            emit_check(INFO, "result.checks.ai_opt.brand_sparse", f"Brand entity \"{name}\" found but used sparingly — consistent naming helps AI entity recognition", {"name": name})
            emit_fix("result.fixes.ai_opt.use_brand_consistently", f"Use your brand name \"{name}\" more consistently throughout the page content.\nMention it in headings, intro paragraphs, and structured data to strengthen entity recognition.", {"name": name})
    else:
        emit_check(INFO, "result.checks.ai_opt.brand_unknown", "Could not determine primary brand/entity name")
        emit_fix("result.fixes.ai_opt.add_brand_meta", "Make your brand name discoverable by adding:\n  <meta property=\"og:site_name\" content=\"Your Brand\" />\nAnd use a consistent 'Brand — Page Title' format in your <title> tags.")

    api_paths = [
        "/openapi.json", "/openapi.yaml", "/swagger.json",
        "/api-docs", "/api/v1", "/graphql",
    ]
    api_found = False
    for path in api_paths:
        api_url = urljoin(base_url, path)
        api_resp = fetch(api_url, timeout=5)
        if api_resp and api_resp.status_code == 200:
            emit_check(PASS, "result.checks.ai_opt.api_endpoint_found", f"Machine-readable endpoint found: {path}", {"path": path})
            api_found = True
            ao_score += 1.5
            break
    if not api_found:
        emit_check(INFO, "result.checks.ai_opt.api_endpoint_missing", "No public API endpoints found — optional, but helps AI systems access structured data")

    track_score("AI Optimization", min(ao_score, 5), 5)


# ---------------------------------------------------------------------------
# 14. Social Signals
# ---------------------------------------------------------------------------
def check_social_signals(base_url):
    """Check for social media presence signals that help AI entity recognition."""
    print("\n--- Social Signals ---")
    resp, soup = get_soup(base_url)
    if not soup:
        emit_check(FAIL, "result.checks.social.fetch_failed", "Could not fetch homepage")
        track_score("Social Signals", 0, 3)
        return

    ss_score = 0

    # Twitter/X card meta tags
    twitter_tags = soup.find_all("meta", attrs={"name": re.compile(r"^twitter:", re.IGNORECASE)})
    if not twitter_tags:
        twitter_tags = soup.find_all("meta", property=re.compile(r"^twitter:", re.IGNORECASE))
    if twitter_tags:
        tw_types = [t.get("name") or t.get("property") for t in twitter_tags]
        tw_text = ", ".join(tw_types)
        emit_check(PASS, "result.checks.social.twitter_found", f"Twitter/X card tags found: {tw_text}", {"tags": tw_text})
        ss_score += 1
    else:
        emit_check(WARN, "result.checks.social.twitter_missing", "No Twitter/X card meta tags found")
        emit_fix("result.fixes.social.add_twitter_card", "Add Twitter card tags to your <head>:\n  <meta name=\"twitter:card\" content=\"summary_large_image\" />\n  <meta name=\"twitter:site\" content=\"@yourhandle\" />\n  <meta name=\"twitter:title\" content=\"Page Title\" />\n  <meta name=\"twitter:description\" content=\"Page description\" />\n  <meta name=\"twitter:image\" content=\"https://yoursite.com/image.jpg\" />")

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
        emit_check(PASS, "result.checks.social.sameas_found", f"sameAs social links in JSON-LD ({len(same_as_links)}):", {"count": len(same_as_links)})
        ss_score += 2
        for link in same_as_links[:5]:
            print(f"         {link}")
    else:
        emit_check(WARN, "result.checks.social.sameas_missing", "No sameAs social profile links in structured data")
        emit_fix("result.fixes.social.add_sameas", "Add sameAs to your Organization JSON-LD to connect your social profiles:\n  \"sameAs\": [\n    \"https://twitter.com/yourbrand\",\n    \"https://linkedin.com/company/yourbrand\",\n    \"https://github.com/yourbrand\",\n    \"https://facebook.com/yourbrand\"\n  ]\nThis helps AI engines confirm your entity identity across platforms.")

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
            emit_check(INFO, "result.checks.social.html_links_found", f"{len(social_links)} social profile link(s) found in HTML — consider adding them as sameAs in JSON-LD too", {"count": len(social_links)})
        else:
            emit_check(INFO, "result.checks.social.no_social_links", "No social profile links detected on the page")

    track_score("Social Signals", min(ss_score, 3), 3)


# ---------------------------------------------------------------------------
# 15. AI Answer Format Optimization
# ---------------------------------------------------------------------------
def check_ai_answer_formats(base_url):
    """Check for content patterns that AI engines prefer to cite."""
    print("\n--- AI Answer Format Optimization ---")
    resp, soup = get_soup(base_url)
    if not soup:
        emit_check(FAIL, "result.checks.answer_format.fetch_failed", "Could not fetch homepage")
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
        emit_check(PASS, "result.checks.answer_format.definitions_found", f"{len(definition_patterns)} definition-style sentence(s) found — highly citable by AI", {"count": len(definition_patterns)})
    else:
        emit_check(WARN, "result.checks.answer_format.definitions_missing", "No definition-style sentences detected")
        emit_fix("result.fixes.answer_format.add_definitions", "Add clear definition sentences that AI engines can directly quote:\n  'Generative Engine Optimization (GEO) is the practice of optimizing web content...'\n  'A sitemap refers to a file that lists all pages on a website...'\nPattern: '[Term] is/are [clear definition].'")

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
        emit_check(PASS, "result.checks.answer_format.tables_with_headers", "Comparison table(s) with headers found — AI engines extract tabular data")
    else:
        if tables:
            emit_check(WARN, "result.checks.answer_format.tables_without_headers", "Tables found but missing <th> headers — add headers for AI extraction")
            emit_fix("result.fixes.answer_format.add_table_headers", "Add proper headers to your tables:\n  <table>\n    <thead><tr><th>Feature</th><th>Plan A</th><th>Plan B</th></tr></thead>\n    <tbody><tr><td>Price</td><td>$10</td><td>$20</td></tr></tbody>\n  </table>\nAI engines extract well-structured tables for comparison answers.")
        else:
            emit_check(INFO, "result.checks.answer_format.tables_missing", "No comparison tables — consider adding tables for feature comparisons, pricing, etc.")
            emit_fix("result.fixes.answer_format.add_comparison_tables", "Add comparison tables where applicable (pricing, features, vs. competitors):\n  <table>\n    <thead><tr><th>Feature</th><th>Basic</th><th>Pro</th></tr></thead>\n    <tbody>...</tbody>\n  </table>\nAI engines frequently cite tabular data in comparison answers.")

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
        emit_check(PASS, "result.checks.answer_format.steps_found", "Step-by-step instructional content detected — great for 'how to' AI answers")
    else:
        emit_check(INFO, "result.checks.answer_format.steps_missing", "No step-by-step instructions found")
        emit_fix("result.fixes.answer_format.add_steps", "Add numbered how-to instructions where relevant:\n  <h2>How to Set Up Your Account</h2>\n  <ol>\n    <li>Go to the signup page</li>\n    <li>Enter your email address</li>\n    <li>Verify your account</li>\n  </ol>\nAI engines surface step-by-step content for 'how to' queries.")

    # 4. Pros and cons / advantages and disadvantages
    pros_cons_patterns = re.findall(
        r'(?:pros?\s+(?:and|&)\s+cons?|advantages?\s+(?:and|&)\s+disadvantages?|benefits?\s+(?:and|&)\s+drawbacks?)',
        text, re.IGNORECASE
    )
    pros_cons_elements = soup.find_all(class_=re.compile(r"pros?|cons?|advantage|disadvantage", re.IGNORECASE))
    if pros_cons_patterns or pros_cons_elements:
        score += 1
        emit_check(PASS, "result.checks.answer_format.proscons_found", "Pros/cons or advantages/disadvantages content detected")
    else:
        emit_check(INFO, "result.checks.answer_format.proscons_missing", "No pros/cons pattern detected")
        emit_fix("result.fixes.answer_format.add_proscons", "Add pros and cons sections for products, services, or comparisons:\n  <h3>Pros</h3>\n  <ul><li>Fast performance</li><li>Easy to use</li></ul>\n  <h3>Cons</h3>\n  <ul><li>Limited free tier</li><li>No mobile app</li></ul>\nAI engines frequently cite balanced pros/cons in recommendation answers.")

    # 5. Key takeaways / TL;DR / summary sections
    summary_indicators = soup.find_all(
        re.compile(r"^h[1-6]$"),
        string=re.compile(r"key\s+takeaway|tl;?\s*dr|summary|in\s+(?:a\s+)?nutshell|bottom\s+line|conclusion", re.IGNORECASE)
    )
    summary_classes = soup.find_all(class_=re.compile(r"takeaway|tldr|summary|highlight", re.IGNORECASE))
    if summary_indicators or summary_classes:
        score += 1
        emit_check(PASS, "result.checks.answer_format.summary_found", "Summary/key takeaways section found — AI engines prefer concise summaries")
    else:
        emit_check(INFO, "result.checks.answer_format.summary_missing", "No key takeaways or TL;DR section found")
        emit_fix("result.fixes.answer_format.add_summary", "Add a 'Key Takeaways' or 'TL;DR' section near the top or bottom:\n  <h2>Key Takeaways</h2>\n  <ul>\n    <li>Main point 1</li>\n    <li>Main point 2</li>\n  </ul>\nAI engines often pull from summary sections for quick answers.")

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
        emit_check(PASS, "result.checks.answer_format.question_headings_strong", f"{len(q_headings)} question-pattern heading(s) — strong conversational readiness", {"count": len(q_headings)})
        for qh in q_headings[:3]:
            print(f"         \"{qh[:70]}\"")
    elif q_headings:
        emit_check(INFO, "result.checks.answer_format.question_headings_few", f"Only {len(q_headings)} question-pattern heading(s) — add more for chat-style queries", {"count": len(q_headings)})
        emit_fix("result.fixes.answer_format.add_question_headings", "Add more question-pattern headings that match how people prompt AI engines:\n"
            "  <h2>What is GEO?</h2>\n"
            "  <h2>How do I optimize for AI search?</h2>\n"
            "  <h2>Why does GEO matter?</h2>\n"
            "Follow each with a short, direct answer so AI engines can extract it.")
    else:
        emit_check(WARN, "result.checks.answer_format.question_headings_none", "No question-pattern headings detected — low conversational readiness")
        emit_fix("result.fixes.answer_format.add_question_headings_intro", "Add question-pattern headings so AI engines can match chat-style queries to your content:\n"
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
        emit_check(FAIL, "result.checks.schema_kg.fetch_failed", "Could not fetch homepage")
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
        emit_check(PASS, "result.checks.schema_kg.breadcrumb_schema", "BreadcrumbList schema found — helps AI engines understand site hierarchy")
        sk_score += 1.5
    else:
        # Check for HTML breadcrumb nav
        breadcrumb_nav = soup.find(attrs={"aria-label": re.compile(r"breadcrumb", re.IGNORECASE)})
        breadcrumb_class = soup.find(class_=re.compile(r"breadcrumb", re.IGNORECASE))
        if breadcrumb_nav or breadcrumb_class:
            emit_check(WARN, "result.checks.schema_kg.breadcrumb_html_only", "HTML breadcrumb navigation found but no BreadcrumbList schema")
            emit_fix("result.fixes.schema_kb.add_breadcrumb_schema", "Add BreadcrumbList structured data to match your HTML breadcrumbs:\n  <script type=\"application/ld+json\">\n  {\n    \"@context\": \"https://schema.org\",\n    \"@type\": \"BreadcrumbList\",\n    \"itemListElement\": [\n      {\"@type\": \"ListItem\", \"position\": 1, \"name\": \"Home\", \"item\": \"https://yoursite.com\"},\n      {\"@type\": \"ListItem\", \"position\": 2, \"name\": \"Products\", \"item\": \"https://yoursite.com/products\"}\n    ]\n  }\n  </script>")
        else:
            emit_check(INFO, "result.checks.schema_kg.breadcrumb_none", "No breadcrumb navigation or schema found")
            emit_fix("result.fixes.schema_kb.add_breadcrumbs", "Add breadcrumb navigation to help AI engines understand your site structure:\n  1. Add visible breadcrumbs: Home > Category > Page\n  2. Add BreadcrumbList JSON-LD schema to match")

    # Knowledge panel readiness — check Organization/LocalBusiness completeness
    if org_data:
        org_type = org_data.get("@type")
        emit_check(PASS, "result.checks.schema_kg.org_schema_found", f"Organization/Business schema found: @type = {org_type}", {"type": org_type})
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
                emit_check(PASS, "result.checks.schema_kg.org_field_present", f"{label}: present", {"label": label})
                sk_score += 0.375  # 4 fields * 0.375 = 1.5 pts max
            else:
                emit_check(WARN, "result.checks.schema_kg.org_field_missing", f"{label}: missing", {"label": label})
                emit_fix("result.fixes.schema_kb.add_org_field", f"Add \"{field}\" to your Organization JSON-LD to improve knowledge panel eligibility.", {"field": field})

        present_optional = [label for field, label in optional_fields.items() if org_data.get(field)]
        missing_optional = [label for field, label in optional_fields.items() if not org_data.get(field)]
        if present_optional:
            present_text = ", ".join(present_optional)
            emit_check(PASS, "result.checks.schema_kg.optional_present", f"Optional fields present: {present_text}", {"fields": present_text})
        if missing_optional:
            missing_text = ", ".join(missing_optional)
            emit_check(INFO, "result.checks.schema_kg.optional_missing", f"Optional fields missing: {missing_text}", {"fields": missing_text})
            emit_fix("result.fixes.schema_kb.add_org_fields", "Add more fields to strengthen knowledge panel eligibility:\n  \"address\": {\"@type\": \"PostalAddress\", \"streetAddress\": \"...\", \"addressLocality\": \"...\"},\n  \"telephone\": \"+1-xxx-xxx-xxxx\",\n  \"foundingDate\": \"2020\",\n  \"sameAs\": [\"https://twitter.com/...\", \"https://linkedin.com/...\"]")
    else:
        emit_check(WARN, "result.checks.schema_kg.org_schema_missing", "No Organization/LocalBusiness schema found — needed for knowledge panels")
        emit_fix("result.fixes.schema_kb.add_organization", "Add Organization structured data for knowledge panel eligibility:\n  <script type=\"application/ld+json\">\n  {\n    \"@context\": \"https://schema.org\",\n    \"@type\": \"Organization\",\n    \"name\": \"Your Company\",\n    \"url\": \"https://yoursite.com\",\n    \"logo\": \"https://yoursite.com/logo.png\",\n    \"description\": \"What your company does\",\n    \"sameAs\": [\"https://twitter.com/you\", \"https://linkedin.com/company/you\"]\n  }\n  </script>")

    track_score("Schema & Knowledge", min(sk_score, 4), 4)


# ---------------------------------------------------------------------------
# 17. Mobile-Friendliness & Page Weight
# ---------------------------------------------------------------------------
def check_mobile_and_weight(base_url):
    """Check mobile-friendliness signals and page weight."""
    print("\n--- Mobile-Friendliness & Page Weight ---")
    resp, soup = get_soup(base_url)
    if not soup:
        emit_check(FAIL, "result.checks.mobile.fetch_failed", "Could not fetch homepage")
        track_score("Mobile & Weight", 0, 4)
        return

    mw_score = 0

    # Viewport meta tag
    viewport = soup.find("meta", attrs={"name": "viewport"})
    if viewport and viewport.get("content"):
        content = viewport["content"]
        preview = content[:80]
        emit_check(PASS, "result.checks.mobile.viewport_found", f"Viewport meta tag found: {preview}", {"viewport": preview})
        if "width=device-width" in content:
            emit_check(PASS, "result.checks.mobile.viewport_responsive", "Uses width=device-width (responsive)")
            mw_score += 1
        else:
            emit_check(WARN, "result.checks.mobile.viewport_not_responsive", "Viewport doesn't use width=device-width")
            emit_fix("result.fixes.mobile.set_viewport_responsive", "Set viewport to responsive:\n  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />")
    else:
        emit_check(FAIL, "result.checks.mobile.viewport_missing", "No viewport meta tag — page won't render properly on mobile")
        emit_fix("result.fixes.mobile.add_viewport", "Add a viewport meta tag to your <head>:\n  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />\nMobile-first indexing means AI crawlers expect mobile-friendly pages.")

    # Page weight
    html_size = len(resp.text.encode("utf-8"))
    html_kb = html_size / 1024
    if html_kb < 100:
        emit_check(PASS, "result.checks.mobile.weight_light", f"HTML page weight: {html_kb:.0f} KB (lightweight)", {"kb": int(html_kb)})
        mw_score += 1
    elif html_kb < 500:
        emit_check(WARN, "result.checks.mobile.weight_medium", f"HTML page weight: {html_kb:.0f} KB — consider reducing inline CSS/JS", {"kb": int(html_kb)})
        emit_fix("result.fixes.mobile.reduce_weight", "Reduce page weight:\n  1. Move inline CSS to external stylesheets\n  2. Move inline JS to external scripts with defer/async\n  3. Remove unused HTML/comments\n  4. Enable server-side compression (gzip/brotli)")
    else:
        emit_check(FAIL, "result.checks.mobile.weight_heavy", f"HTML page weight: {html_kb:.0f} KB — very heavy, may slow AI crawlers", {"kb": int(html_kb)})
        emit_fix("result.fixes.mobile.reduce_weight_critical", "Page is too heavy for efficient crawling. Actions:\n  1. Externalize all inline CSS and JavaScript\n  2. Remove inline SVGs and base64 images — use external files\n  3. Enable gzip/brotli compression on your server\n  4. Consider code-splitting for JavaScript-heavy pages")

    # Count inline resources
    inline_styles = soup.find_all("style")
    inline_scripts = soup.find_all("script", src=False)
    inline_scripts = [s for s in inline_scripts if s.string and len(s.string.strip()) > 100 and s.get("type") != "application/ld+json"]

    if len(inline_styles) > 3 or len(inline_scripts) > 5:
        emit_check(WARN, "result.checks.mobile.inline_heavy", f"Heavy inline resources: {len(inline_styles)} <style> blocks, {len(inline_scripts)} large <script> blocks", {"styles": len(inline_styles), "scripts": len(inline_scripts)})
        emit_fix("result.fixes.mobile.externalize_inline", "Move inline styles and scripts to external files to reduce HTML weight\nand improve caching for repeat crawls.")
    else:
        emit_check(PASS, "result.checks.mobile.inline_ok", "Inline resources within acceptable range")
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
        signals_text = "; ".join(cache_signals[:2])
        emit_check(PASS, "result.checks.mobile.cache_headers_found", f"Cache headers found: {signals_text}", {"signals": signals_text})
        mw_score += 1
    else:
        emit_check(WARN, "result.checks.mobile.cache_headers_missing", "No cache headers (Cache-Control, ETag, Last-Modified)")
        emit_fix("result.fixes.mobile.add_cache_headers", "Add cache headers for efficient re-crawling:\n  Cache-Control: public, max-age=3600\n  ETag: (auto-generated by most servers)\nThis allows AI crawlers to use conditional requests (If-None-Match)\nand avoid re-downloading unchanged pages.")

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
            emit_check(PASS, "result.checks.url_norm.host_redirects", f"{alt_host} redirects to {hostname} (consistent)", {"alt": alt_host, "main": hostname})
            un_score += 1
        elif alt_resp.status_code == 200:
            emit_check(WARN, "result.checks.url_norm.host_duplicate", f"Both {hostname} and {alt_host} serve content — duplicate content risk", {"main": hostname, "alt": alt_host})
            emit_fix("result.fixes.url_norm.www_redirect", f"Set up a 301 redirect so one version redirects to the other:\n  # Nginx: redirect www to non-www\n  server {{ server_name www.{parsed.netloc.replace('www.', '')}; return 301 https://{parsed.netloc.replace('www.', '')}$request_uri; }}\nThen set the canonical URL to match the preferred version.", {"host": parsed.netloc.replace("www.", "")})
        else:
            emit_check(PASS, "result.checks.url_norm.host_alt_inaccessible", f"Alternate hostname ({alt_host}) is not accessible", {"alt": alt_host})
            un_score += 1
    except requests.RequestException:
        emit_check(PASS, "result.checks.url_norm.host_alt_inaccessible", f"Alternate hostname ({alt_host}) is not accessible", {"alt": alt_host})
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
            emit_check(INFO, "result.checks.url_norm.slash_both_200", "Both trailing slash and non-trailing slash return 200 — ensure canonical is set")
        elif resp_no_slash.is_redirect or resp_slash.is_redirect:
            emit_check(PASS, "result.checks.url_norm.slash_redirect", "Trailing slash consistency handled via redirect")
            un_score += 0.5
        else:
            emit_check(PASS, "result.checks.url_norm.path_consistent", "URL paths are consistent")
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
                emit_check(WARN, "result.checks.url_norm.case_mixed", "Mixed case URLs resolve to different pages — can cause duplicate content")
                emit_fix("result.fixes.url_norm.lowercase_url", "Ensure your server normalizes URL case (lowercase). In nginx:\n  location ~ [A-Z] { rewrite ^(.*)$ $scheme://$host$uri_lowercase permanent; }")
            else:
                emit_check(PASS, "result.checks.url_norm.case_consistent", "URL case handling is consistent")
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
        emit_check(FAIL, "result.checks.outbound.fetch_failed", "Could not fetch homepage")
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
        emit_check(PASS, "result.checks.outbound.links_found", f"{len(outbound_links)} outbound link(s) to {len(unique_domains)} unique domain(s)", {"count": len(outbound_links), "domains": len(unique_domains)})
        om_score += 0.5
        if authoritative_domains:
            auth_text = ", ".join(authoritative_domains[:5])
            emit_check(PASS, "result.checks.outbound.authoritative_links", f"Links to authoritative sources: {auth_text}", {"domains": auth_text})
            om_score += 0.5
        else:
            emit_check(INFO, "result.checks.outbound.no_authoritative", "No links to .gov/.edu/.org authoritative sources detected")
            emit_fix("result.fixes.outbound.add_authoritative_links", "Link to authoritative external sources where relevant (research papers, .gov/.edu sites,\nindustry standards). Outbound links to reputable sources signal well-researched content to AI engines.")
    else:
        emit_check(INFO, "result.checks.outbound.no_outbound_links", "No outbound links found — linking to authoritative sources increases content trust")
        emit_fix("result.fixes.outbound.add_outbound_links", "Add outbound links to reputable, authoritative sources that support your claims.\nAI engines see this as a signal of well-researched, trustworthy content.")

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
        emit_check(PASS, "result.checks.outbound.video_schema_found", "VideoObject structured data found")
        om_score += 0.5
    elif video_embeds:
        emit_check(WARN, "result.checks.outbound.video_no_schema", f"Video content found ({len(video_embeds)} embed(s)) but no VideoObject schema", {"count": len(video_embeds)})
        emit_fix("result.fixes.outbound.add_video_schema", "Add VideoObject structured data for your video content:\n  <script type=\"application/ld+json\">\n  {\n    \"@context\": \"https://schema.org\",\n    \"@type\": \"VideoObject\",\n    \"name\": \"Video Title\",\n    \"description\": \"Video description\",\n    \"thumbnailUrl\": \"https://yoursite.com/thumb.jpg\",\n    \"uploadDate\": \"2025-01-15\",\n    \"contentUrl\": \"https://yoursite.com/video.mp4\"\n  }\n  </script>")
    else:
        emit_check(INFO, "result.checks.outbound.no_video", "No video content detected")

    # Check for video transcripts
    if video_embeds:
        transcript_indicators = soup.find_all(class_=re.compile(r"transcript", re.IGNORECASE))
        transcript_indicators += soup.find_all(id=re.compile(r"transcript", re.IGNORECASE))
        if transcript_indicators:
            emit_check(PASS, "result.checks.outbound.transcript_found", "Video transcript section found — AI engines can index transcript text")
        else:
            emit_check(WARN, "result.checks.outbound.transcript_missing", "Videos found but no transcript detected")
            emit_fix("result.fixes.outbound.add_video_transcripts", "Add text transcripts for video content so AI crawlers can index the spoken content.\nPlace the transcript in a visible section below the video.")

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

    emit_check(INFO, "result.checks.outbound.multi_format_coverage", f"Multi-format coverage: {', '.join(sorted(formats_found)) or 'text only'}", {"formats": ", ".join(sorted(formats_found)) or "text only"})
    if len(formats_found) >= 3:
        emit_check(PASS, "result.checks.outbound.multi_format_strong", f"{len(formats_found)} content format(s) — broad AI surface area", {"count": len(formats_found)})
        om_score += 0.5
    elif len(formats_found) >= 1:
        emit_check(INFO, "result.checks.outbound.multi_format_limited", f"Only {len(formats_found)} non-text format(s) detected — more formats = more AI surface area", {"count": len(formats_found)})
        emit_fix("result.fixes.outbound.diversify_formats", "Diversify your content formats so AI engines encounter you in more contexts:\n"
            "  \u2022 Podcast (audio transcripts feed ChatGPT, Perplexity)\n"
            "  \u2022 PDF whitepapers (citable documents)\n"
            "  \u2022 Infographics with descriptive alt text\n"
            "  \u2022 Slides on SlideShare / Speaker Deck\n"
            "  \u2022 Video with transcripts")
    else:
        emit_check(WARN, "result.checks.outbound.multi_format_none", "No non-text formats detected — content is text-only")
        emit_fix("result.fixes.outbound.add_alt_format", "Add at least one alternative format (video with transcript, podcast, PDF, or infographic).\n"
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
            emit_check(PASS, "result.checks.outbound.tables_well_formed", f"{len(tables)} table(s) with proper <thead>/<th> markup", {"count": len(tables)})
            om_score += 0.5
        elif well_formed > 0:
            emit_check(WARN, "result.checks.outbound.tables_partial_headers", f"{well_formed}/{len(tables)} tables have proper headers — fix the rest", {"well_formed": well_formed, "total": len(tables)})
            emit_fix("result.fixes.outbound.add_table_thead", "Add <thead> and <th> to all data tables:\n  <table>\n    <thead><tr><th>Column 1</th><th>Column 2</th></tr></thead>\n    <tbody><tr><td>Data</td><td>Data</td></tr></tbody>\n  </table>")
        else:
            emit_check(WARN, "result.checks.outbound.tables_no_headers", f"{len(tables)} table(s) but none have proper <thead>/<th> headers", {"count": len(tables)})
            emit_fix("result.fixes.outbound.add_table_headers_semantic", "Add semantic headers to your tables for AI extraction:\n  <table>\n    <thead><tr><th>Header 1</th><th>Header 2</th></tr></thead>\n    <tbody>...</tbody>\n  </table>")
    else:
        emit_check(INFO, "result.checks.outbound.no_tables", "No tables found on homepage")

    # Definition elements
    dfn_tags = soup.find_all("dfn")
    abbr_tags = soup.find_all("abbr")
    if dfn_tags or abbr_tags:
        emit_check(PASS, "result.checks.outbound.definition_markup", f"Definition markup found: {len(dfn_tags)} <dfn>, {len(abbr_tags)} <abbr> tags", {"dfn": len(dfn_tags), "abbr": len(abbr_tags)})
        om_score += 0.5
    else:
        emit_check(INFO, "result.checks.outbound.no_definition_markup", "No <dfn> or <abbr> tags — use these to mark up technical terms and abbreviations")
        emit_fix("result.fixes.outbound.add_dfn_abbr", "Mark up key terms and abbreviations:\n  <dfn>Generative Engine Optimization</dfn> (GEO) is...\n  <abbr title=\"Generative Engine Optimization\">GEO</abbr>\nThis helps AI engines understand and define terms in your content.")

    track_score("Outbound & Media", min(om_score, 3), 3)


# ---------------------------------------------------------------------------
# 20. Multilingual Content Depth
# ---------------------------------------------------------------------------
def check_multilingual_depth(base_url):
    """Check if alternate language pages actually exist and have content."""
    print("\n--- Multilingual Content Depth ---")
    resp, soup = get_soup(base_url)
    if not soup:
        emit_check(FAIL, "result.checks.multilingual.fetch_failed", "Could not fetch homepage")
        return

    hreflangs = soup.find_all("link", rel="alternate", hreflang=True)
    if not hreflangs:
        emit_check(INFO, "result.checks.multilingual.no_hreflang", "No hreflang tags — skipping multilingual check")
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
            emit_check(PASS, "result.checks.multilingual.lang_substantive", f"[{lang}] has substantive content ({wc} words)", {"lang": lang, "count": wc})

    if thin_pages:
        for lang, href, wc in thin_pages:
            emit_check(WARN, "result.checks.multilingual.lang_thin", f"[{lang}] has very thin content ({wc} words): {href}", {"lang": lang, "count": wc, "url": href})
        emit_fix("result.fixes.multilingual.expand_alt_pages", "Alternate language pages have too little content. Ensure translations are complete\nand not just stubs or machine-translated snippets. AI engines may skip thin multilingual pages.")

    if broken_pages:
        for lang, href in broken_pages:
            emit_check(FAIL, "result.checks.multilingual.lang_broken", f"[{lang}] page is broken or inaccessible: {href}", {"lang": lang, "url": href})
        emit_fix("result.fixes.multilingual.fix_hreflang", "Fix broken hreflang URLs — they return errors. Either create the page\nor remove the hreflang tag to avoid confusing AI crawlers.")

    if not thin_pages and not broken_pages and good_pages:
        emit_check(PASS, "result.checks.multilingual.all_good", "All alternate language pages have substantive content")
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
    # × 8s timeout = up to 80s blocking. Fan out with ThreadPoolExecutor;
    # max_workers caps at the platform count (≤ 10).
    probed = {}  # platform_name -> (found: bool, url)
    platforms_to_probe = {k: v for k, v in platforms.items() if k not in on_page_links}

    browser_ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

    def _probe_platform(plat_name, plat_info):
        """Probe one platform; return (plat_name, found, url). No prints."""
        for probe_url in plat_info["probe_urls"]:
            try:
                r = requests.get(probe_url, timeout=8, allow_redirects=True, headers={
                    "User-Agent": browser_ua
                })
                if r.status_code == 200:
                    final_url = r.url.lower()
                    redirected_to_login = any(seg in final_url for seg in [
                        "/login", "/signin", "/sign_in", "/accounts/login",
                    ])
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
        emit_check(PASS, "result.checks.cross_platform.linked_on_site", f"{plat_name:<16} linked on site: {link}", {"platform": plat_name, "url": link})

    # Probed and found
    for plat_name, (found, url) in sorted(probed.items()):
        if found:
            found_platforms.append(plat_name)
            emit_check(PASS, "result.checks.cross_platform.profile_found", f"{plat_name:<16} profile found: {url}", {"platform": plat_name, "url": url})

    # Not found
    for plat_name, (found, url) in sorted(probed.items()):
        if not found:
            not_found_platforms.append(plat_name)
            emit_check(INFO, "result.checks.cross_platform.not_detected", f"{plat_name:<16} not detected", {"platform": plat_name})

    # --- Score & summary ---
    total_platforms = len(platforms)
    found_count = len(found_platforms)

    print()
    if found_count >= 6:
        emit_check(PASS, "result.checks.cross_platform.presence_strong", f"Strong cross-platform presence: {found_count}/{total_platforms} platforms", {"found": found_count, "total": total_platforms})
    elif found_count >= 3:
        emit_check(WARN, "result.checks.cross_platform.presence_moderate", f"Moderate cross-platform presence: {found_count}/{total_platforms} platforms", {"found": found_count, "total": total_platforms})
    elif found_count >= 1:
        emit_check(WARN, "result.checks.cross_platform.presence_limited", f"Limited cross-platform presence: {found_count}/{total_platforms} platforms", {"found": found_count, "total": total_platforms})
    else:
        emit_check(FAIL, "result.checks.cross_platform.presence_none", "No cross-platform presence detected")

    if not_found_platforms:
        emit_fix(
            "result.fixes.cross_platform.expand_presence",
            "Expand your brand presence on platforms that AI models train on:\n"
            + "".join(f"  - {p}\n" for p in not_found_platforms)
            + "AI engines (ChatGPT, Perplexity, Claude, Gemini) train on data from these platforms.\n"
            "Being present increases the probability of your brand being cited in AI answers,\n"
            "regardless of which source the AI pulls from.",
            {"platforms": ", ".join(not_found_platforms)},
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
        emit_check(WARN, "result.checks.multi_page.no_internal_pages", "No internal pages to sample")
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
        emit_check(WARN, "result.checks.multi_page.no_content_pages", "No content pages found to sample")
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
        "missing_title": ("Missing <title>", FAIL, "result.checks.multi_page.missing_title"),
        "missing_description": ("Missing meta description", FAIL, "result.checks.multi_page.missing_description"),
        "missing_canonical": ("Missing canonical URL", WARN, "result.checks.multi_page.missing_canonical"),
        "missing_structured_data": ("No structured data (JSON-LD)", WARN, "result.checks.multi_page.missing_structured_data"),
        "missing_h1": ("Missing <h1>", WARN, "result.checks.multi_page.missing_h1"),
        "low_word_count": ("Low word count (<100 words)", WARN, "result.checks.multi_page.low_word_count"),
        "missing_og": ("Missing Open Graph tags", WARN, "result.checks.multi_page.missing_og"),
        "missing_alt_text": ("Most images missing alt text", WARN, "result.checks.multi_page.missing_alt_text"),
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
    for key, (label, severity, i18n_key) in check_labels.items():
        pages = issues[key]
        if pages:
            all_good = False
            emit_check(severity, i18n_key, f"{label} on {len(pages)} page(s):", {"count": len(pages)})
            for p in pages[:3]:
                print(f"         {p}")
            if len(pages) > 3:
                print(f"         ...and {len(pages) - 3} more")
            emit_fix("result.fixes.multi_page." + key, fix_suggestions[key])

    if duplicate_descs:
        all_good = False
        emit_check(WARN, "result.checks.multi_page.duplicate_descriptions", "Duplicate meta descriptions found across pages:")
        for desc_text, pages in list(duplicate_descs.items())[:3]:
            print(f"         \"{desc_text[:60]}...\" on {len(pages)} pages:")
            for p in pages[:5]:
                print(f"           - {p}")
            if len(pages) > 5:
                print(f"           ...and {len(pages) - 5} more")
        emit_fix("result.fixes.multi_page.duplicate_descriptions", "Write unique meta descriptions for each page. Duplicate descriptions\nconfuse AI engines about which page to cite for a given topic.")

    if duplicate_titles:
        all_good = False
        emit_check(WARN, "result.checks.multi_page.duplicate_titles", "Duplicate <title> tags found across pages:")
        for t, pages in list(duplicate_titles.items())[:3]:
            print(f"         \"{t[:60]}\" on {len(pages)} pages:")
            for p in pages[:5]:
                print(f"           - {p}")
            if len(pages) > 5:
                print(f"           ...and {len(pages) - 5} more")
        emit_fix("result.fixes.multi_page.duplicate_titles", "Write unique <title> tags for each page. Identical titles cause keyword\ncannibalization — AI engines can't tell which page to cite for a given query.")

    if overlap_pairs:
        all_good = False
        emit_check(WARN, "result.checks.multi_page.content_overlap", "Content overlap / possible cannibalization between pages:")
        for u1, u2, j in sorted(overlap_pairs, key=lambda x: -x[2])[:3]:
            print(f"         {int(j * 100)}% overlap: {u1}  \u2194  {u2}")
        emit_fix("result.fixes.multi_page.content_overlap", "Two or more pages cover the same topic with highly overlapping content.\n"
            "Options:\n"
            "  1. Consolidate into one canonical page and 301-redirect the others.\n"
            "  2. Differentiate each page with distinct angles, examples, and keywords.\n"
            "  3. Use rel=canonical to point near-duplicates to the primary page.\n"
            "Cannibalization dilutes your AI visibility \u2014 pick the strongest page to surface.")

    if all_good:
        emit_check(PASS, "result.checks.multi_page.all_good", "All sampled pages maintain consistent GEO standards")
        track_score("Multi-Page", 5, 5)
    else:
        total_issues = sum(len(v) for v in issues.values()) + len(duplicate_descs) + len(duplicate_titles) + len(overlap_pairs)
        mp_score = max(5 - total_issues, 0)
        track_score("Multi-Page", mp_score, 5)

