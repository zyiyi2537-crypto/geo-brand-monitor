"""authority_audit — off-page authority signals (GitHub / npm / PyPI / Wikipedia / etc.).

Migrated from /geo_checker.py lines 4789-5275.
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
