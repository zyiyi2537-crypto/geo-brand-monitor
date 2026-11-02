const enKnowledge = {
"geoKnowledge": {
            "title": "Resources Center",
            "description": "Master GEO + AEO: The Smart Way to Win Visibility and Recommendations from AI Search Engines",
            "sections": {
              "about": "Understand GEO & AEO",
              "whatIsGeo": "What are GEO & AEO?",
              "whatIsGeoBody": "GEO (Generative Engine Optimization) and AEO (Answer Engine Optimization) are optimization practices designed for AI search engines and AI assistants (ChatGPT, Perplexity, Google AI Overviews, Gemini, Claude, Copilot, etc.). GEO focuses on making your brand visible and citable by AI engines. AEO takes it further — optimizing your content so AI not only finds you but directly understands, trusts, and selects your brand as the best answer to user questions. While traditional SEO optimizes for blue links on search result pages, GEO + AEO optimizes the actual answers AI generates.",
              "whyGeoImportant": "Why GEO + AEO Matter",
              "whyGeoPoints": [
                "Traditional search traffic is being replaced by AI-generated answers — if you're not in the answer, you're completely invisible.",
                "AI engines cite only a very small number of trusted sources per query — getting into that list locks in category authority.",
                "Once AI models recognize you as a brand entity, they repeatedly recommend you across countless related queries, creating compounding effects.",
                "Early adopters of GEO + AEO can secure category leadership before competitors catch up."
              ],
              "strategies": "GEO Strategies",
              "contentLocalization": "Authoritative Content & Entity Clarity",
              "contentLocalizationDesc": "AI engines cite sources they can verify. Build comprehensive first-party content about your brand, products and category with clear entity signals that large language models can parse and trust.",
              "contentLocalizationPoints": [
                "Publish in-depth, expert-grade content on your core topics — avoid thin marketing copy",
                "Add Organization / Product structured data (JSON-LD) and an llms.txt file",
                "Establish brand presence on Wikipedia, Wikidata, Reddit, GitHub and authoritative directories"
              ],
              "technicalOptimization": "Technical Foundations & AI Crawlability",
              "technicalOptimizationDesc": "If AI crawlers cannot reach your content, they cannot cite you. Make sure GPTBot, ClaudeBot, PerplexityBot and Google-Extended can actually fetch and render your pages.",
              "technicalOptimizationPoints": [
                "Allow AI crawlers in robots.txt (GPTBot, ClaudeBot, PerplexityBot, Google-Extended)",
                "Serve fast, server-rendered HTML — avoid JS-only pages that AI bots cannot execute",
                "Use semantic HTML and clean markup so LLMs can parse your pages into structured facts"
              ],
              "keyData": "Key GEO Metrics",
              "importantMetrics": "What to measure",
              "regionalTraffic": "AI Citation Rate",
              "regionalTrafficDesc": "How often your site is linked as a source when AI engines answer brand- or category-relevant queries.",
              "languagePreference": "Answer Inclusion Rate",
              "languagePreferenceDesc": "The share of relevant queries where your brand is actually named in the AI-generated answer, with or without a direct citation link.",
              "searchTrends": "Competitor Share of Voice",
              "searchTrendsDesc": "Which competitors AI models name alongside you and how often — the real benchmark for category mindshare."
            },
            "tabs": {
              "overview": "Overview",
              "metrics": "Metrics Glossary"
            },
            "metrics": {
              "title": "GEO Metrics Glossary",
              "description": "Every check in the GEO Readiness report, explained plainly: what it measures, why it matters for AI visibility, and how to improve it.",
              "field": {
                "measures": "What it measures",
                "why": "Why it matters",
                "scoring": "Scoring logic"
              },
              "categories": {
                "crawlability": {
                  "title": "1. Basic Crawlability",
                  "description": "The baseline signals that decide whether AI crawlers can reach and index your pages at all. If these fail, nothing else matters.",
                  "items": {
                    "https": {
                      "name": "HTTPS",
                      "measures": "Checks whether your site is served over HTTPS and the TLS certificate is valid.",
                      "why": "AI engine crawlers (OpenAI GPTBot, Anthropic ClaudeBot, Perplexity, Google-Extended) skip non-HTTPS sites. Plain HTTP pages are downranked or ignored outright during both training and real-time retrieval.",
                      "scoring": "HTTPS with a valid certificate → PASS. HTTP that redirects to HTTPS is acceptable. Plain HTTP or an expired certificate → FAIL."
                    },
                    "robots": {
                      "name": "robots.txt crawler rules",
                      "measures": "Checks whether robots.txt exists, parses cleanly, and explicitly allows the major AI crawlers (GPTBot, ClaudeBot, PerplexityBot, Google-Extended, CCBot).",
                      "why": "AI crawlers honor robots.txt by default. A single Disallow: / or a User-agent: GPTBot block makes you invisible to OpenAI — the equivalent of voluntarily disappearing from the AI view of the web.",
                      "scoring": "File present and all major AI crawlers allowed → PASS. Blocking one or two minor crawlers → WARN. Blocking any of GPTBot, ClaudeBot, or CCBot → FAIL."
                    },
                    "sitemap": {
                      "name": "sitemap.xml",
                      "measures": "Checks whether sitemap.xml exists, is well-formed, contains a healthy number of URLs, and is referenced from robots.txt.",
                      "why": "AI crawlers discover pages through the sitemap rather than link-walking from the homepage. Without one, a crawler may grab only your index page and leave — your deep content stays invisible to LLMs.",
                      "scoring": "File present and URL count looks right → PASS. Present but very small or malformed → WARN. Missing → FAIL."
                    },
                    "llms": {
                      "name": "llms.txt",
                      "measures": "Checks whether llms.txt exists at the site root. This is a 2024 proposal — a Markdown file that tells LLMs what your site is and where its canonical content lives.",
                      "why": "llms.txt gives AI crawlers a curated tour instead of forcing them to guess which pages matter. Anthropic, Perplexity and others have started to support or reference the format, and early movers own the slot.",
                      "scoring": "File present → PASS. Missing → INFO (not yet mandatory, but cheap to add and first-mover advantage is real)."
                    },
                    "aiCrawlerAccess": {
                      "name": "AI crawler live accessibility",
                      "measures": "Sends real HTTP requests using GPTBot, ClaudeBot, PerplexityBot and other user-agents to see whether your WAF, Cloudflare Bot Fight, or CAPTCHA challenges block them.",
                      "why": "Allowing a bot in robots.txt is only half the story — Cloudflare Bot Fight or AWS WAF rules often block every non-browser user-agent as malicious, trapping legitimate AI crawlers with the rest. Robots policy and edge policy must agree.",
                      "scoring": "All AI user-agents return 200 → PASS. Some blocked → WARN. All blocked → FAIL."
                    }
                  }
                },
                "structuredData": {
                  "title": "2. Structured Data",
                  "description": "Machine-readable signals that let large language models verify what you are, what you sell, and how the page is organized — without guessing from prose.",
                  "items": {
                    "jsonld": {
                      "name": "JSON-LD Schema Markup",
                      "measures": "Checks for JSON-LD blocks on the homepage and whether they describe an Organization, Product, WebSite, or similar schema.org type, with the key fields filled in.",
                      "why": "Structured data is the most machine-readable signal you can give an LLM. ChatGPT, Perplexity, and Google AI Overviews all rely on schema.org markup to verify entity identity and extract facts — without it you force models to infer everything from prose, which is error-prone and gets hedged.",
                      "scoring": "Organization + one of {Product, WebSite, FAQ} blocks present with core fields → PASS. A single thin block → WARN. No JSON-LD → FAIL."
                    },
                    "metaTags": {
                      "name": "Meta Tag Coverage",
                      "measures": "Checks the homepage for title, meta description, canonical, viewport, Open Graph (og:title / og:description / og:image), and Twitter card tags.",
                      "why": "Meta tags are the 2-line summary AI uses when deciding whether a page is relevant. A missing description forces models to generate one themselves — or skip the page entirely. og:image is what AI-powered link previews render in chat answers.",
                      "scoring": "All 6 core signals present → PASS. 4–5 present → WARN. Fewer than 4 → FAIL."
                    },
                    "breadcrumbs": {
                      "name": "Breadcrumbs & Knowledge Panel Markup",
                      "measures": "Looks for BreadcrumbList JSON-LD, visible breadcrumb navigation, and knowledge-panel-friendly markup such as `sameAs`, `logo`, and `SearchAction`.",
                      "why": "Breadcrumbs help AI models understand your site hierarchy — where a page sits inside the category tree. Knowledge panel markup is what Google and Perplexity use to construct the summary box next to a query. Both compound over time.",
                      "scoring": "Both signals present → PASS. One present → WARN. Neither → FAIL."
                    },
                    "answerFormat": {
                      "name": "AI Answer Format Optimization",
                      "measures": "Checks whether content is written in a format LLMs can quote cleanly — FAQ schema, Q&A patterns, definition-style opening paragraphs, short direct answers.",
                      "why": "LLMs prefer to cite sources that give them a quotable, self-contained sentence. `\"X is a [category] that [value prop]\"` is vastly more citable than a marketing paragraph burying the answer. FAQ schema explicitly flags Q&A pairs for extraction.",
                      "scoring": "FAQ schema + clear definition openings → PASS. Partial → WARN. No quotable structure → FAIL."
                    }
                  }
                },
                "authority": {
                  "title": "3. Authority Signals",
                  "description": "The off-page evidence LLMs rely on to decide whether you are a real entity worth recommending — presence in training corpora, encyclopedias, review platforms, and the press.",
                  "items": {
                    "commonCrawl": {
                      "name": "AI Training Data Indexing (Common Crawl)",
                      "measures": "Looks up your domain in the latest Common Crawl index snapshot and counts how many of your pages have been captured into this public web corpus.",
                      "why": "Common Crawl is training data for ChatGPT, Claude, LLaMA and almost every open LLM. If you are not in Common Crawl, these models never saw you during training — they have zero memory of your brand when users ask and will hedge or omit you entirely.",
                      "scoring": "Pages found → PASS. Not found but domain is under 60 days old → INFO (normal for new sites). Not found on an older site → WARN. Not found and CCBot is blocked in robots.txt → FAIL."
                    },
                    "wikipedia": {
                      "name": "Wikipedia / Wikidata Entity",
                      "measures": "Checks whether your brand or product has an entry on Wikipedia (English and/or Chinese) and a Wikidata Q-item.",
                      "why": "Wikipedia and Wikidata are the single most authoritative structured sources LLMs use to verify entities. If ChatGPT can look you up on Wikidata, it treats you as a real entity; if not, you get the `I'm not sure about this brand` hedge that kills recommendations.",
                      "scoring": "Wikipedia article + Wikidata Q-item → PASS. One of the two → WARN. Neither → FAIL."
                    },
                    "knowledgeGraph": {
                      "name": "Google Knowledge Graph Presence",
                      "measures": "Checks for a Google Knowledge Graph entity — the sidebar box that shows up in Google results for recognized brands — via schema.org markup and Google's Knowledge Graph API.",
                      "why": "Google's Knowledge Graph feeds directly into Google AI Overviews, SGE, and Gemini. An entity that is in the graph gets cited; one that is not, does not. It also seeds the brand fact table for every other LLM that crawls Google results as a reference.",
                      "scoring": "Entity found with rich fields → PASS. Partial coverage → WARN. Not found → FAIL."
                    },
                    "reviews": {
                      "name": "Third-party Reviews & Ratings",
                      "measures": "Checks for a brand presence on the review platforms that matter in your category — G2, Capterra, Trustpilot, Glassdoor, Yelp, TripAdvisor, CNET, Product Hunt, and similar.",
                      "why": "AI engines weigh user reviews heavily when comparing competitors. A brand with 100 reviews at 4.5 stars on G2 gets recommended; a brand with none gets skipped in favor of one that has been vetted by real users. The platforms LLMs read are different per category.",
                      "scoring": "Presence on 3+ category-relevant platforms → PASS. 1–2 platforms → WARN. None → FAIL."
                    },
                    "mentions": {
                      "name": "Authoritative Press & Media Mentions",
                      "measures": "Searches for mentions of your brand on high-authority news and trade publications — WSJ, NYT, TechCrunch, Forbes, Bloomberg, industry analyst reports.",
                      "why": "Authority compounds. One TechCrunch article is worth more than a hundred backlinks from random blogs. LLMs trained on news datasets (GDELT, CCNews, RSS dumps) treat these mentions as ground truth when building a brand's entity profile.",
                      "scoring": "3+ high-authority mentions → PASS. 1–2 → WARN. None → FAIL."
                    }
                  }
                },
                "visibility": {
                  "title": "4. Direct AI Visibility",
                  "description": "The lagging-indicator metrics that measure whether real AI engines actually name and cite you when users ask questions in your category. Everything above is a leading indicator; this is what actually matters.",
                  "items": {
                    "citationRate": {
                      "name": "AI Citation Rate",
                      "measures": "Sends a fixed set of brand- and category-relevant questions to Perplexity (via OpenRouter) and counts how often your domain appears as a cited source.",
                      "why": "The ultimate test: are real AI engines pointing to you when users ask questions in your category? Everything else in this glossary is a leading indicator; citation rate is the lagging indicator that actually moves revenue.",
                      "scoring": "≥80% citation rate → A (excellent). 60–79% → B. 40–59% → C. 20–39% → D. <20% → F."
                    },
                    "answerInclusion": {
                      "name": "Answer Inclusion Rate",
                      "measures": "Similar to citation rate but softer — checks whether your brand name appears in the AI-generated answer text, even without a clickable citation link.",
                      "why": "Being named without a citation still earns mindshare. Users who read `Brands like X, Y, Z all do this` remember the names even without clicking. Answer inclusion is a leading indicator of citation rate — mentions come first, citations follow.",
                      "scoring": "≥60% of relevant queries name your brand → PASS. 30–59% → WARN. <30% → FAIL."
                    },
                    "shareOfVoice": {
                      "name": "Competitor Share of Voice",
                      "measures": "Across the same set of category queries, counts which competitor brands are mentioned alongside yours and how often.",
                      "why": "You don't just want to be mentioned — you want to be mentioned before your main competitors and more often than them. This metric shows whether AI perceives you as the category leader, a challenger, or an also-ran.",
                      "scoring": "Your brand in the top-3 most-mentioned → PASS. In top-10 → WARN. Not mentioned → FAIL."
                    },
                    "sentimentFraming": {
                      "name": "Brand Sentiment & Framing",
                      "measures": "Analyzes the emotional tone and narrative framing AI uses when describing your brand — innovator, challenger, niche player, has-had-issues, controversial.",
                      "why": "The frame AI picks up during training sticks for years. A brand framed as `innovator` in training data gets recommended proactively; a brand framed as `has had issues` gets hedged with disclaimers even when the situation has improved long ago.",
                      "scoring": "≥60% positive or neutral framing → PASS. 30–59% → WARN. <30% or frequent hedging → FAIL."
                    },
                    "contentGaps": {
                      "name": "Content Gaps",
                      "measures": "Identifies questions in your category where AI engines cannot find a good answer from your site — topics where a competitor wrote the definitive piece and you did not.",
                      "why": "Every unfilled content gap is a user journey your competitor owns. Filling the gap is the single most direct way to move citation rate, because AI will immediately start pointing to the new page once it's crawled.",
                      "scoring": "0 major gaps → PASS. 1–3 gaps → WARN. 4+ gaps → FAIL."
                    }
                  }
                },
                "entity": {
                  "title": "5. Entity Recognition",
                  "description": "Whether large language models perceive your brand as a real, distinct entity they can confidently describe — the foundation that everything else in AI visibility rests on.",
                  "items": {
                    "entityClarity": {
                      "name": "Entity Clarity",
                      "measures": "Asks AI models to describe your brand, then scores how accurate, specific, and complete the description is. Does the model know what you do, for whom, and how you're different?",
                      "why": "If AI can't crisply describe what you are, it can't recommend you. `I think they do something with AI` is a failure state — users re-ask and competitors jump the queue while the model is hedging on you.",
                      "scoring": "Accurate and specific description → PASS. Vague or partially wrong → WARN. Confused or unknown → FAIL."
                    },
                    "categoryAssociation": {
                      "name": "Category Association",
                      "measures": "Checks whether AI places your brand in the right mental bucket when users ask category questions. Ask `best tools for X` — do you appear? Asked about the wrong category — are you absent?",
                      "why": "Most buyer searches go through category intent. If AI classifies you in the wrong category (or none at all) you're invisible to people who are actively shopping — they'll never see your name.",
                      "scoring": "Correctly placed in the right category for ≥70% of queries → PASS. 30–69% → WARN. <30% → FAIL."
                    },
                    "platformCoverage": {
                      "name": "Multi-platform Presence",
                      "measures": "Checks whether your brand has a verified presence on the platforms AI models train on most heavily: Wikipedia, Wikidata, Crunchbase, LinkedIn, GitHub, Reddit, Product Hunt, Hacker News, industry directories.",
                      "why": "Every additional high-authority platform is another corroborating source that AI uses to build your entity profile. Brands with 6+ platform presences get recommended confidently; those with only a website get treated as unverified and hedged.",
                      "scoring": "Presence on ≥6 of 10 key platforms → PASS. 3–5 → WARN. <3 → FAIL."
                    },
                    "recognitionRate": {
                      "name": "Recognition Rate",
                      "measures": "The share of AI queries — across multiple engines and prompt variations — where the model recognizes your brand name without needing a URL or disambiguation.",
                      "why": "Recognition is the precursor to recommendation. If AI has to ask `which X do you mean?` every time, you lose the user to a brand the model already knows by name.",
                      "scoring": "≥80% recognition → PASS. 50–79% → WARN. <50% → FAIL."
                    },
                    "stability": {
                      "name": "Answer Stability",
                      "measures": "Runs the same query multiple times against the same AI engine and checks whether the answer is consistent across runs. Unstable answers signal weak training grounding.",
                      "why": "If the same question gives `X is a great tool` one time and `I've never heard of X` the next, users will trust the uncertain run and pass. Stability equals trust, and trust equals the recommendation.",
                      "scoring": "≥90% consistent answers → PASS. 70–89% → WARN. <70% → FAIL."
                    }
                  }
                }
              }
            }
          },
} as const;

export default enKnowledge;
