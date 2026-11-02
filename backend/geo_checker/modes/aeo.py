"""aeo_visibility — Answer Engine Optimization audit (FAQ schema / question headings / direct answers).

Migrated from /geo_checker.py lines 3830-4538.
"""

import json
import re
import sys
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from ..constants import AI_BOTS, AI_CRAWLERS, PASS, WARN, FAIL, INFO, FIX
from ..io import fetch, get_soup, get_text_content, flesch_kincaid_grade
from ..output import print, emit_check, emit_fix, fix, _pad
from ..state import (
    SHOW_FIX, _scores, _page_cache, reset_state, track_score,
    get_ai_visibility_score, get_grade,
)
from ..orchestrate import run_silent


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


