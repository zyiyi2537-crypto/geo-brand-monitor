"""Static data constants: AI bot/crawler lists + ANSI status tags.

Migrated from /geo_checker.py lines 27–66.
"""

# ---------------------------------------------------------------------------
# Global config
# ---------------------------------------------------------------------------
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

# ANSI-color status tags used in CLI output. Also embedded in strings parsed
# by the backend's parse_geo_output, which strips ANSI before matching.
PASS = "\033[92mPASS\033[0m"
WARN = "\033[93mWARN\033[0m"
FAIL = "\033[91mFAIL\033[0m"
INFO = "\033[94mINFO\033[0m"
FIX  = "\033[96m FIX\033[0m"
