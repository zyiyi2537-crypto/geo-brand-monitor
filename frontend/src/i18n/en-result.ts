const enResult = {
"result": {
            "title": "GEO Readiness Results",
            "resultsFor": "Results for:",
            "progress": {
              "title": "Running check…",
              "elapsed": "Elapsed {{seconds}}s",
              "hint": "Please keep this page open",
              "almostDone": "Almost done…",
              "subtitle": {
                "default": "Running all 25 GEO categories",
                "compare": "Scoring multiple sites side-by-side",
                "crawlTest": "Testing AI crawler reachability",
                "authority": "Auditing off-page authority signals",
                "citation": "Checking AI citations via Perplexity",
                "visibility": "Running multi-engine visibility audit",
                "entity": "Auditing AI recognition of this entity"
              },
              "stages": {
                "default": {
                  "fetch": "Fetching page & HTTP headers",
                  "protocols": "Checking robots, sitemap, llms.txt",
                  "structured": "Parsing structured data & schema",
                  "content": "Analyzing content quality for AI",
                  "technical": "Testing technical robustness & media",
                  "authority": "Gathering authority & trust signals",
                  "finalize": "Scoring & finalizing report"
                },
                "compare": {
                  "fetch": "Fetching all target sites",
                  "parse": "Parsing each site",
                  "score": "Scoring all 25 GEO categories",
                  "diff": "Computing category differences",
                  "finalize": "Building comparison table"
                },
                "crawlTest": {
                  "robots": "Reading robots.txt rules",
                  "probe": "Probing GPTBot / ClaudeBot / PerplexityBot",
                  "waf": "Testing WAF & CDN reachability",
                  "commonCrawl": "Querying Common Crawl index",
                  "finalize": "Summarizing crawler findings"
                },
                "authority": {
                  "github": "Searching GitHub mentions",
                  "pkg": "Checking npm / PyPI registries",
                  "wiki": "Looking up Wikipedia & Wikidata",
                  "social": "Collecting social signals",
                  "finalize": "Aggregating authority score"
                },
                "citation": {
                  "prepare": "Preparing brand-relevant queries",
                  "perplexity": "Querying Perplexity AI (this can take a while)",
                  "parseCites": "Parsing citations & source domains",
                  "finalize": "Scoring citation coverage"
                },
                "visibility": {
                  "prepare": "Preparing visibility queries",
                  "chatgpt": "Asking ChatGPT (this can take a while)",
                  "perplexity": "Asking Perplexity",
                  "claude": "Asking Claude",
                  "classify": "Classifying brand framings",
                  "finalize": "Aggregating cross-engine visibility"
                },
                "entity": {
                  "wiki": "Checking Wikipedia coverage",
                  "wikidata": "Checking Wikidata entity",
                  "platforms": "Checking platform coverage (GitHub, IMDB…)",
                  "llm": "Probing AI recognition (multi-engine)",
                  "sentiment": "Classifying sentiment & framing",
                  "gaps": "Detecting content gaps",
                  "finalize": "Aggregating entity GEO score"
                }
              }
            },
            "checks": {
              "https": {
                "uses_https": "Site uses HTTPS",
                "not_https": "Site does not use HTTPS — AI engines prefer secure sites"
              },
              "robots": {
                "not_found": "robots.txt not found at {{url}}",
                "found": "robots.txt found ({{bytes}} bytes)",
                "sitemap_ref_present": "robots.txt references a sitemap",
                "sitemap_ref_missing": "robots.txt does not reference a sitemap",
                "wildcard_blocks_all": "Wildcard user-agent blocks all crawlers (Disallow: /)",
                "bots_blocked": "AI bots explicitly BLOCKED: {{bots}}",
                "bots_with_directives": "AI bots with directives (not blocked): {{bots}}",
                "bots_inherit_wildcard": "AI bots not mentioned (inherit wildcard rules): {{bots}}",
                "ai_txt_found": "{{path}} found — strategic AI crawler policy declared",
                "ai_txt_not_found": "No ai.txt or .well-known/ai.txt found — emerging standard for AI-specific policies"
              },
              "llms": {
                "found": "{{filename}} found ({{lines}} lines, {{bytes}} bytes)",
                "title_present": "Title: {{title}}",
                "title_missing": "No markdown title (# heading) — recommended by llms.txt spec",
                "description_present": "Contains descriptive text",
                "description_missing": "No descriptive text found — should explain what the site/org does",
                "sections_found": "{{count}} section(s) found (## headings)",
                "sections_missing": "No sections (## headings) — consider organizing content into sections",
                "links_found": "{{count}} link(s) to resources found",
                "links_missing": "No links found — llms.txt should link to key resources",
                "blockquotes_present": "Blockquote descriptions (>) present",
                "too_short": "File is very short ({{bytes}} bytes) — may be a placeholder",
                "file_not_found": "{{filename}} not found"
              },
              "well_known": {
                "file_found": "{{path}} found — {{description}}",
                "invalid_json": "{{path}} exists but contains invalid JSON",
                "file_not_found": "{{path}} not found — {{description}}"
              },
              "sitemap": {
                "found": "Sitemap found at {{path}} ({{count}} <loc> entries)",
                "lastmod_present": "Sitemap includes <lastmod> timestamps",
                "lastmod_missing": "Sitemap missing <lastmod> timestamps — helps AI engines know content freshness",
                "not_found": "No sitemap.xml found"
              },
              "meta": {
                "fetch_failed": "Could not fetch homepage",
                "title_found": "<title> found: \"{{title}}\"",
                "title_missing": "Missing <title> tag",
                "description_found": "Meta description found ({{chars}} chars)",
                "description_too_short": "Meta description is very short — aim for 120-160 characters",
                "description_missing": "Missing meta description",
                "canonical_found": "Canonical URL set: {{url}}",
                "canonical_missing": "No canonical URL — can cause duplicate content issues for AI engines",
                "og_tags_found": "Open Graph tags found: {{tags}}",
                "og_tags_missing": "No Open Graph tags — used by AI engines for content summarization",
                "lang_declared": "Language declared: {{lang}}",
                "lang_missing": "No lang attribute on <html> — helps AI engines understand content language",
                "hreflang_found": "Hreflang tags found for: {{langs}}",
                "hreflang_missing": "No hreflang tags — add these if your site supports multiple languages",
                "twitter_cards_found": "Twitter Card tags present: {{tags}}",
                "twitter_cards_missing": "Missing Twitter Card tags: {{missing}} — improves X/Twitter link previews"
              },
              "mobile": {
                "fetch_failed": "Could not fetch homepage",
                "viewport_found": "Viewport meta tag found: {{viewport}}",
                "viewport_responsive": "Uses width=device-width (responsive)",
                "viewport_not_responsive": "Viewport doesn't use width=device-width",
                "viewport_missing": "No viewport meta tag — page won't render properly on mobile",
                "weight_light": "HTML page weight: {{kb}} KB (lightweight)",
                "weight_medium": "HTML page weight: {{kb}} KB — consider reducing inline CSS/JS",
                "weight_heavy": "HTML page weight: {{kb}} KB — very heavy, may slow AI crawlers",
                "inline_heavy": "Heavy inline resources: {{styles}} <style> blocks, {{scripts}} large <script> blocks",
                "inline_ok": "Inline resources within acceptable range",
                "cache_headers_found": "Cache headers found: {{signals}}",
                "cache_headers_missing": "No cache headers (Cache-Control, ETag, Last-Modified)"
              },
              "structured_data": {
                "fetch_failed": "Could not fetch homepage",
                "jsonld_found": "Found {{count}} JSON-LD block(s)",
                "jsonld_missing": "No JSON-LD structured data found — helps AI engines understand your content",
                "schema_ref_only": "schema.org references found (possibly microdata or RDFa)",
                "granular_types": "Granular schema types present: {{types}}",
                "generic_only": "Only generic schema types found ({{types}}) — add granular types for richer AI extraction",
                "nonstandard_types": "Non-standard @types detected — consider using schema.org granular types",
                "product_reviews": "Product schema includes reviews/ratings — strong AI signal",
                "product_no_reviews": "Product schema present but no review/aggregateRating field"
              },
              "content_access": {
                "fetch_failed": "Could not fetch homepage",
                "words_ok": "Homepage has {{count}} words in initial HTML",
                "words_low": "Homepage has only {{count}} words in initial HTML — may rely too heavily on JavaScript rendering",
                "words_js_only": "Homepage has only {{count}} words — likely JS-rendered, invisible to most AI crawlers",
                "ratio_good": "Content-to-HTML ratio: {{ratio}}% (good)",
                "ratio_low": "Content-to-HTML ratio: {{ratio}}% — low ratio means lots of boilerplate vs. real content",
                "ratio_very_low": "Content-to-HTML ratio: {{ratio}}% — very low, mostly boilerplate/code",
                "headings_found": "Heading structure found ({{summary}})",
                "first_heading_not_h1": "First heading is <{{tag}}>, not <h1> — clear hierarchy helps AI engines",
                "headings_missing": "No heading tags found — structured headings help AI engines parse content"
              },
              "crawl_ready": {
                "fetch_failed": "Could not fetch homepage",
                "spa_empty": "Likely a client-side rendered SPA with minimal server-side content",
                "spa_with_ssr": "SPA framework detected but server-side content is present (SSR/SSG)",
                "ssr_content": "Content is rendered server-side",
                "meta_noindex": "Meta robots contains 'noindex' — page will be excluded from AI training data",
                "meta_nofollow": "Meta robots contains 'nofollow' — AI crawlers won't follow links on this page",
                "meta_noai": "Meta robots contains AI-specific opt-out directive: {{content}}",
                "meta_allows_index": "Meta robots allows indexing: {{content}}",
                "meta_no_restriction": "No restrictive meta robots tag found",
                "xrobots_restrict": "X-Robots-Tag header restricts AI: {{header}}",
                "xrobots_present": "X-Robots-Tag header present: {{header}}",
                "xrobots_clean": "No restrictive X-Robots-Tag header",
                "paywall_detected": "Possible gated content detected (classes/ids: {{classes}})",
                "no_paywall": "No paywall/login-wall indicators detected",
                "semantic_good": "Good semantic HTML structure ({{tags}})",
                "semantic_limited": "Limited semantic HTML ({{tags}}) — more semantic tags help AI parse content",
                "semantic_missing": "No semantic HTML tags found — AI crawlers rely on semantic structure",
                "alt_good": "{{with_alt}}/{{total}} images have alt text ({{pct}}%)",
                "alt_medium": "{{with_alt}}/{{total}} images have alt text ({{pct}}%) — aim for >80%",
                "alt_poor": "Only {{with_alt}}/{{total}} images have alt text ({{pct}}%) — AI crawlers need alt text",
                "no_images": "No images found on homepage",
                "internal_links_good": "{{count}} internal links — good for AI crawl discovery",
                "internal_links_few": "Only {{count}} internal links — more internal links help AI engines discover content",
                "internal_links_none": "Very few internal links ({{count}}) — AI crawlers rely on links to find content",
                "response_fast": "Response time: {{seconds}}s",
                "response_slow": "Response time: {{seconds}}s — slow responses may cause AI crawlers to skip pages",
                "response_timeout": "Response time: {{seconds}}s — too slow for reliable AI crawling"
              },
              "content_quality": {
                "fetch_failed": "Could not fetch homepage",
                "readability_good": "Readability: Flesch-Kincaid grade {{grade}} (accessible)",
                "readability_simple": "Readability: Flesch-Kincaid grade {{grade}} (very simple)",
                "readability_complex": "Readability: Flesch-Kincaid grade {{grade}} (complex) — simpler text ranks better in AI answers",
                "faq_detected": "FAQ content detected — strong signal for AI-generated answers",
                "faq_partial": "Possible FAQ-like content — consider adding FAQPage structured data",
                "faq_missing": "No FAQ content detected — FAQ pages rank well in AI-generated answers",
                "stats_good": "{{count}} quotable statistics found — good for AI citations",
                "stats_few": "{{count}} statistic(s) found — more specific data improves AI citation likelihood",
                "stats_missing": "No quotable statistics found — specific numbers/data help AI engines cite your content",
                "sources_cited": "{{count}} source attribution(s) found — increases trust for AI engines",
                "sources_missing": "No explicit source attributions — citing sources increases AI trust in your content",
                "lists_good": "Structured lists found ({{lists}} lists, {{items}} items)",
                "lists_few": "Some list content ({{items}} items) — structured lists help AI extract key points",
                "lists_missing": "No list elements — structured lists help AI engines extract key points",
                "first_para_good": "First paragraph ({{words}} words) contains extractable facts: {{facts}}",
                "first_para_length": "First paragraph has facts ({{facts}}) but is {{words}} words — aim for 25-120",
                "first_para_no_facts": "First paragraph ({{words}} words) lacks extractable facts — add a definition or key statistic up front",
                "first_para_missing": "Could not identify a substantive first paragraph — AI engines rely on early content for extraction"
              },
              "tech_crawl": {
                "fetch_failed": "Could not fetch homepage",
                "canonical_chain": "Canonical chain detected: {{from}} -> {{via}} -> {{to}}",
                "canonical_resolves": "Canonical URL resolves correctly",
                "canonical_broken": "Canonical URL {{url}} returns error",
                "canonical_self": "Canonical URL is self-referencing (correct)",
                "redirect_chain": "Redirect chain with {{hops}} hops: {{chain}} -> {{final}}",
                "redirect_ok": "{{count}} redirect(s) — within acceptable range",
                "no_redirect": "No redirects — direct access",
                "redirect_test_failed": "Could not test redirect chain",
                "http2_supported": "HTTP/{{version}} supported — faster crawling",
                "http1_only": "HTTP/{{version}} — consider upgrading to HTTP/2 or HTTP/3 for faster crawling",
                "http_unknown": "Could not determine HTTP version",
                "feed_declared": "RSS/Atom feed(s) found: {{feeds}}",
                "feed_found_at_path": "Feed found at {{path}}",
                "feed_missing": "No RSS/Atom feed found — feeds help AI engines monitor content freshness",
                "feed_full_content": "Feed provides full content (avg {{avg_words}} words/item) — AI-friendly",
                "feed_excerpts": "Feed provides excerpts (avg {{avg_words}} words/item) — consider full content",
                "feed_headlines_only": "Feed items are very short (avg {{avg_words}} words) — mostly headlines",
                "machine_readable": "Machine-readable / integration endpoints: {{paths}}",
                "no_machine_readable": "No API / integration / webhook documentation detected"
              },
              "authority": {
                "fetch_failed": "Could not fetch homepage",
                "security_headers_strong": "Strong security headers ({{count}}/4): {{headers}}",
                "security_headers_partial": "Some security headers present ({{count}}/4): {{headers}}",
                "security_headers_missing": "No security headers found — reduces trust signal for AI engines",
                "humans_txt_found": "humans.txt found — authorship transparency",
                "humans_txt_missing": "No humans.txt — optional authorship transparency file",
                "author_jsonld": "Author markup found in structured data (JSON-LD)",
                "author_meta": "Author information found (meta/link tag)",
                "author_class_only": "Author class detected in HTML — consider adding schema.org Person markup",
                "author_missing": "No author attribution found — authorship signals boost AI trust (E-E-A-T)",
                "bio_page_found": "Bio/about page found at {{path}}",
                "credentials_found": "Credential signals in bio: {{credentials}}",
                "credentials_weak": "Bio page has little credential language — add credentials/experience",
                "external_bylines": "External byline/profile links: {{bylines}}",
                "no_external_bylines": "No external bylines detected on bio page",
                "no_bio_page": "No author bio / about / team page found"
              },
              "ai_opt": {
                "fetch_failed": "Could not fetch homepage",
                "freshness_found": "Content freshness signals found:",
                "freshness_missing": "No content freshness signals — add dateModified to JSON-LD or <time> elements",
                "brand_inconsistent": "Inconsistent site name across tags: {{names}}",
                "brand_consistent": "Brand entity \"{{name}}\" used consistently ({{count}} occurrences)",
                "brand_sparse": "Brand entity \"{{name}}\" found but used sparingly — consistent naming helps AI entity recognition",
                "brand_unknown": "Could not determine primary brand/entity name",
                "api_endpoint_found": "Machine-readable endpoint found: {{path}}",
                "api_endpoint_missing": "No public API endpoints found — optional, but helps AI systems access structured data",
                "sitemap_cadence": "Sitemap contains {{total}} <lastmod> entries (median age: {{median_days}} days, {{fresh_90}}/{{count}} updated in last 90d)",
                "cadence_healthy": "Healthy sitewide update cadence",
                "cadence_moderate": "Moderate cadence — less than half of pages updated in the last 90 days",
                "cadence_low": "Low cadence — most pages are stale (median {{median_days}} days old)",
                "cadence_unknown": "Could not analyze sitewide update cadence (no parseable <lastmod> in sitemap)"
              },
              "social": {
                "fetch_failed": "Could not fetch homepage",
                "twitter_found": "Twitter/X card tags found: {{tags}}",
                "twitter_missing": "No Twitter/X card meta tags found",
                "sameas_found": "sameAs social links in JSON-LD ({{count}}):",
                "sameas_missing": "No sameAs social profile links in structured data",
                "html_links_found": "{{count}} social profile link(s) found in HTML — consider adding them as sameAs in JSON-LD too",
                "no_social_links": "No social profile links detected on the page"
              },
              "answer_format": {
                "fetch_failed": "Could not fetch homepage",
                "definitions_found": "{{count}} definition-style sentence(s) found — highly citable by AI",
                "definitions_missing": "No definition-style sentences detected",
                "tables_with_headers": "Comparison table(s) with headers found — AI engines extract tabular data",
                "tables_without_headers": "Tables found but missing <th> headers — add headers for AI extraction",
                "tables_missing": "No comparison tables — consider adding tables for feature comparisons, pricing, etc.",
                "steps_found": "Step-by-step instructional content detected — great for 'how to' AI answers",
                "steps_missing": "No step-by-step instructions found",
                "proscons_found": "Pros/cons or advantages/disadvantages content detected",
                "proscons_missing": "No pros/cons pattern detected",
                "summary_found": "Summary/key takeaways section found — AI engines prefer concise summaries",
                "summary_missing": "No key takeaways or TL;DR section found",
                "question_headings_strong": "{{count}} question-pattern heading(s) — strong conversational readiness",
                "question_headings_few": "Only {{count}} question-pattern heading(s) — add more for chat-style queries",
                "question_headings_none": "No question-pattern headings detected — low conversational readiness"
              },
              "platform_reg": {
                "fetch_failed": "Could not fetch homepage",
                "gsc_verified": "Google Search Console verification tag found",
                "gsc_missing": "No Google Search Console verification tag found",
                "bing_verified": "Bing Webmaster Tools verification tag found",
                "bing_missing": "No Bing Webmaster Tools verification tag found",
                "yandex_verified": "Yandex Webmaster verification tag found",
                "yandex_missing": "No Yandex Webmaster verification tag — relevant if targeting international AI platforms",
                "indexnow_endpoint": "IndexNow endpoint found at {{path}} — enables instant index notifications",
                "indexnow_meta": "IndexNow meta tag found",
                "indexnow_missing": "No IndexNow integration detected",
                "pinterest_verified": "Pinterest domain verification found",
                "summary_registered": "Registered: {{platforms}}",
                "summary_missing": "Not detected: {{platforms}}"
              },
              "schema_kg": {
                "fetch_failed": "Could not fetch homepage",
                "breadcrumb_schema": "BreadcrumbList schema found — helps AI engines understand site hierarchy",
                "breadcrumb_html_only": "HTML breadcrumb navigation found but no BreadcrumbList schema",
                "breadcrumb_none": "No breadcrumb navigation or schema found",
                "org_schema_found": "Organization/Business schema found: @type = {{type}}",
                "org_field_present": "{{label}}: present",
                "org_field_missing": "{{label}}: missing",
                "optional_present": "Optional fields present: {{fields}}",
                "optional_missing": "Optional fields missing: {{fields}}",
                "org_schema_missing": "No Organization/LocalBusiness schema found — needed for knowledge panels"
              },
              "url_norm": {
                "host_redirects": "{{alt}} redirects to {{main}} (consistent)",
                "host_duplicate": "Both {{main}} and {{alt}} serve content — duplicate content risk",
                "host_alt_inaccessible": "Alternate hostname ({{alt}}) is not accessible",
                "slash_both_200": "Both trailing slash and non-trailing slash return 200 — ensure canonical is set",
                "slash_redirect": "Trailing slash consistency handled via redirect",
                "path_consistent": "URL paths are consistent",
                "case_mixed": "Mixed case URLs resolve to different pages — can cause duplicate content",
                "case_consistent": "URL case handling is consistent"
              },
              "outbound": {
                "fetch_failed": "Could not fetch homepage",
                "links_found": "{{count}} outbound link(s) to {{domains}} unique domain(s)",
                "authoritative_links": "Links to authoritative sources: {{domains}}",
                "no_authoritative": "No links to .gov/.edu/.org authoritative sources detected",
                "no_outbound_links": "No outbound links found — linking to authoritative sources increases content trust",
                "video_schema_found": "VideoObject structured data found",
                "video_no_schema": "Video content found ({{count}} embed(s)) but no VideoObject schema",
                "no_video": "No video content detected",
                "transcript_found": "Video transcript section found — AI engines can index transcript text",
                "transcript_missing": "Videos found but no transcript detected",
                "tables_well_formed": "{{count}} table(s) with proper <thead>/<th> markup",
                "tables_partial_headers": "{{well_formed}}/{{total}} tables have proper headers — fix the rest",
                "tables_no_headers": "{{count}} table(s) but none have proper <thead>/<th> headers",
                "no_tables": "No tables found on homepage",
                "definition_markup": "Definition markup found: {{dfn}} <dfn>, {{abbr}} <abbr> tags",
                "no_definition_markup": "No <dfn> or <abbr> tags — use these to mark up technical terms and abbreviations",
                "multi_format_coverage": "Multi-format coverage: {{formats}}",
                "multi_format_strong": "{{count}} content format(s) — broad AI surface area",
                "multi_format_limited": "Only {{count}} non-text format(s) detected — more formats = more AI surface area",
                "multi_format_none": "No non-text formats detected — content is text-only"
              },
              "multilingual": {
                "fetch_failed": "Could not fetch homepage",
                "no_hreflang": "No hreflang tags — skipping multilingual check",
                "lang_substantive": "[{{lang}}] has substantive content ({{count}} words)",
                "lang_thin": "[{{lang}}] has very thin content ({{count}} words): {{url}}",
                "lang_broken": "[{{lang}}] page is broken or inaccessible: {{url}}",
                "all_good": "All alternate language pages have substantive content"
              },
              "cross_platform": {
                "linked_on_site": "{{platform}} linked on site: {{url}}",
                "profile_found": "{{platform}} profile found: {{url}}",
                "not_detected": "{{platform}} not detected",
                "presence_strong": "Strong cross-platform presence: {{found}}/{{total}} platforms",
                "presence_moderate": "Moderate cross-platform presence: {{found}}/{{total}} platforms",
                "presence_limited": "Limited cross-platform presence: {{found}}/{{total}} platforms",
                "presence_none": "No cross-platform presence detected"
              },
              "multi_page": {
                "no_internal_pages": "No internal pages to sample",
                "no_content_pages": "No content pages found to sample",
                "missing_title": "Missing <title> on {{count}} page(s):",
                "missing_description": "Missing meta description on {{count}} page(s):",
                "missing_canonical": "Missing canonical URL on {{count}} page(s):",
                "missing_structured_data": "No structured data (JSON-LD) on {{count}} page(s):",
                "missing_h1": "Missing <h1> on {{count}} page(s):",
                "low_word_count": "Low word count (<100 words) on {{count}} page(s):",
                "missing_og": "Missing Open Graph tags on {{count}} page(s):",
                "missing_alt_text": "Most images missing alt text on {{count}} page(s):",
                "duplicate_descriptions": "Duplicate meta descriptions found across pages:",
                "duplicate_titles": "Duplicate <title> tags found across pages:",
                "content_overlap": "Content overlap / possible cannibalization between pages:",
                "all_good": "All sampled pages maintain consistent GEO standards"
              },
              "brand_kg": {
                "wikipedia_found": "Wikipedia page found: \"{{title}}\"",
                "wikipedia_not_found": "No Wikipedia page found for \"{{brand}}\"",
                "wikidata_found": "Wikidata entity found: {{id}}",
                "wikidata_not_found": "No Wikidata entity found for \"{{brand}}\"",
                "backlinks_strong": "Wikipedia backlinks: {{count}}+ pages link to this entity — strong authority",
                "backlinks_moderate": "Wikipedia backlinks: {{count}} pages link to this entity",
                "backlinks_weak": "Only {{count}} Wikipedia backlink(s) — entity is recognized but niche"
              },
              "trust_safety": {
                "fetch_failed": "Could not fetch homepage",
                "privacy_found": "Privacy policy found: {{path}}",
                "privacy_missing": "No privacy policy page detected",
                "terms_found": "Terms of service found: {{path}}",
                "terms_missing": "No terms of service page detected",
                "contact_found": "Contact page found: {{path}}",
                "contact_missing": "No contact page detected",
                "legal_found": "Legal/DMCA/imprint page found: {{path}}",
                "legal_missing": "No DMCA / legal / imprint page detected",
                "identity_strong": "Strong business identity in footer/schema: {{signals}}",
                "identity_partial": "Partial business identity: {{signals}}",
                "identity_missing": "No business identity signals found (email, phone, address, or legal entity)"
              }
            },
            "fixes": {
              "ai_opt": {
                "add_brand_meta": "Make your brand name discoverable by adding:\n  <meta property=\"og:site_name\" content=\"Your Brand\" />\nAnd use a consistent 'Brand — Page Title' format in your <title> tags.",
                "add_freshness": "Add freshness signals so AI engines know your content is current:\n  1. Add dateModified to your JSON-LD: \"dateModified\": \"2025-01-15\"\n  2. Use <time> tags: <time datetime=\"2025-01-15\">January 15, 2025</time>\n  3. Set Last-Modified HTTP header on your server",
                "unify_brand_name": "Use the same brand name everywhere. Ensure og:site_name, the title tag suffix,\nand JSON-LD Organization name all use the exact same string.\nPick one: {names}",
                "use_brand_consistently": "Use your brand name \"{name}\" more consistently throughout the page content.\nMention it in headings, intro paragraphs, and structured data to strengthen entity recognition.",
                "increase_cadence": "Increase content refresh cadence. AI engines prefer sites that update regularly — stale pages\ndrop out of training windows and retrieval indexes.",
                "refresh_stale_content": "Most of your content hasn't been touched in months. Refresh high-value pages periodically\n(update stats, add recent examples, bump dateModified) so AI engines see ongoing maintenance."
              },
              "answer_format": {
                "add_comparison_tables": "Add comparison tables where applicable (pricing, features, vs. competitors):\n  <table>\n    <thead><tr><th>Feature</th><th>Basic</th><th>Pro</th></tr></thead>\n    <tbody>...</tbody>\n  </table>\nAI engines frequently cite tabular data in comparison answers.",
                "add_definitions": "Add clear definition sentences that AI engines can directly quote:\n  'Generative Engine Optimization (GEO) is the practice of optimizing web content...'\n  'A sitemap refers to a file that lists all pages on a website...'\nPattern: '[Term] is/are [clear definition].'",
                "add_proscons": "Add pros and cons sections for products, services, or comparisons:\n  <h3>Pros</h3>\n  <ul><li>Fast performance</li><li>Easy to use</li></ul>\n  <h3>Cons</h3>\n  <ul><li>Limited free tier</li><li>No mobile app</li></ul>\nAI engines frequently cite balanced pros/cons in recommendation answers.",
                "add_steps": "Add numbered how-to instructions where relevant:\n  <h2>How to Set Up Your Account</h2>\n  <ol>\n    <li>Go to the signup page</li>\n    <li>Enter your email address</li>\n    <li>Verify your account</li>\n  </ol>\nAI engines surface step-by-step content for 'how to' queries.",
                "add_summary": "Add a 'Key Takeaways' or 'TL;DR' section near the top or bottom:\n  <h2>Key Takeaways</h2>\n  <ul>\n    <li>Main point 1</li>\n    <li>Main point 2</li>\n  </ul>\nAI engines often pull from summary sections for quick answers.",
                "add_question_headings": "Add more question-pattern headings that match how people prompt AI engines:\n  <h2>What is GEO?</h2>\n  <h2>How do I optimize for AI search?</h2>\n  <h2>Why does GEO matter?</h2>\nFollow each with a short, direct answer so AI engines can extract it.",
                "add_question_headings_intro": "Add question-pattern headings so AI engines can match chat-style queries to your content:\n  <h2>What is GEO?</h2>\n  <h3>How does this work?</h3>\nPages structured around who/what/how/why questions rank higher in AI answers.",
                "add_table_headers": "Add proper headers to your tables:\n  <table>\n    <thead><tr><th>Feature</th><th>Plan A</th><th>Plan B</th></tr></thead>\n    <tbody><tr><td>Price</td><td>$10</td><td>$20</td></tr></tbody>\n  </table>\nAI engines extract well-structured tables for comparison answers."
              },
              "authority": {
                "add_author": "Add author information to boost E-E-A-T signals:\n  1. Add <meta name=\"author\" content=\"Author Name\">\n  2. Or add author to your JSON-LD structured data:\n     \"author\": {\"@type\": \"Person\", \"name\": \"Author Name\"}\n  3. For blog posts, display author name, bio, and credentials visibly on the page.",
                "add_humans_txt": "Create a humans.txt at your site root to signal authorship:\n  /* TEAM */\n  Name: Your Name\n  Role: Lead Developer\n  Contact: email@example.com\n  \n  /* SITE */\n  Last update: 2025/01/15\n  Standards: HTML5, CSS3\nSee humanstxt.org for the full spec.",
                "add_security_headers": "Add missing security headers to your server config:\n  Strict-Transport-Security: max-age=31536000; includeSubDomains\n  Content-Security-Policy: default-src 'self'\n  X-Content-Type-Options: nosniff\n  X-Frame-Options: DENY",
                "add_security_headers_nginx": "Add security headers to your server response. In nginx:\n  add_header Strict-Transport-Security \"max-age=31536000; includeSubDomains\" always;\n  add_header Content-Security-Policy \"default-src 'self'\" always;\n  add_header X-Content-Type-Options \"nosniff\" always;\n  add_header X-Frame-Options \"DENY\" always;",
                "strengthen_bio": "Strengthen your bio/about page with explicit E-E-A-T signals:\n  • Credentials (PhD, MD, certifications)\n  • Years of experience and roles\n  • Notable prior affiliations\n  • External bylines, publications, or press coverage",
                "add_external_bylines": "Link to external bylines (Medium, Substack, trade press, Google Scholar, ORCID)\nfrom your bio/about page. Independent bylines carry more E-E-A-T weight than self-claims.",
                "create_about_page": "Create a substantive /about or /team page (200+ words) documenting who is behind\nthe site: real names, credentials, photos, contact paths, and links to external profiles.\nAI engines treat faceless sites as lower E-E-A-T.",
                "upgrade_author_jsonld": "Upgrade your author attribution with JSON-LD:\n  \"author\": {\n    \"@type\": \"Person\",\n    \"name\": \"Author Name\",\n    \"url\": \"https://authorsite.com\"\n  }"
              },
              "content_access": {
                "add_h1": "Ensure the first heading on the page is an <h1> tag containing the primary topic.\nUse a logical hierarchy: h1 > h2 > h3 (don't skip levels).",
                "add_headings": "Add heading tags to structure your content:\n  <h1>Main Page Topic</h1>\n  <h2>Subtopic</h2>\n  <h3>Detail</h3>\nHeadings help AI engines understand content hierarchy and extract key topics.",
                "client_rendered_workarounds": "Your page content is likely rendered client-side via JavaScript. AI crawlers cannot execute JS.\nSolutions:\n  1. Use server-side rendering (SSR) — Next.js, Nuxt.js, etc.\n  2. Use static site generation (SSG) — pre-render pages at build time.\n  3. Add a pre-rendering service (e.g., Prerender.io) to serve static HTML to bots.",
                "enable_ssr": "Ensure key content is rendered server-side (SSR/SSG) so AI crawlers can read it.\nIf using React/Vue/Angular, switch to Next.js/Nuxt.js/Angular Universal for server-side rendering.",
                "improve_text_ratio": "Extremely low content ratio. Likely causes:\n  1. Heavy inline CSS/JS frameworks — externalize them.\n  2. Client-side rendering — switch to SSR/SSG.\n  3. Content hidden in JavaScript state — ensure HTML contains readable text.",
                "reduce_html_bloat": "Reduce HTML bloat: minimize inline CSS/JS, remove unused markup, and move scripts to external files.\nEnsure the page body contains substantive, unique content — not just navigation and footers."
              },
              "content_quality": {
                "add_attributions": "Add source attributions to increase credibility:\n  'According to [Source Name], ...'\n  'Data from our 2025 industry report shows...'\n  'A study by [Institution] found...'\nAI engines weight attributed claims higher than unattributed ones.",
                "add_faq_schema": "Add FAQPage schema to boost AI answer ranking:\n  <script type=\"application/ld+json\">\n  {\n    \"@context\": \"https://schema.org\",\n    \"@type\": \"FAQPage\",\n    \"mainEntity\": [{\n      \"@type\": \"Question\",\n      \"name\": \"What is your product?\",\n      \"acceptedAnswer\": {\n        \"@type\": \"Answer\",\n        \"text\": \"Our product is...\"\n      }\n    }]\n  }\n  </script>",
                "add_faq_section": "Consider adding an FAQ section to your page. Format questions as headings:\n  <h2>Frequently Asked Questions</h2>\n  <h3>What does your product do?</h3>\n  <p>Clear, concise answer...</p>\nThen add FAQPage structured data (JSON-LD) for each Q&A pair.",
                "add_lists": "Add structured lists to make content easily extractable by AI:\n  <ul>\n    <li>Key feature or benefit</li>\n    <li>Another important point</li>\n  </ul>\nUse <ol> for steps/processes and <ul> for features/benefits.",
                "add_statistics": "Add concrete, quotable statistics to your content:\n  '95% of customers report improved performance'\n  'Over 10,000 companies use our platform'\n  'Reduces processing time by 3.5x'\nAI engines prefer citing specific data points over vague claims.",
                "tighten_first_para": "Tighten your opening paragraph to 25-120 words so AI engines can lift it as a snippet.",
                "frontload_facts": "Front-load facts into your first paragraph so AI engines can extract it directly:\n  'GEO is the practice of optimizing content for AI-powered search engines.\n   Over 70% of search users now consult an AI assistant before clicking a link.'\nAim for one definition-style sentence and one concrete stat in the first 25-120 words.",
                "add_opening_para": "Place a substantive opening paragraph high in the page body (inside <main> or <article>)\nthat answers 'what is this about?' with a definition and/or a concrete number.",
                "simplify": "Simplify your content for better AI readability:\n  1. Use shorter sentences (under 20 words)\n  2. Replace jargon with plain language\n  3. Break complex ideas into bullet points\n  4. Use active voice instead of passive\n  5. Target a grade 8-10 reading level"
              },
              "crawl_ready": {
                "add_alt_text": "Add descriptive alt text to all <img> tags:\n  <img src=\"photo.jpg\" alt=\"Description of what the image shows\" />\nGood alt text is specific: 'Team meeting in conference room' not 'image1'.",
                "add_alt_text_majority": "Most images are missing alt text. Add descriptive alt attributes to every <img>:\n  <img src=\"photo.jpg\" alt=\"Descriptive text about the image content\" />\nFor decorative images, use alt=\"\" (empty but present).",
                "add_internal_links": "Add more internal links to help AI crawlers discover your content.\nInclude links to key pages in your navigation, footer, and within content body.\nUse descriptive anchor text: 'Read our pricing guide' not 'click here'.",
                "add_internal_links_homepage": "Your homepage has very few internal links. AI crawlers use links to discover pages.\nAdd:\n  1. A navigation menu linking to key sections\n  2. Featured content links in the body\n  3. A footer with links to important pages\n  4. Contextual links within content",
                "add_semantic_html5": "Replace generic <div> containers with semantic HTML5 tags:\n  <header> for site header/nav\n  <main> for primary content\n  <article> for self-contained content\n  <section> for thematic groupings\n  <aside> for sidebar/related content\n  <footer> for footer",
                "critical_response_time": "Response time is critically slow. AI crawlers may time out.\nImmediate actions:\n  1. Add a CDN in front of your origin server\n  2. Enable page caching at the server level\n  3. Profile your server-side code for bottlenecks\n  4. Consider static site generation for content pages",
                "enable_ssr": "Enable server-side rendering in your framework:\n  Next.js: use getServerSideProps() or generateStaticParams()\n  Nuxt.js: set ssr: true in nuxt.config\n  React: consider migrating to Next.js or Remix",
                "improve_response_time": "Improve response time:\n  1. Enable server-side caching (Redis, Varnish, CDN)\n  2. Optimize database queries\n  3. Use a CDN (Cloudflare, Fastly, CloudFront)\n  4. Enable gzip/brotli compression",
                "paywall_workarounds": "AI crawlers cannot see content behind paywalls/login walls.\nConsider:\n  1. Providing a generous free preview or summary above the gate.\n  2. Using 'metered' access so bots see full content on first visit.\n  3. Adding structured data (JSON-LD) with key facts outside the gate.",
                "remove_noai": "The 'noai' / 'noimageai' directive opts your content out of AI training.\nRemove it if you want AI engines to include your content in their responses.",
                "remove_nofollow": "Remove 'nofollow' if you want AI crawlers to discover linked pages:\n  <meta name=\"robots\" content=\"index, follow\" />",
                "remove_noindex": "Remove 'noindex' from the meta robots tag if you want AI engines to index this page:\n  <meta name=\"robots\" content=\"index, follow\" />",
                "remove_xrobots": "Remove the restrictive X-Robots-Tag header from your server config.\nNginx: remove 'add_header X-Robots-Tag \"noindex\";'\nApache: remove 'Header set X-Robots-Tag \"noindex\"'",
                "replace_divs": "Your page uses only <div> tags. Replace them with semantic HTML5 elements:\n  <header>, <nav>, <main>, <article>, <section>, <aside>, <footer>\nThis helps AI engines understand the role of each content block."
              },
              "cross_platform": {
                "expand_presence": "Expand your brand presence on platforms that AI models train on: {platforms}\nAI engines (ChatGPT, Perplexity, Claude, Gemini) train on data from these platforms.\nBeing present increases the probability of your brand being cited in AI answers,\nregardless of which source the AI pulls from."
              },
              "https": {
                "enable_https": "Install an SSL/TLS certificate (free via Let's Encrypt) and redirect all HTTP traffic to HTTPS.\nExample nginx: return 301 https://$host$request_uri;"
              },
              "llms": {
                "add_description": "Add a paragraph below the title explaining what your site/org does:\n  # Your Site\n  A brief description of your site and what it offers.",
                "add_links": "Add markdown links to your key pages:\n  - [Documentation](https://yoursite.com/docs)\n  - [API Reference](https://yoursite.com/api)",
                "add_sections": "Organize your llms.txt with sections like:\n  ## Documentation\n  ## API Reference\n  ## Blog",
                "add_title": "Add a title as the first line of {filename}:\n  # Your Site Name",
                "create_file": "Create an llms.txt file at your site root. Example structure:\n  # Your Site Name\n  A brief description of your site.\n  \n  ## Documentation\n  > Overview of your docs\n  - [Getting Started](https://yoursite.com/docs/start)\n  \n  ## API\n  > API reference\n  - [API Docs](https://yoursite.com/api)",
                "create_full_file": "Create llms-full.txt with expanded content — a more detailed version of llms.txt\nwith full descriptions, complete resource listings, and deeper context for AI models.",
                "expand_content": "Expand the file with meaningful content about your site, its purpose, key pages, and resources."
              },
              "meta": {
                "add_canonical": "Add a canonical link in your <head>:\n  <link rel=\"canonical\" href=\"https://yoursite.com/current-page\" />\nThis tells AI engines which version of a page is the authoritative one.",
                "add_description": "Add a meta description in your <head>:\n  <meta name=\"description\" content=\"A 120-160 character summary of your page content, including key topics and value proposition.\">\nThis is often what AI engines use when summarizing your site.",
                "add_hreflang": "If your site is multilingual, add hreflang tags:\n  <link rel=\"alternate\" hreflang=\"en\" href=\"https://yoursite.com/en/page\" />\n  <link rel=\"alternate\" hreflang=\"es\" href=\"https://yoursite.com/es/page\" />\n  <link rel=\"alternate\" hreflang=\"x-default\" href=\"https://yoursite.com/page\" />",
                "add_lang": "Add a lang attribute to your <html> tag:\n  <html lang=\"en\">",
                "add_og": "Add Open Graph meta tags in your <head>:\n  <meta property=\"og:title\" content=\"Page Title\" />\n  <meta property=\"og:description\" content=\"Page description\" />\n  <meta property=\"og:type\" content=\"website\" />\n  <meta property=\"og:url\" content=\"https://yoursite.com/page\" />\n  <meta property=\"og:image\" content=\"https://yoursite.com/image.jpg\" />",
                "add_title": "Add a <title> tag in your <head>:\n  <title>Your Page Title — Your Brand</title>\nKeep it under 60 characters and include your primary keyword.",
                "expand_description": "Expand your meta description to 120-160 characters. Include a clear value proposition and primary keywords.",
                "add_twitter_cards": "Add Twitter Card meta tags in your <head>:\n  <meta name=\"twitter:card\" content=\"summary_large_image\" />\n  <meta name=\"twitter:title\" content=\"Page Title\" />\n  <meta name=\"twitter:description\" content=\"Page description\" />\n  <meta name=\"twitter:image\" content=\"https://yoursite.com/image.jpg\" />"
              },
              "mobile": {
                "add_cache_headers": "Add cache headers for efficient re-crawling:\n  Cache-Control: public, max-age=3600\n  ETag: (auto-generated by most servers)\nThis allows AI crawlers to use conditional requests (If-None-Match)\nand avoid re-downloading unchanged pages.",
                "add_viewport": "Add a viewport meta tag to your <head>:\n  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />\nMobile-first indexing means AI crawlers expect mobile-friendly pages.",
                "externalize_inline": "Move inline styles and scripts to external files to reduce HTML weight\nand improve caching for repeat crawls.",
                "reduce_weight": "Reduce page weight:\n  1. Move inline CSS to external stylesheets\n  2. Move inline JS to external scripts with defer/async\n  3. Remove unused HTML/comments\n  4. Enable server-side compression (gzip/brotli)",
                "reduce_weight_critical": "Page is too heavy for efficient crawling. Actions:\n  1. Externalize all inline CSS and JavaScript\n  2. Remove inline SVGs and base64 images — use external files\n  3. Enable gzip/brotli compression on your server\n  4. Consider code-splitting for JavaScript-heavy pages",
                "set_viewport_responsive": "Set viewport to responsive:\n  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />"
              },
              "multi_page": {
                "boost_google_authority": "Boost Google authority:\n  - Complete your Organization schema (all 9 fields)\n  - Create a Wikipedia article for your brand/product\n  - Create a Wikidata entity and link it in sameAs\n  - Claim your Google Business Profile\n  - Build high-quality backlinks from authoritative domains",
                "common_crawl_inbound_links": "Your site hasn't been crawled by Common Crawl yet.\nThis is normal for newer/smaller sites. Build inbound links to increase discovery.",
                "duplicate_descriptions": "Write unique meta descriptions for each page. Duplicate descriptions\nconfuse AI engines about which page to cite for a given topic.",
                "duplicate_titles": "Write unique <title> tags for each page. Identical titles cause keyword\ncannibalization — AI engines can't tell which page to cite for a given query.",
                "content_overlap": "Two or more pages cover the same topic with highly overlapping content.\nOptions:\n  1. Consolidate into one canonical page and 301-redirect the others.\n  2. Differentiate each page with distinct angles, examples, and keywords.\n  3. Use rel=canonical to point near-duplicates to the primary page.\nCannibalization dilutes your AI visibility — pick the strongest page to surface.",
                "increase_platform_presence": "Increase your presence on authoritative platforms:\n  - Create a Crunchbase profile for your company\n  - Maintain an active GitHub organization\n  - Publish packages on npm/PyPI if applicable\n  - Get mentioned on Hacker News (Show HN posts)\n  - Submit to startup directories (Product Hunt, AngelList/Wellfound)\n  - Seek mentions in industry publications and comparison lists",
                "list_review_platforms": "List your product on review platforms to build trust signals:\n  - Trustpilot (https://business.trustpilot.com) — general reviews\n  - G2 (https://sell.g2.com) — B2B/SaaS reviews\n  - Product Hunt (https://producthunt.com) — launch & discovery\n  - Capterra (https://capterra.com) — software reviews\nAdd AggregateRating schema to your site to display star ratings in search.",
                "low_word_count": "Pages with <100 words have too little content for AI engines. Add substantive, unique text.",
                "missing_alt_text": "Add descriptive alt text to all images on these pages.",
                "missing_canonical": "Add <link rel=\"canonical\" href=\"...\"> to each page pointing to its preferred URL.",
                "missing_description": "Add a unique meta description to each page (120-160 chars) summarizing the page content.",
                "missing_h1": "Add a single <h1> tag to each page describing its primary topic.",
                "missing_og": "Add Open Graph tags (og:title, og:description, og:image) to each page.",
                "missing_structured_data": "Add JSON-LD structured data to content pages (Article, Product, FAQPage, etc.).",
                "missing_title": "Add a unique, descriptive <title> tag to each page (under 60 chars).",
                "register_search_engines": "Register with Google Search Console and Bing Webmaster Tools to get indexed.\nSubmit your sitemap.xml to each platform.\nEnsure robots.txt does not block AI crawlers.\nCheck your CDN/WAF settings — some block bot traffic by default.",
                "strengthen_trust": "Strengthen trust signals:\n  - Display certifications prominently (SOC2, GDPR, ISO, PCI-DSS)\n  - Add award badges with alt text: <img alt='2025 Best Fintech Award' ...>\n  - Add partner/affiliation logos (Y Combinator, accelerators, industry groups)\n  - Use structured data for awards:\n    {\"@type\": \"Organization\", \"award\": [\"Best Fintech 2025\", ...]}",
                "unblock_core_bots": "These are core AI crawlers. If missing, your content may not appear in their AI products.\nEnsure you are registered with the corresponding search platforms.\nCheck that robots.txt does not block these user agents.\nSubmit your sitemap to Google Search Console and Bing Webmaster Tools.",
                "unblock_robots_bots": "The following bots are blocked by robots.txt: {bots}\nIf you want AI engines to index your content, remove or modify these rules:\n  User-agent: BotName\n  Disallow: /\nChange 'Disallow: /' to 'Allow: /' or remove the block entirely.",
                "unblock_waf_bots": "Some AI bots are being blocked by your server, CDN, or WAF.\nCheck your Cloudflare/AWS WAF/Nginx rules and whitelist these user agents.\nCommon causes:\n  - Cloudflare Bot Fight Mode blocking non-browser user agents\n  - Rate limiting rules that are too aggressive\n  - Security plugins (Wordfence, Sucuri) with strict bot blocking"
              },
              "multilingual": {
                "expand_alt_pages": "Alternate language pages have too little content. Ensure translations are complete\nand not just stubs or machine-translated snippets. AI engines may skip thin multilingual pages.",
                "fix_hreflang": "Fix broken hreflang URLs — they return errors. Either create the page\nor remove the hreflang tag to avoid confusing AI crawlers."
              },
              "brand_kg": {
                "create_wikipedia": "A Wikipedia page is one of the strongest entity signals for AI engines. If you're\nnotable enough, seek independent coverage in news/trade press and follow Wikipedia's\nnotability guidelines. Do not write your own page — it will be flagged as COI.",
                "create_wikidata": "Wikidata is free to edit and AI engines (especially Google Knowledge Graph) ingest it\nheavily. Create an entry at https://www.wikidata.org/wiki/Special:NewItem with:\n  • Label + description\n  • instance of (P31) — e.g. 'business'\n  • official website (P856) — your domain\n  • sameAs links to social profiles"
              },
              "trust_safety": {
                "add_privacy": "Publish a Privacy Policy at /privacy (or /privacy-policy). AI engines treat missing\nprivacy policies as a trust red flag — required by GDPR, CCPA, and most ad networks.",
                "add_terms": "Publish Terms of Service at /terms. This is a basic trust signal AI engines\nand search platforms expect from legitimate sites.",
                "add_contact": "Add a /contact page with at least an email address and/or form. AI engines rank\nsites with clear contact paths higher for trust-sensitive queries.",
                "add_legal": "Add a /dmca or /legal page. In the EU an 'Impressum' (imprint) is legally required;\nelsewhere a DMCA agent page protects you from copyright liability and boosts trust.",
                "add_identity_signals": "Add missing trust signals so AI engines can verify who is behind the site.",
                "add_business_identity": "AI engines cannot verify who runs this site. Add in the footer and/or Organization JSON-LD:\n  • Physical address (schema.org PostalAddress)\n  • Contact email and telephone (contactPoint)\n  • Legal entity suffix (LLC / Inc / Ltd / GmbH) and registration number where applicable"
              },
              "outbound": {
                "add_authoritative_links": "Link to authoritative external sources where relevant (research papers, .gov/.edu sites,\nindustry standards). Outbound links to reputable sources signal well-researched content to AI engines.",
                "add_dfn_abbr": "Mark up key terms and abbreviations:\n  <dfn>Generative Engine Optimization</dfn> (GEO) is...\n  <abbr title=\"Generative Engine Optimization\">GEO</abbr>\nThis helps AI engines understand and define terms in your content.",
                "add_outbound_links": "Add outbound links to reputable, authoritative sources that support your claims.\nAI engines see this as a signal of well-researched, trustworthy content.",
                "add_table_headers_semantic": "Add semantic headers to your tables for AI extraction:\n  <table>\n    <thead><tr><th>Header 1</th><th>Header 2</th></tr></thead>\n    <tbody>...</tbody>\n  </table>",
                "add_table_thead": "Add <thead> and <th> to all data tables:\n  <table>\n    <thead><tr><th>Column 1</th><th>Column 2</th></tr></thead>\n    <tbody><tr><td>Data</td><td>Data</td></tr></tbody>\n  </table>",
                "add_video_schema": "Add VideoObject structured data for your video content:\n  <script type=\"application/ld+json\">\n  {\n    \"@context\": \"https://schema.org\",\n    \"@type\": \"VideoObject\",\n    \"name\": \"Video Title\",\n    \"description\": \"Video description\",\n    \"thumbnailUrl\": \"https://yoursite.com/thumb.jpg\",\n    \"uploadDate\": \"2025-01-15\",\n    \"contentUrl\": \"https://yoursite.com/video.mp4\"\n  }\n  </script>",
                "add_video_transcripts": "Add text transcripts for video content so AI crawlers can index the spoken content.\nPlace the transcript in a visible section below the video.",
                "diversify_formats": "Diversify your content formats so AI engines encounter you in more contexts:\n  • Podcast (audio transcripts feed ChatGPT, Perplexity)\n  • PDF whitepapers (citable documents)\n  • Infographics with descriptive alt text\n  • Slides on SlideShare / Speaker Deck\n  • Video with transcripts",
                "add_alt_format": "Add at least one alternative format (video with transcript, podcast, PDF, or infographic).\nEach format opens a new retrieval channel for AI engines."
              },
              "robots": {
                "add_sitemap_directive": "Add a Sitemap directive to your robots.txt:\n  Sitemap: https://yoursite.com/sitemap.xml",
                "create": "Create a robots.txt file at the root of your site.\nMinimal example:\n  User-agent: *\n  Allow: /\n  Sitemap: https://yoursite.com/sitemap.xml",
                "unblock_bots": "To allow these AI bots, remove or modify their Disallow directives in robots.txt.\nExample to allow GPTBot:\n  User-agent: GPTBot\n  Allow: /",
                "unblock_wildcard": "Change 'Disallow: /' under 'User-agent: *' to 'Allow: /' if you want AI crawlers to index your site.\nYou can selectively block specific bots while allowing others.",
                "add_ai_txt": "Consider an ai.txt file at your site root (spec: spawning.ai/ai-txt) to declare\na strategic policy separate from robots.txt."
              },
              "schema_kb": {
                "add_breadcrumb_schema": "Add BreadcrumbList structured data to match your HTML breadcrumbs:\n  <script type=\"application/ld+json\">\n  {\n    \"@context\": \"https://schema.org\",\n    \"@type\": \"BreadcrumbList\",\n    \"itemListElement\": [\n      {\"@type\": \"ListItem\", \"position\": 1, \"name\": \"Home\", \"item\": \"https://yoursite.com\"},\n      {\"@type\": \"ListItem\", \"position\": 2, \"name\": \"Products\", \"item\": \"https://yoursite.com/products\"}\n    ]\n  }\n  </script>",
                "add_breadcrumbs": "Add breadcrumb navigation to help AI engines understand your site structure:\n  1. Add visible breadcrumbs: Home > Category > Page\n  2. Add BreadcrumbList JSON-LD schema to match",
                "add_org_field": "Add \"{field}\" to your Organization JSON-LD to improve knowledge panel eligibility.",
                "add_org_fields": "Add more fields to strengthen knowledge panel eligibility:\n  \"address\": {\"@type\": \"PostalAddress\", \"streetAddress\": \"...\", \"addressLocality\": \"...\"},\n  \"telephone\": \"+1-xxx-xxx-xxxx\",\n  \"foundingDate\": \"2020\",\n  \"sameAs\": [\"https://twitter.com/...\", \"https://linkedin.com/...\"]",
                "add_organization": "Add Organization structured data for knowledge panel eligibility:\n  <script type=\"application/ld+json\">\n  {\n    \"@context\": \"https://schema.org\",\n    \"@type\": \"Organization\",\n    \"name\": \"Your Company\",\n    \"url\": \"https://yoursite.com\",\n    \"logo\": \"https://yoursite.com/logo.png\",\n    \"description\": \"What your company does\",\n    \"sameAs\": [\"https://twitter.com/you\", \"https://linkedin.com/company/you\"]\n  }\n  </script>"
              },
              "search_reg": {
                "bing_webmaster": "Register your site with Bing Webmaster Tools (https://www.bing.com/webmasters):\n  1. Add your site and verify ownership\n  2. Submit your sitemap.xml\n  3. This is essential — Bing's index powers Microsoft Copilot, ChatGPT (via Bing search),\n     and other AI assistants that use Bing as their search backend.",
                "google_console": "Register your site with Google Search Console (https://search.google.com/search-console):\n  1. Add your property (URL prefix or domain)\n  2. Verify ownership via meta tag, DNS, or HTML file\n  3. Submit your sitemap.xml under Sitemaps\n  4. Monitor indexing status and fix any crawl errors\nThis is critical — Google's AI Overviews and SGE pull from the Google index.",
                "indexnow": "Set up IndexNow for instant indexing by Bing, Yandex, and others:\n  1. Generate an API key at https://www.indexnow.org/\n  2. Host the key file at your site root: https://yoursite.com/{key}.txt\n  3. Notify search engines when content changes:\n     POST https://api.indexnow.org/indexnow\n     {\"host\": \"yoursite.com\", \"key\": \"your-key\", \"urlList\": [\"https://yoursite.com/updated-page\"]}\n  4. Many CMS plugins (WordPress, etc.) support IndexNow automatically.",
                "submit_all": "Having files like sitemap.xml and robots.txt is not enough on its own.\nYou must also register and submit them to each platform:\n  \n  Google Search Console → Submit sitemap → Powers Google AI Overviews / SGE\n  Bing Webmaster Tools  → Submit sitemap → Powers Copilot, ChatGPT (Bing backend)\n  IndexNow              → Auto-notify   → Instant indexing for Bing, Yandex, Naver\n  \nWithout registration, search engines may find your sitemap eventually via crawling,\nbut submission ensures faster, more reliable indexing."
              },
              "sitemap": {
                "add_lastmod": "Add <lastmod> to each <url> entry in your sitemap:\n  <url>\n    <loc>https://yoursite.com/page</loc>\n    <lastmod>2025-01-15</lastmod>\n  </url>",
                "create_file": "Create a sitemap.xml at your site root. Example:\n  <?xml version=\"1.0\" encoding=\"UTF-8\"?>\n  <urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">\n    <url>\n      <loc>https://yoursite.com/</loc>\n      <lastmod>2025-01-15</lastmod>\n    </url>\n  </urlset>\nMost CMS platforms (WordPress, Next.js, etc.) can auto-generate sitemaps."
              },
              "social": {
                "add_sameas": "Add sameAs to your Organization JSON-LD to connect your social profiles:\n  \"sameAs\": [\n    \"https://twitter.com/yourbrand\",\n    \"https://linkedin.com/company/yourbrand\",\n    \"https://github.com/yourbrand\",\n    \"https://facebook.com/yourbrand\"\n  ]\nThis helps AI engines confirm your entity identity across platforms.",
                "add_twitter_card": "Add Twitter card tags to your <head>:\n  <meta name=\"twitter:card\" content=\"summary_large_image\" />\n  <meta name=\"twitter:site\" content=\"@yourhandle\" />\n  <meta name=\"twitter:title\" content=\"Page Title\" />\n  <meta name=\"twitter:description\" content=\"Page description\" />\n  <meta name=\"twitter:image\" content=\"https://yoursite.com/image.jpg\" />"
              },
              "structured": {
                "add_product_reviews": "Add review and aggregateRating to your Product schema:\n  \"aggregateRating\": {\"@type\": \"AggregateRating\", \"ratingValue\": \"4.6\", \"reviewCount\": \"128\"},\n  \"review\": [{\"@type\": \"Review\", \"author\": ..., \"reviewRating\": ...}]",
                "upgrade_to_granular": "Upgrade from generic WebPage/CreativeWork to specific types:\n  • How-to content → HowTo with step list\n  • Q&A pages → FAQPage with Question/Answer pairs\n  • Products → Product with offers + aggregateRating\n  • Articles → NewsArticle or BlogPosting\nGranular types give AI engines far more extractable facts than WebPage.",
                "add_organization_jsonld": "Add JSON-LD structured data to your <head>. Example for an Organization:\n  <script type=\"application/ld+json\">\n  {\n    \"@context\": \"https://schema.org\",\n    \"@type\": \"Organization\",\n    \"name\": \"Your Company\",\n    \"url\": \"https://yoursite.com\",\n    \"description\": \"What your company does\"\n  }\n  </script>\nUse Google's Rich Results Test to validate: https://search.google.com/test/rich-results"
              },
              "tech_crawl": {
                "add_rss_feed": "Add an RSS or Atom feed for your content and link to it in <head>:\n  <link rel=\"alternate\" type=\"application/rss+xml\" title=\"RSS\" href=\"/feed.xml\" />\nMost CMS platforms generate feeds automatically. For static sites, tools like eleventy-rss can help.",
                "broken_canonical": "The canonical URL {canonical_url} is broken. Either fix the target page or update the canonical to a working URL.",
                "enable_http2": "Enable HTTP/2 on your server for faster crawling:\n  Nginx: listen 443 ssl http2;\n  Apache: Protocols h2 http/1.1\n  Or use a CDN like Cloudflare which enables HTTP/2 automatically.",
                "fix_canonical_chain": "Fix the canonical chain — each page's canonical should point directly to the final URL, not through intermediaries.\nSet the canonical on each page to its own URL or the ultimate target.",
                "reduce_redirects": "Reduce the redirect chain to a single hop (A -> B, not A -> B -> C -> D).\nUpdate your server config to redirect directly to the final destination URL.",
                "feed_full_content": "Publish full content in your feed rather than excerpts. AI agents that consume feeds\nprogrammatically prefer complete text they can extract without following every link.",
                "feed_expand_content": "Your feed publishes only headlines/snippets. Switch to full content so AI agents\nand aggregators can index the actual article without scraping the HTML page.",
                "add_api_docs": "Publish machine-readable data feeds and integration docs so AI agents can consume\nyour data programmatically (e.g. /openapi.json, /api/v1, /developers)."
              },
              "url_norm": {
                "lowercase_url": "Ensure your server normalizes URL case (lowercase). In nginx:\n  location ~ [A-Z] { rewrite ^(.*)$ $scheme://$host$uri_lowercase permanent; }",
                "www_redirect": "Set up a 301 redirect so one version redirects to the other:\n  # Nginx: redirect www to non-www\n  server {{ server_name www.{host}; return 301 https://{host}$request_uri; }}\nThen set the canonical URL to match the preferred version."
              },
              "well_known": {
                "add_security_txt": "Consider adding .well-known/security.txt (RFC 9116) as a trust signal:\n  Contact: mailto:security@yoursite.com\n  Preferred-Languages: en\n  Canonical: https://yoursite.com/.well-known/security.txt",
                "fix_invalid_json": "Validate and fix the JSON in {path} — use a JSON linter to check for syntax errors."
              }
            },
            "scoreCard": {
              "title": "AI Visibility Score",
              "description": "How well your website is optimized for AI search",
              "grade": "Grade"
            },
            "summary": {
              "passed": "Passed",
              "warnings": "Warnings",
              "failed": "Failed",
              "info": "Info",
              "totalChecks": "Total Checks",
              "overview": "Overview",
              "allPassed": "All Passed"
            },
            "detailedResults": "Detailed Results",
            "fix": "Fix:",
            "buttons": {
              "checkAnother": "Check Another Website",
              "getHelp": "Get Optimization Help"
            },
            "error": {
              "noData": "No GEO check data found. Please run a check first."
            },
            "loginToView": "Login to View Full Results",
            "loginToViewDesc": "Log in to see all detailed results and recommendations",
            "loginButton": "Log In",
            "paywall": {
              "lockedCount": "{{count}} more checks locked",
              "subtitle": "Activate a membership to unlock every check and detailed fix recommendation.",
              "viewAll": "View all →",
              "perCategoryHint": "View 2 of {{total}} checks (membership unlocks all)",
              "unlockCategory": "Upgrade to unlock this category →",
              "memberOnly": "This category requires a membership",
              "upgradePro": "Subscribe"
            },
            "upgradeHint": {
              "fixPrompt": "Upgrade to get fix recommendations →"
            },
            "groupProgress": {
              "title": "Category Progress"
            },
            "categories": {
              "infraProtocols": "Protocols & Crawlability",
              "pageBasics": "Page Basics & Mobile",
              "aiProtocols": "AI-Specific Protocols",
              "structuredSemantic": "Structured & Semantic Data",
              "contentQuality": "Content Quality & Readability",
              "techRobustness": "Technical Robustness & Media",
              "authorityExternal": "Authority & External Signals",
              "other": "Other"
            },
            "categoryLabels": {
              "HTTPS": "HTTPS",
              "robots.txt": "robots.txt",
              "llms.txt": "llms.txt",
              ".well-known Discovery": ".well-known Discovery",
              "sitemap.xml": "Sitemap (sitemap.xml)",
              "Search Engine & AI Platform Registration": "Search Engine & AI Platform Registration",
              "Structured Data": "Structured Data (JSON-LD)",
              "Meta Tags": "Meta Tags",
              "Content Accessibility": "Content Accessibility",
              "AI Crawl Readiness": "AI Crawl Readiness",
              "Content Quality for AI": "Content Quality for AI",
              "Technical Crawlability": "Technical Crawlability",
              "Authority & Trust Signals": "Authority & Trust Signals",
              "AI-Specific Optimization": "AI-Specific Optimization",
              "Social Signals": "Social Signals",
              "AI Answer Format Optimization": "AI Answer Format Optimization",
              "Schema Breadcrumbs & Knowledge Panel": "Schema Breadcrumbs & Knowledge Panel",
              "Mobile-Friendliness & Page Weight": "Mobile-Friendliness & Page Weight",
              "URL Normalization": "URL Normalization",
              "Outbound Links & Media": "Outbound Links & Media",
              "Multilingual Content Depth": "Multilingual Content Depth",
              "Cross-Platform Content Distribution": "Cross-Platform Content Distribution",
              "Multi-Page Sampling": "Multi-Page Sampling",
              "Brand Entity KG": "Brand Entity & Knowledge Graph",
              "Trust & Safety": "Trust & Safety Signals"
            },
            "header": {
              "rerunPlaceholder": "Enter a URL to re-run the check",
              "rerun": "Re-run check",
              "modeLabel": "Detection mode",
              "modeDefault": "Standard check",
              "modeLockedHint": "Upgrade your plan to unlock this mode",
              "placeholderCompare": "https://a.com, https://b.com, https://c.com",
              "placeholderKeywords": "Keywords (optional, comma-separated)",
              "placeholderEntity": "Brand / product / person name",
              "entityTypeLabel": "Entity type",
              "entityType": {
                "brand": "Brand",
                "product": "Product",
                "person": "Person"
              },
              "compareHint": "Separate 2-5 URLs with commas or spaces",
              "visibilityHint": "Leave keywords blank to auto-generate; separate multiple with commas",
              "entityHint": "Enter the brand, product or person you want to audit"
            },
            "visuals": {
              "robots": {
                "title": "AI Crawler Permissions",
                "filePresent": "robots.txt · file present",
                "fileMissing": "robots.txt · file missing",
                "sitemapRef": "sitemap ref ✓",
                "noSitemapRef": "no sitemap ref",
                "wildcardWarning": "Wildcard rule User-agent: * blocks every crawler. Bots shown as \"inherit\" below are effectively blocked until you override them.",
                "legend": {
                  "allowed": "Allowed",
                  "blocked": "Blocked",
                  "inherited": "Inherits wildcard",
                  "unknown": "Unknown"
                }
              },
              "meta": {
                "title": "Meta Tag Coverage",
                "subtitle": "6 signals AI engines rely on for summaries",
                "passCount": "{{pass}}/{{total}} pass",
                "items": {
                  "title": { "help": "Page title tag" },
                  "description": { "help": "Meta description" },
                  "canonical": { "help": "Canonical URL" },
                  "og": { "help": "og:* tags for social and AI summaries" },
                  "lang": { "help": "Language declaration" },
                  "hreflang": { "help": "Multilingual alternate versions" }
                }
              },
              "platform": {
                "titleCross": "Cross-Platform Presence",
                "titleSocial": "Social Signal Coverage",
                "subtitle": "Platforms AI engines train on",
                "notDetected": "{{name}} not detected"
              }
            },
            "fixPackage": {
              "download": "Fix Package",
              "downloading": "Generating...",
              "title": "Download Fix Package",
              "upgradeRequired": "This feature requires a starter or higher membership.",
              "error": "Failed to download fix package"
            },
            "shareExport": {
              "title": "Share & Export",
              "copied": "Link copied to clipboard!",
              "copyLink": "Copy Link",
              "exportPDF": "Export PDF",
              "exportPDFLoading": "Exporting PDF...",
              "exportCSV": "Export CSV",
              "shareSocial": "Share to social media",
              "share": "Share",
              "downloadReport": "Download Report",
              "downloadReportLoading": "Generating report…"
            },
            "pdfReport": {
              "title": "GEO Readiness Report",
              "subtitle": "How ready your site is for AI-powered search engines",
              "targetSite": "Target Site",
              "generatedAt": "Generated At",
              "tier": "Report Tier",
              "overallScore": "Overall Score",
              "scoreInterpretation": "Score Interpretation",
              "scoreLevels": {
                "excellent": "Excellent — your site is well-optimized for AI search engines. Keep monitoring and fine-tuning.",
                "good": "Good — most fundamentals are in place. A few targeted fixes will lift you into the top tier.",
                "average": "Average — several important signals are missing. Prioritize the fixes below to improve visibility.",
                "poor": "Needs work — AI engines are likely underrepresenting your content. Address the failed checks soon.",
                "critical": "Critical — your site is largely invisible to AI engines. A full optimization pass is strongly recommended."
              },
              "groupSection": "Category Breakdown",
              "groupLabel": "Category",
              "recommendationsSection": "Priority Recommendations",
              "topFixesIntro": "The highest-impact issues, sorted by severity. Fixing these first yields the biggest score gains.",
              "detailSection": "Detailed Findings",
              "appendixSection": "About This Report",
              "appendixBody": "Generated by GEO Checker. Scores reflect how well your site follows best practices for AI-powered search engines like ChatGPT, Perplexity, Google AI Overviews, and Copilot. Re-run after making changes to see your progress.",
              "footer": "GEO Checker · © {{year}} · All rights reserved",
              "fileName": "geo-readiness-report",
              "fixLabel": "Fix",
              "noFix": "No specific fix required.",
              "noFailItems": "No failed or warning items found. Great work!",
              "lockedNotice": "{{count}} category group(s) are locked in this tier. Upgrade to unlock full results.",
              "statusLabels": {
                "pass": "Pass",
                "warn": "Warn",
                "fail": "Fail",
                "info": "Info"
              },
              "tierLabels": {
                "free": "Free",
                "pro": "Detector",
                "starter": "Starter",
                "growth": "Growth",
                "scale": "Scale"
              },
              "pageOf": "Page {{current}} / {{total}}",
              "coverBadge": "GEO READINESS REPORT",
              "headerSite": "Report for"
            }
          },
} as const;

export default enResult;
