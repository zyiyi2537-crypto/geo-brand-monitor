"""AI engine query helpers + response analysis.

Migrated from /geo_checker.py lines 5536-5791.

- `_query_perplexity/openai/anthropic` route through OpenRouter so a single
  OPENROUTER_API_KEY unlocks all three engines. Each returns
  (answer, citations, error).
- `_query_deepseek/doubao/qwen` hit native APIs for Chinese AI engines.
- `_check_brand_in_result`, `_extract_competitors`, `_classify_framing` are
  shared response analyzers used by citation / visibility / entity modes.
"""

import re
import time
from urllib.parse import urlparse

import requests


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
        # Haiku 4.5 vs Sonnet 4: output $5/M vs $15/M (-67% on Claude cost,
        # -22% on overall /visibility cost). For binary "brand mentioned?"
        # classification Haiku overlaps 85-90% with Sonnet. The engine
        # display label stays "Claude" in modes/visibility.py:60 — users
        # don't need the version number.
        "model": "anthropic/claude-haiku-4.5:online",
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


def _query_qwen(query, api_key):
    """Send a query to Qwen (DashScope) with enable_search=true. Returns (answer, citations, error)."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "qwen-plus",
        "messages": [{"role": "user", "content": query}],
        "enable_search": True,
    }
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=60)
        if r.status_code == 401:
            return "", [], "invalid_key"
        if r.status_code == 429:
            time.sleep(5)
            r = requests.post(url, json=payload, headers=headers, timeout=60)
        if r.status_code != 200:
            return "", [], f"http_{r.status_code}"
        data = r.json()
        choices = data.get("choices", [])
        msg = choices[0].get("message", {}) if choices else {}
        answer = msg.get("content", "") or ""

        # DashScope returns structured search_results when enable_search=true.
        # The field can live at the top level or nested under message.
        search_results = data.get("search_results") or msg.get("search_results") or []
        citations = []
        for sr in search_results:
            u = sr.get("url") or sr.get("link") or ""
            if u:
                citations.append(u)
        # Fallback: extract URLs from answer text
        if not citations:
            citations = re.findall(r'https?://[^\s\)\]>]+', answer)
        citations = list(dict.fromkeys(citations))
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
    """Classify how the AI frames the brand in its answer.
    Supports both English and Chinese response patterns."""
    answer_lower = answer.lower()
    brand_lower = brand.lower()

    if brand_lower not in answer_lower:
        return "not_mentioned"

    # Check for recommendation language (strongest) — EN + ZH
    rec_patterns = [
        f"recommend {brand_lower}", f"use {brand_lower}", f"consider {brand_lower}",
        f"try {brand_lower}", f"choose {brand_lower}", f"go with {brand_lower}",
        f"{brand_lower} is the best", f"{brand_lower} is a leading",
        f"{brand_lower} is a top", f"{brand_lower} stands out",
    ]
    rec_patterns_zh = [
        f"推荐{brand_lower}", f"建议.*{brand_lower}", f"首选.*{brand_lower}",
        f"{brand_lower}.*最好", f"{brand_lower}.*最佳", f"{brand_lower}.*首推",
        f"值得.*{brand_lower}", f"选择{brand_lower}",
    ]
    for pat in rec_patterns:
        if pat in answer_lower:
            return "recommended"
    for pat in rec_patterns_zh:
        if re.search(pat, answer_lower):
            return "recommended"

    # Check for leader framing — EN + ZH
    leader_patterns = [
        f"{brand_lower} is a leader", f"{brand_lower} is one of the leading",
        f"{brand_lower} is a major", f"{brand_lower} is a popular",
        f"{brand_lower} is well-known", f"{brand_lower} is widely used",
        f"{brand_lower} is a prominent",
    ]
    leader_patterns_zh = [
        f"{brand_lower}.*领先", f"{brand_lower}.*领导", f"{brand_lower}.*知名",
        f"{brand_lower}.*著名", f"{brand_lower}.*头部", f"{brand_lower}.*顶尖",
        f"{brand_lower}.*领军", f"{brand_lower}.*权威",
    ]
    for pat in leader_patterns:
        if pat in answer_lower:
            return "leader"
    for pat in leader_patterns_zh:
        if re.search(pat, answer_lower):
            return "leader"

    # Check for option/alternative framing — EN + ZH
    option_patterns = [
        f"{brand_lower} is an option", f"{brand_lower} is one option",
        f"{brand_lower} is an alternative", f"alternative.*{brand_lower}",
        f"options.*{brand_lower}", f"include.*{brand_lower}",
        f"{brand_lower} is another",
    ]
    option_patterns_zh = [
        f"{brand_lower}.*之一", f"{brand_lower}.*可选", f"{brand_lower}.*替代",
        f"包括.*{brand_lower}", f"其中.*{brand_lower}",
    ]
    for pat in option_patterns:
        if re.search(pat, answer_lower):
            return "option"
    for pat in option_patterns_zh:
        if re.search(pat, answer_lower):
            return "option"

    # Check for niche/experimental framing — EN + ZH
    niche_patterns = [
        f"{brand_lower} is a niche", f"{brand_lower} is experimental",
        f"{brand_lower} is a newer", f"{brand_lower} is a small",
        f"{brand_lower} is relatively new", f"{brand_lower} is emerging",
    ]
    niche_patterns_zh = [
        f"{brand_lower}.*小众", f"{brand_lower}.*新兴", f"{brand_lower}.*新锐",
        f"{brand_lower}.*起步", f"{brand_lower}.*实验",
    ]
    for pat in niche_patterns:
        if pat in answer_lower:
            return "niche"
    for pat in niche_patterns_zh:
        if re.search(pat, answer_lower):
            return "niche"

    return "mentioned"


