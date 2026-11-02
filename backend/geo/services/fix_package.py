"""Generate a downloadable fix package (ZIP) from a GeoTestResult.

The package contains real file contents (robots.txt, llms.txt, HTML patches,
nginx/apache config snippets, content suggestion markdown) that the user can
drop straight into their site root or pass to a developer.

Supports locale-aware content generation (en/zh) and auto-populates templates
with data extracted from the actual check results (brand name, title,
description, lang, social links, etc.).

Invoked by POST /api/check/fix-package.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from ..models.geo import GeoTestResult, CheckResult

TIER_RANK = {"free": 0, "pro": 1, "starter": 2, "growth": 3, "scale": 4}


class FixItem:
    """A single actionable fix derived from a FAIL/WARN check."""

    def __init__(
        self,
        fix_key: str | None,
        fix_text: str,
        check_message: str,
        category: str,
        status: str,
        priority: str = "medium",
    ):
        self.fix_key = fix_key
        self.fix_text = fix_text
        self.check_message = check_message
        self.category = category
        self.status = status
        self.priority = priority


def _domain_from_url(url: str) -> str:
    parsed = urlparse(url)
    domain = parsed.netloc or url
    return domain.replace(":", "_").replace("/", "_")


# ---------------------------------------------------------------------------
# Site info extracted from check results
# ---------------------------------------------------------------------------
class _SiteInfo:
    """Data extracted from check results to personalize generated files."""

    def __init__(self):
        self.brand: str = ""
        self.title: str = ""
        self.description: str = ""
        self.lang: str = "en"
        self.og_image: str = ""
        self.social_links: list[str] = []
        self.hreflang_langs: list[str] = []
        self.has_sitemap: bool = False
        self.sitemap_path: str = ""
        self.feed_url: str = ""

    @staticmethod
    def from_checks(checks: list[CheckResult], url: str) -> "_SiteInfo":
        info = _SiteInfo()
        base = url.rstrip("/")
        domain = _domain_from_url(url)

        for c in checks:
            msg = c.message or ""
            params = c.message_params or {}
            key = c.message_key or ""

            # Brand name — from ai_opt.brand_consistent or brand_sparse
            if "brand_consistent" in key or "brand_sparse" in key:
                info.brand = params.get("name", "") or info.brand
            if "brand_inconsistent" in key and not info.brand:
                names = params.get("names", "")
                if names:
                    info.brand = names.split(",")[0].strip()

            # Title
            if "meta.title_found" in key:
                info.title = params.get("title", "") or info.title
            elif not info.title and "title_found" in key and "title" in params:
                info.title = params["title"]

            # Description
            if "meta.description_found" in key:
                # description text is in message, not params
                info.description = info.description or ""

            # Language
            if "meta.lang_declared" in key:
                info.lang = params.get("lang", "en") or "en"

            # Social links from sameAs
            if "sameas_found" in key:
                # Extract URLs from message
                urls = re.findall(r'https?://[^\s,\'"]+', msg)
                info.social_links.extend(urls)

            # Social links from cross_platform
            if "cross_platform.linked_on_site" in key or "cross_platform.profile_found" in key:
                link_url = params.get("url", "")
                if link_url and link_url not in info.social_links:
                    info.social_links.append(link_url)

            # Hreflang
            if "meta.hreflang_found" in key:
                langs = params.get("langs", "")
                if langs:
                    info.hreflang_langs = [l.strip() for l in langs.split(",")]

            # Sitemap
            if "sitemap.found" in key:
                info.has_sitemap = True
                info.sitemap_path = params.get("path", "/sitemap.xml")

            # Feed
            if "tech_crawl.feed_declared" in key:
                info.feed_url = params.get("feeds", "")

        # Fallback brand from domain
        if not info.brand:
            host = urlparse(url).netloc or ""
            parts = host.replace("www.", "").split(".")
            if parts:
                info.brand = parts[0].capitalize()

        # Fallback title
        if not info.title:
            info.title = info.brand

        return info


# ---------------------------------------------------------------------------
# Localized text tables
# ---------------------------------------------------------------------------
_ZH_FIX_TABLE: dict[str, str] = {
    "result.fixes.https.enable_https": "安装 SSL/TLS 证书（可通过 Let's Encrypt 免费获取），并将所有 HTTP 流量重定向至 HTTPS。",
    "result.fixes.robots.create": "在站点根目录创建 robots.txt 文件。",
    "result.fixes.robots.add_sitemap_directive": "在 robots.txt 中添加 Sitemap 指令。",
    "result.fixes.robots.unblock_wildcard": "将 robots.txt 中的 'Disallow: /' 改为 'Allow: /' 以允许 AI 爬虫。",
    "result.fixes.robots.unblock_bots": "在 robots.txt 中移除或修改特定 AI 爬虫的 Disallow 规则。",
    "result.fixes.robots.add_ai_txt": "创建 ai.txt 或 .well-known/ai.txt 来声明 AI 爬虫策略。",
    "result.fixes.llms.create_file": "在站点根目录创建 llms.txt 文件。",
    "result.fixes.llms.create_full_file": "创建 llms-full.txt 提供扩展内容。",
    "result.fixes.sitemap.create_file": "在站点根目录创建 sitemap.xml。",
    "result.fixes.sitemap.add_lastmod": "为 sitemap.xml 的各条目添��� <lastmod> 时间戳。",
    "result.fixes.structured.add_organization_jsonld": "在 <head> 中添加 Organization JSON-LD 结构化数据。",
    "result.fixes.meta.add_title": "在 <head> 中添加 <title> 标签。",
    "result.fixes.meta.add_description": "在 <head> 中添加 meta description 标签。",
    "result.fixes.meta.add_canonical": "在 <head> 中添加 canonical 链接。",
    "result.fixes.meta.add_og": "在 <head> 中添加 Open Graph meta 标签。",
    "result.fixes.meta.add_twitter_cards": "在 <head> 中添加 Twitter Card meta 标签。",
    "result.fixes.meta.add_lang": "为 <html> 标签添加 lang 属性。",
    "result.fixes.meta.add_hreflang": "为多语言页面添加 hreflang 标签。",
    "result.fixes.authority.add_security_headers": "在服务器配置中添加安全响应头。",
    "result.fixes.authority.add_humans_txt": "在站点根目录创建 humans.txt。",
    "result.fixes.tech_crawl.add_rss_feed": "为内容添加 RSS 或 Atom feed。",
    "result.fixes.content_access.add_alt_text": "为所有 <img> 标签添加描述性 alt 文本。",
    "result.fixes.content_access.add_headings": "使用标题标签构建内容���级。",
    "result.fixes.crawl_ready.enable_ssr": "启用服务端渲染。",
    "result.fixes.crawl_ready.remove_noindex": "从 meta robots 中移除 'noindex'。",
    "result.fixes.crawl_ready.remove_nofollow": "从 meta robots 中移除 'nofollow'。",
    "result.fixes.crawl_ready.remove_noai": "移除 'noai' 指令。",
    "result.fixes.crawl_ready.paywall_workarounds": "在付费墙之前提供免费预览或摘要。",
    "result.fixes.crawl_ready.add_semantic_html5": "用语义化 HTML5 元素替换通用 <div>。",
    "result.fixes.content_quality.add_statistics": "在内容中加入可引用的具体数据。",
    "result.fixes.content_quality.add_attributions": "添加来源标注以增强可信度。",
    "result.fixes.content_quality.add_lists": "使用结构化列表，便于 AI 提取。",
    "result.fixes.content_quality.add_faq_schema": "添加 FAQPage schema 提升 AI 答案排名。",
    "result.fixes.content_quality.add_faq_section": "为页面添�� FAQ 区块。",
    "result.fixes.content_quality.frontload_facts": "在首段前置事实信息。",
    "result.fixes.tech_crawl.enable_http2": "在服务器启用 HTTP/2 加快爬取速度。",
    "result.fixes.tech_crawl.reduce_redirects": "将重定��链压缩为单跳。",
    "result.fixes.tech_crawl.fix_canonical_chain": "修复 canonical 链——每个页面应直接指向最终 URL。",
    "result.fixes.tech_crawl.add_api_docs": "发布机器可读的数据 feed 和集成文档。",
    "result.fixes.content_access.enable_ssr": "确保关键��容由服务端渲染。",
    "result.fixes.content_access.client_rendered_workarounds": "切换至 SSR/SSG 或接入预渲染服务。",
}

_EN_FIX_TABLE: dict[str, str] = {
    "result.fixes.https.enable_https": "Install an SSL/TLS certificate (free via Let's Encrypt) and redirect all HTTP traffic to HTTPS.",
    "result.fixes.robots.create": "Create a robots.txt file at the root of your site.",
    "result.fixes.robots.add_sitemap_directive": "Add a Sitemap directive to robots.txt.",
    "result.fixes.robots.unblock_wildcard": "Change 'Disallow: /' to 'Allow: /' in robots.txt to allow AI crawlers.",
    "result.fixes.robots.unblock_bots": "Remove or modify Disallow directives for specific AI bots in robots.txt.",
    "result.fixes.robots.add_ai_txt": "Create an ai.txt or .well-known/ai.txt to declare AI crawler policy.",
    "result.fixes.llms.create_file": "Create an llms.txt file at your site root.",
    "result.fixes.llms.create_full_file": "Create llms-full.txt with expanded content.",
    "result.fixes.sitemap.create_file": "Create a sitemap.xml at your site root.",
    "result.fixes.sitemap.add_lastmod": "Add <lastmod> timestamps to your sitemap.xml entries.",
    "result.fixes.structured.add_organization_jsonld": "Add Organization JSON-LD structured data to your <head>.",
    "result.fixes.meta.add_title": "Add a <title> tag in your <head>.",
    "result.fixes.meta.add_description": "Add a meta description tag in your <head>.",
    "result.fixes.meta.add_canonical": "Add a canonical link in your <head>.",
    "result.fixes.meta.add_og": "Add Open Graph meta tags in your <head>.",
    "result.fixes.meta.add_twitter_cards": "Add Twitter Card meta tags in your <head>.",
    "result.fixes.meta.add_lang": "Add a lang attribute to your <html> tag.",
    "result.fixes.meta.add_hreflang": "Add hreflang tags for multilingual pages.",
    "result.fixes.authority.add_security_headers": "Add security headers to your server.",
    "result.fixes.authority.add_humans_txt": "Create a humans.txt at your site root.",
    "result.fixes.tech_crawl.add_rss_feed": "Add an RSS or Atom feed for your content.",
    "result.fixes.content_access.add_alt_text": "Add descriptive alt text to all <img> tags.",
    "result.fixes.content_access.add_headings": "Add heading tags to structure your content.",
    "result.fixes.crawl_ready.enable_ssr": "Enable server-side rendering.",
    "result.fixes.crawl_ready.remove_noindex": "Remove 'noindex' from meta robots tag.",
    "result.fixes.crawl_ready.remove_nofollow": "Remove 'nofollow' from meta robots tag.",
    "result.fixes.crawl_ready.remove_noai": "Remove 'noai' directive.",
    "result.fixes.crawl_ready.paywall_workarounds": "Provide a free preview or summary above the paywall.",
    "result.fixes.crawl_ready.add_semantic_html5": "Replace generic <div> containers with semantic HTML5 elements.",
    "result.fixes.content_quality.add_statistics": "Add concrete, quotable statistics to your content.",
    "result.fixes.content_quality.add_attributions": "Add source attributions to increase credibility.",
    "result.fixes.content_quality.add_lists": "Add structured lists to make content easily extractable by AI.",
    "result.fixes.content_quality.add_faq_schema": "Add FAQPage schema to boost AI answer ranking.",
    "result.fixes.content_quality.add_faq_section": "Add an FAQ section to your page.",
    "result.fixes.content_quality.frontload_facts": "Front-load facts into your first paragraph.",
    "result.fixes.tech_crawl.enable_http2": "Enable HTTP/2 on your server for faster crawling.",
    "result.fixes.tech_crawl.reduce_redirects": "Reduce redirect chains to a single hop.",
    "result.fixes.tech_crawl.fix_canonical_chain": "Fix the canonical chain — each page's canonical should point directly to the final URL.",
    "result.fixes.tech_crawl.add_api_docs": "Publish machine-readable data feeds and integration docs.",
    "result.fixes.content_access.enable_ssr": "Ensure key content is rendered server-side.",
    "result.fixes.content_access.client_rendered_workarounds": "Switch to SSR/SSG or add a pre-rendering service.",
}


class FixPackageGenerator:
    """Walk a GeoTestResult and emit all the files needed to apply fixes."""

    def __init__(self, result: GeoTestResult, *, locale: str = "en"):
        self.result = result
        self.locale = locale if locale.startswith("zh") else "en"
        self.zh = self.locale.startswith("zh")
        self.fix_items: list[FixItem] = []
        self.site = _SiteInfo.from_checks(result.checks, result.url)
        self._collect_fixes()

    # helper
    def _t(self, en: str, zh: str) -> str:
        return zh if self.zh else en

    # ------------------------------------------------------------------
    # 1. Collect FAIL/WARN items
    # ------------------------------------------------------------------
    def _collect_fixes(self):
        for check in self.result.checks:
            if check.status not in ("FAIL", "WARN"):
                continue
            fix_text = ""
            if check.fix:
                fix_text = check.fix.strip()
            elif check.fix_key:
                fix_text = self._lookup_fix_text(check.fix_key, check.fix_params)

            if not fix_text:
                continue

            priority = "high" if check.status == "FAIL" else "medium"
            self.fix_items.append(
                FixItem(
                    fix_key=check.fix_key,
                    fix_text=fix_text,
                    check_message=check.message,
                    category=check.category,
                    status=check.status,
                    priority=priority,
                )
            )

    def _lookup_fix_text(self, key: str, params: dict | None) -> str:
        table = _ZH_FIX_TABLE if self.zh else _EN_FIX_TABLE
        text = table.get(key, "")
        if params and text:
            try:
                text = text.format(**params)
            except (KeyError, ValueError):
                pass
        return text

    # ------------------------------------------------------------------
    # 2. File generators — all use self.site for real data
    # ------------------------------------------------------------------

    def _generate_robots_txt(self) -> dict[str, str]:
        items = [f for f in self.fix_items if f.fix_key and "robots" in f.fix_key]
        if not items:
            return {}

        sitemap_url = self.result.url.rstrip("/") + "/sitemap.xml"
        header = self._t(
            "# robots.txt — generated by GEO Checker",
            "# robots.txt — 由 GEO Checker 生成",
        )
        comment_allow = self._t(
            "# Allow all AI crawlers by default",
            "# 默认允许所有 AI 爬虫",
        )
        comment_explicit = self._t(
            "# Explicitly allow common AI crawlers",
            "# 显式允许常见 AI 爬虫",
        )
        content = (
            f"{header}\n"
            "# https://www.vigilath.com\n"
            "#\n"
            f"{comment_allow}\n"
            "User-agent: *\n"
            "Allow: /\n"
            "\n"
            f"{comment_explicit}\n"
            "User-agent: GPTBot\n"
            "Allow: /\n"
            "\n"
            "User-agent: ChatGPT-User\n"
            "Allow: /\n"
            "\n"
            "User-agent: ClaudeBot\n"
            "Allow: /\n"
            "\n"
            "User-agent: Google-Extended\n"
            "Allow: /\n"
            "\n"
            "User-agent: PerplexityBot\n"
            "Allow: /\n"
            "\n"
            "# Sitemap\n"
            f"Sitemap: {sitemap_url}\n"
        )
        return {"robots.txt": content}

    def _generate_llms_txt(self) -> dict[str, str]:
        items = [f for f in self.fix_items if f.fix_key and "llms" in f.fix_key]
        if not items:
            return {}

        base = self.result.url.rstrip("/")
        brand = self.site.brand
        desc_placeholder = self._t(
            f"A comprehensive platform by {brand}.",
            f"{brand} 提供的综合平台。",
        )
        doc_heading = self._t("## Documentation", "## 文档")
        doc_desc = self._t("Guides and documentation.", "使用指南与文档。")
        blog_heading = self._t("## Blog", "## 博客")
        blog_desc = self._t("Latest articles and updates.", "最新文章与动态。")
        about_heading = self._t("## About", "## 关于")
        about_desc = self._t(f"Learn more about {brand}.", f"了解更多关于 {brand} 的信息。")
        legal_heading = self._t("## Legal", "## 法律条款")

        llms = (
            f"# {brand}\n"
            f"\n"
            f"{desc_placeholder}\n"
            f"\n"
            f"{doc_heading}\n"
            f"{doc_desc}\n"
            f"- [Getting Started]({base}/docs/start)\n"
            f"- [API Reference]({base}/api)\n"
            f"\n"
            f"{blog_heading}\n"
            f"{blog_desc}\n"
            f"- [All Posts]({base}/blog)\n"
            f"\n"
            f"{about_heading}\n"
            f"{about_desc}\n"
            f"- [About Us]({base}/about)\n"
            f"- [Contact]({base}/contact)\n"
            f"\n"
            f"{legal_heading}\n"
            f"- [Privacy Policy]({base}/privacy)\n"
            f"- [Terms of Service]({base}/terms)\n"
        )

        full_title = self._t(
            f"# {brand} — Full Documentation",
            f"# {brand} — 完整文档",
        )
        full_desc = self._t(
            f"This is a comprehensive guide to {brand}.",
            f"这是 {brand} 的完整使用指南。",
        )
        overview = self._t("## Platform Overview", "## 平台概览")
        features = self._t("## Core Features", "## 核心功能")
        getting_started = self._t("## Getting Started", "## 快速开始")
        api_ref = self._t("## API Reference", "## API 文档")
        blog_news = self._t("## Blog & News", "## 博客与动态")
        company = self._t("## Company", "## 公司信息")
        status = self._t("## Status", "## 状态")

        llms_full = (
            f"{full_title}\n"
            f"\n"
            f"{full_desc}\n"
            f"\n"
            f"{overview}\n"
            f"\n"
            f"{features}\n"
            f"\n"
            f"{getting_started}\n"
            f"- [Sign Up]({base}/signup)\n"
            f"- [Documentation]({base}/docs)\n"
            f"\n"
            f"{api_ref}\n"
            f"- [REST API]({base}/api)\n"
            f"- [Webhooks]({base}/api/webhooks)\n"
            f"\n"
            f"{blog_news}\n"
            f"- [All Posts]({base}/blog)\n"
            f"- [Changelog]({base}/changelog)\n"
            f"\n"
            f"{company}\n"
            f"- [About Us]({base}/about)\n"
            f"- [Careers]({base}/careers)\n"
            f"- [Contact]({base}/contact)\n"
            f"\n"
            f"{legal_heading}\n"
            f"- [Privacy Policy]({base}/privacy)\n"
            f"- [Terms of Service]({base}/terms)\n"
            f"\n"
            f"{status}\n"
            f"- [System Status]({base}/status)\n"
            f"- [Security]({base}/.well-known/security.txt)\n"
        )
        return {"llms.txt": llms, "llms-full.txt": llms_full}

    def _generate_meta_patches(self) -> dict[str, str]:
        items = [f for f in self.fix_items if f.fix_key and "meta" in f.fix_key]
        if not items:
            return {}

        base = self.result.url.rstrip("/")
        brand = self.site.brand
        title = self.site.title or brand
        lang = self.site.lang

        patches: list[str] = []
        header_comment = self._t(
            "<!-- GEO Checker: Meta Tags Patch -->\n"
            "<!-- Add these tags inside your <head> section -->",
            "<!-- GEO Checker：Meta 标签补丁 -->\n"
            "<!-- 将以下标签添加到 <head> 区域内 -->",
        )
        patches.append(header_comment + "\n")

        has_title = any("add_title" in f.fix_key for f in items)
        if has_title:
            patches.append(f'\n<title>{title}</title>\n')

        has_description = any("description" in f.fix_key for f in items)
        if has_description:
            desc_hint = self._t(
                f"A 120-160 character summary of {brand} — include key topics and value proposition.",
                f"{brand} 的 120-160 字简介 — 包含核心关键词与价值主张。",
            )
            patches.append(f'\n<meta name="description" content="{desc_hint}" />\n')

        has_canonical = any("canonical" in f.fix_key for f in items)
        if has_canonical:
            patches.append(f'\n<link rel="canonical" href="{base}" />\n')

        has_og = any("og" in f.fix_key for f in items)
        if has_og:
            patches.append(
                f'\n<meta property="og:title" content="{title}" />\n'
                f'<meta property="og:description" content="{self._t("Brief description of your page.", f"{brand} 的页面简介。")}" />\n'
                f'<meta property="og:type" content="website" />\n'
                f'<meta property="og:url" content="{base}" />\n'
                f'<meta property="og:site_name" content="{brand}" />\n'
                f'<meta property="og:image" content="{base}/og-image.png" />\n'
            )

        has_twitter = any("twitter" in f.fix_key for f in items)
        if has_twitter:
            patches.append(
                f'\n<meta name="twitter:card" content="summary_large_image" />\n'
                f'<meta name="twitter:title" content="{title}" />\n'
                f'<meta name="twitter:description" content="{self._t("Brief description of your page.", f"{brand} 的页面简介。")}" />\n'
                f'<meta name="twitter:image" content="{base}/og-image.png" />\n'
            )

        has_lang = any("lang" in f.fix_key and "hreflang" not in f.fix_key for f in items)
        if has_lang:
            lang_comment = self._t(
                f'<!-- Add lang="{lang}" to your <html> tag: <html lang="{lang}"> -->',
                f'<!-- 为 <html> 标签添加 lang="{lang}"：<html lang="{lang}"> -->',
            )
            patches.append(f"\n{lang_comment}\n")

        has_hreflang = any("hreflang" in f.fix_key for f in items)
        if has_hreflang:
            hreflang_comment = self._t(
                "<!-- hreflang tags — add inside <head>: -->",
                "<!-- hreflang 标签 — 添加到 <head> 内: -->",
            )
            patches.append(f"\n{hreflang_comment}\n")
            if self.site.hreflang_langs:
                for hl in self.site.hreflang_langs:
                    patches.append(f'<link rel="alternate" hreflang="{hl}" href="{base}/{hl}/" />\n')
            else:
                patches.append(f'<link rel="alternate" hreflang="en" href="{base}/en/" />\n')
                patches.append(f'<link rel="alternate" hreflang="zh" href="{base}/zh/" />\n')
            patches.append(f'<link rel="alternate" hreflang="x-default" href="{base}/" />\n')

        return {"patches/meta-tags-patch.html": "".join(patches)}

    def _generate_jsonld_patches(self) -> dict[str, str]:
        items = [f for f in self.fix_items if f.fix_key and "structured" in f.fix_key]
        if not items:
            return {}

        base = self.result.url.rstrip("/")
        brand = self.site.brand

        patches: list[str] = []
        header = self._t(
            "<!-- GEO Checker: JSON-LD Structured Data Patch -->\n"
            '<!-- Add these <script type="application/ld+json"> blocks inside your <head> -->',
            "<!-- GEO Checker：JSON-LD 结构化数据补丁 -->\n"
            '<!-- 将以下 <script type="application/ld+json"> 代码块添加到 <head> 内 -->',
        )
        patches.append(header + "\n")

        has_org = any("organization" in f.fix_key or "jsonld" in f.fix_key for f in items)
        if has_org:
            same_as = ""
            if self.site.social_links:
                links_json = ",\n    ".join(f'"{u}"' for u in self.site.social_links[:5])
                same_as = f',\n  "sameAs": [\n    {links_json}\n  ]'
            desc = self._t(
                f"What {brand} does in one or two sentences.",
                f"{brand} 的核心业务简介（一到两句话）。",
            )
            patches.append(
                '\n'
                '<script type="application/ld+json">\n'
                '{\n'
                '  "@context": "https://schema.org",\n'
                '  "@type": "Organization",\n'
                f'  "name": "{brand}",\n'
                f'  "url": "{base}",\n'
                f'  "description": "{desc}",\n'
                f'  "logo": "{base}/logo.png"'
                f'{same_as}\n'
                '}\n'
                '</script>\n'
            )

        has_faq = any("faq" in f.fix_key for f in items)
        if has_faq:
            if self.zh:
                q1, a1 = f"{brand} 是什么？", f"请在此处简明扼要地回答。"
                q2, a2 = "价格是多少？", "请在此处提供定价信息。"
                q3, a3 = "如何开始使用？", "请在此处提供快速入门步骤。"
            else:
                q1, a1 = f"What is {brand}?", "Provide a clear, concise answer here."
                q2, a2 = "How much does it cost?", "Provide pricing information here."
                q3, a3 = "How do I get started?", "Provide step-by-step guidance here."
            patches.append(
                '\n'
                '<script type="application/ld+json">\n'
                '{\n'
                '  "@context": "https://schema.org",\n'
                '  "@type": "FAQPage",\n'
                '  "mainEntity": [\n'
                '    {\n'
                '      "@type": "Question",\n'
                f'      "name": "{q1}",\n'
                '      "acceptedAnswer": {\n'
                '        "@type": "Answer",\n'
                f'        "text": "{a1}"\n'
                '      }\n'
                '    },\n'
                '    {\n'
                '      "@type": "Question",\n'
                f'      "name": "{q2}",\n'
                '      "acceptedAnswer": {\n'
                '        "@type": "Answer",\n'
                f'        "text": "{a2}"\n'
                '      }\n'
                '    },\n'
                '    {\n'
                '      "@type": "Question",\n'
                f'      "name": "{q3}",\n'
                '      "acceptedAnswer": {\n'
                '        "@type": "Answer",\n'
                f'        "text": "{a3}"\n'
                '      }\n'
                '    }\n'
                '  ]\n'
                '}\n'
                '</script>\n'
            )

        return {"patches/json-ld-patch.html": "".join(patches)}

    def _generate_security_config(self) -> dict[str, str]:
        items = [f for f in self.fix_items if f.fix_key and "security" in f.fix_key]
        if not items:
            return {}

        nginx_comment = self._t(
            "# GEO Checker: Security Headers — Nginx\n"
            "# Add to your nginx server block configuration file\n"
            "# Usually located at /etc/nginx/sites-available/your-site",
            "# GEO Checker：安全响应头 — Nginx\n"
            "# 添加到 nginx server 块配置文件中\n"
            "# 通常位于 /etc/nginx/sites-available/your-site",
        )
        nginx = (
            f"{nginx_comment}\n"
            "\n"
            "server {\n"
            "    # ... your existing server block config ...\n"
            "\n"
            "    # Security headers\n"
            '    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;\n'
            '    add_header Content-Security-Policy "default-src \'self\'; script-src \'self\' \'unsafe-inline\'; style-src \'self\' \'unsafe-inline\';" always;\n'
            '    add_header X-Content-Type-Options "nosniff" always;\n'
            '    add_header X-Frame-Options "DENY" always;\n'
            '    add_header Referrer-Policy "strict-origin-when-cross-origin" always;\n'
            "}\n"
        )

        apache_comment = self._t(
            "# GEO Checker: Security Headers — Apache (.htaccess)\n"
            "# Add to your .htaccess file in the site root",
            "# GEO Checker：安全响应头 — Apache (.htaccess)\n"
            "# 添加到站点根目录的 .htaccess 文件中",
        )
        apache = (
            f"{apache_comment}\n"
            "\n"
            "<IfModule mod_headers.c>\n"
            "    Header always set Strict-Transport-Security \"max-age=31536000; includeSubDomains\"\n"
            "    Header always set Content-Security-Policy \"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline';\"\n"
            "    Header always set X-Content-Type-Options \"nosniff\"\n"
            "    Header always set X-Frame-Options \"DENY\"\n"
            "    Header always set Referrer-Policy \"strict-origin-when-cross-origin\"\n"
            "</IfModule>\n"
        )

        humans_comment = self._t(
            "# humans.txt — generated by GEO Checker\n"
            "# Place this file in your site root",
            "# humans.txt — 由 GEO Checker 生成\n"
            "# 将此文件放置在站点根目录",
        )
        humans = (
            f"{humans_comment}\n"
            "\n"
            "/* TEAM */\n"
            f"Site: {self.site.brand}\n"
            "Your Name: <your name>\n"
            "Role: <your role>\n"
            "Contact: your@email.com\n"
            "\n"
            "/* SITE */\n"
            f"Last update: {datetime.now(timezone.utc).strftime('%Y/%m/%d')}\n"
            "Standards: HTML5, CSS3\n"
        )

        return {
            "patches/security-headers-nginx.conf": nginx,
            "patches/security-headers-htaccess.txt": apache,
            "humans.txt": humans,
        }

    def _generate_sitemap_snippet(self) -> dict[str, str]:
        items = [f for f in self.fix_items if f.fix_key and "sitemap" in f.fix_key]
        if not items:
            return {}

        base = self.result.url.rstrip("/")
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        comment = self._t(
            "<!-- GEO Checker: sitemap.xml template — customize before deploying -->",
            "<!-- GEO Checker：sitemap.xml 模板 — 部署前请自行修改 -->",
        )
        content = (
            f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f"{comment}\n"
            f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"  <url>\n"
            f"    <loc>{base}/</loc>\n"
            f"    <lastmod>{today}</lastmod>\n"
            f"    <changefreq>weekly</changefreq>\n"
            f"    <priority>1.0</priority>\n"
            f"  </url>\n"
            f"  <url>\n"
            f"    <loc>{base}/about</loc>\n"
            f"    <lastmod>{today}</lastmod>\n"
            f"    <changefreq>monthly</changefreq>\n"
            f"    <priority>0.8</priority>\n"
            f"  </url>\n"
            f"  <url>\n"
            f"    <loc>{base}/contact</loc>\n"
            f"    <lastmod>{today}</lastmod>\n"
            f"    <changefreq>monthly</changefreq>\n"
            f"    <priority>0.7</priority>\n"
            f"  </url>\n"
            f"  <!-- {'在此添加更多 URL' if self.zh else 'Add more URLs here'} -->\n"
            f"</urlset>\n"
        )
        return {"sitemap.xml.example": content}

    def _generate_content_suggestions(self) -> dict[str, str]:
        items = [f for f in self.fix_items if f.fix_key and "content_quality" in f.fix_key]
        if not items:
            return {}

        brand = self.site.brand
        suggestions: list[str] = []

        heading = self._t(
            "# GEO Content Optimization Suggestions\n\n"
            "The following content improvements will boost your AI visibility. "
            "Apply them to the relevant pages on your site.\n\n",
            "# GEO 内容优化建议\n\n"
            "以下内容改进措施将提升网站的 AI 可见性。"
            "请将这些建议应用��网站的相关页面。\n\n",
        )
        suggestions.append(heading)

        for item in items:
            if item.fix_key == "result.fixes.content_quality.add_faq_section":
                suggestions.append(self._t(
                    "## FAQ Section\n\n"
                    "Add a FAQ section to your page. Format questions as headings:\n\n"
                    "```html\n"
                    "<h2>Frequently Asked Questions</h2>\n"
                    f"<h3>What is {brand}?</h3>\n"
                    "<p>Clear, concise answer...</p>\n"
                    "```\n\n"
                    "Then add FAQPage structured data (JSON-LD) for each Q&A pair.\n\n",
                    "## FAQ 区块\n\n"
                    "为页面添�� FAQ 区块，问题用标题格式：\n\n"
                    "```html\n"
                    "<h2>常见问题</h2>\n"
                    f"<h3>{brand} 是什么？</h3>\n"
                    "<p>简明扼要的回答...</p>\n"
                    "```\n\n"
                    "然后为���个问答对添加 FAQPage JSON-LD 结构化数据。\n\n",
                ))
            if item.fix_key == "result.fixes.content_quality.add_statistics":
                suggestions.append(self._t(
                    "## Add Statistics and Data Points\n\n"
                    "AI engines heavily cite pages with specific numbers. Add concrete data:\n\n"
                    "- \"95% of customers report improved performance\"\n"
                    "- \"Over 10,000 companies use our platform\"\n"
                    "- \"Reduces processing time by 3.5x\"\n\n"
                    "Replace vague claims with specific, quotable statistics.\n\n",
                    "## 添加统计数据\n\n"
                    "AI 引擎更倾向于引用包含具体数字的页面。请添加具体数据：\n\n"
                    "- \"95% 的客户反馈性能得到显著提升\"\n"
                    "- \"��过 10,000 家企业正在使用我们的平台\"\n"
                    "- \"处理��间缩短 3.5 倍\"\n\n"
                    "用具体、可引用的数据替换模糊表述。\n\n",
                ))
            if item.fix_key == "result.fixes.content_quality.add_attributions":
                suggestions.append(self._t(
                    "## Add Source Attributions\n\n"
                    "Increase credibility by citing sources:\n\n"
                    "- \"According to [Source Name], ...\"\n"
                    "- \"Data from our 2025 industry report shows...\"\n"
                    "- \"A study by [Institution] found...\"\n\n"
                    "AI engines weight attributed claims higher than unattributed ones.\n\n",
                    "## 添加来源标注\n\n"
                    "通过引用来源增强可信度：\n\n"
                    "- \"根据 [来源名称]，……\"\n"
                    "- \"我们的 2025 行业报告数���显示……\"\n"
                    "- \"[机构名称] 的一���研究发现……\"\n\n"
                    "AI 引擎对带来源的论述给予更高权重。\n\n",
                ))
            if item.fix_key == "result.fixes.content_quality.frontload_facts":
                suggestions.append(self._t(
                    "## Optimize Your Opening Paragraph\n\n"
                    "Front-load facts into your first paragraph so AI engines can extract them directly:\n\n"
                    "- Aim for one definition-style sentence in the first 25 words\n"
                    "- Include one concrete statistic in the first 25-120 words\n"
                    "- Lead with the most important information\n\n"
                    "Example opening:\n"
                    f"> {brand} is a [definition] that helps [audience] achieve [benefit]. "
                    "With [number] active users and [metric], it is trusted by [audience segment].\n\n",
                    "## 优化开头段落\n\n"
                    "在首段前置事实信息，便于 AI 引擎直接提取：\n\n"
                    "- 在前 25 个字内包含一句定义式表述\n"
                    "- 在前 25-120 字内包含至少一条具体数据\n"
                    "- 把最重要的信息放在最前面\n\n"
                    "示例开头：\n"
                    f"> {brand} 是一个 [定义]，帮助 [目标用户] 实现 [价值]。"
                    "目前已有 [数字] 活跃用户和 [指标]，深受 [用户群体] 信赖。\n\n",
                ))
            if item.fix_key == "result.fixes.content_quality.tighten_first_para":
                suggestions.append(self._t(
                    "## Tighten Opening Paragraph\n\n"
                    "Keep your first paragraph to 25-120 words so AI engines can use it as a snippet. "
                    "Cut fluff and get to the point immediately.\n\n",
                    "## 精炼开头段落\n\n"
                    "将首段控制在 25-120 字，让 AI 引擎能直接将其作为摘要引用。"
                    "删除冗余表述���直奔主题。\n\n",
                ))

        return {"content/gseo-suggestions.md": "".join(suggestions)}

    def _generate_manifest(self) -> dict[str, Any]:
        fixes: list[dict[str, Any]] = []
        for item in self.fix_items:
            affected_files: list[str] = []
            if item.fix_key:
                if "robots" in item.fix_key:
                    affected_files.append("robots.txt")
                elif "llms" in item.fix_key:
                    affected_files.append("llms.txt / llms-full.txt")
                elif "sitemap" in item.fix_key:
                    affected_files.append("sitemap.xml")
                elif "meta" in item.fix_key:
                    affected_files.append("HTML <head>")
                elif "structured" in item.fix_key:
                    affected_files.append("HTML <head> (JSON-LD)")
                elif "security" in item.fix_key:
                    affected_files.append("Server config (nginx/apache)")
                elif "humans" in item.fix_key:
                    affected_files.append("humans.txt")
                elif "content_quality" in item.fix_key:
                    affected_files.append("Page content")

            fixes.append({
                "fix_key": item.fix_key,
                "check_message": item.check_message,
                "status": item.status,
                "priority": item.priority,
                "category": item.category,
                "fix_text": item.fix_text,
                "affected_files": affected_files,
            })

        return {
            "schema_version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "url": self.result.url,
            "score": self.result.score,
            "grade": self.result.grade,
            "locale": self.locale,
            "site_info": {
                "brand": self.site.brand,
                "title": self.site.title,
                "lang": self.site.lang,
            },
            "total_fixes": len(fixes),
            "fixes": fixes,
        }

    def _generate_readme(self) -> str:
        all_pass = len(self.fix_items) == 0
        brand = self.site.brand
        base = self.result.url.rstrip("/")
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        if all_pass:
            return self._t(
                f"# GEO Fix Package — No Fixes Needed\n\n"
                f"## {self.result.url}\n\n"
                f"**Score: {self.result.score}/100 ({self.result.grade})**\n\n"
                f"Great news! All checks passed. Your site is well-optimized for AI visibility.\n\n"
                f"No file changes are required.\n\n"
                f"---\n"
                f"Generated by GEO Checker — https://www.vigilath.com\n"
                f"Timestamp: {ts}\n",
                f"# GEO 修复包 — 无需修复\n\n"
                f"## {self.result.url}\n\n"
                f"**得分：{self.result.score}/100（{self.result.grade}）**\n\n"
                f"恭喜！所有检测项均已通过，网站的 AI 可见性优化状态良好。\n\n"
                f"无需修改任何文件。\n\n"
                f"---\n"
                f"由 GEO Checker 生成 — https://www.vigilath.com\n"
                f"生成时间：{ts}\n",
            )

        title = self._t("# GEO Fix Package", "# GEO 修复包")
        target = self._t("**Target:**", "**目标网站：**")
        score_label = self._t("**Score:**", "**得分：**")
        fixes_label = self._t("**Fixes included:**", "**修复项：**")
        quickstart = self._t("## Quick Start", "## 快速开始")
        quickstart_desc = self._t(
            "Apply the files in this package to your website root. Here's a guide for each file:",
            "将此修复包中的文件部署到网站根目录。��下是各文件的使用说明：",
        )

        lines = [
            f"{title}\n\n",
            f"{target} {self.result.url}\n",
            f"{score_label} {self.result.score}/100 ({self.result.grade})\n",
            f"{fixes_label} {len(self.fix_items)}\n\n",
            f"{quickstart}\n\n",
            f"{quickstart_desc}\n\n",
        ]

        for f in self.fix_items:
            if f.fix_key and "robots" in f.fix_key:
                lines.append(self._t(
                    "### robots.txt\n"
                    f"Upload `robots.txt` to your site root (`{base}/robots.txt`).\n\n",
                    "### robots.txt\n"
                    f"将 `robots.txt` 上传到站点根目录（`{base}/robots.txt`）。\n\n",
                ))
                break

        for f in self.fix_items:
            if f.fix_key and "llms" in f.fix_key:
                lines.append(self._t(
                    "### llms.txt / llms-full.txt\n"
                    "Upload to your site root. These help AI crawlers understand your site structure.\n\n",
                    "### llms.txt / llms-full.txt\n"
                    "上传到站点根目录，帮助 AI 爬虫了解你的网站结构。\n\n",
                ))
                break

        for f in self.fix_items:
            if f.fix_key and "meta" in f.fix_key:
                lines.append(self._t(
                    "### patches/meta-tags-patch.html\n"
                    "Copy the contents into your page `<head>` section.\n\n",
                    "### patches/meta-tags-patch.html\n"
                    "将内容复制到页面的 `<head>` 区域内。\n\n",
                ))
                break

        for f in self.fix_items:
            if f.fix_key and "structured" in f.fix_key:
                lines.append(self._t(
                    "### patches/json-ld-patch.html\n"
                    "Copy the JSON-LD `<script>` blocks into your `<head>` section.\n\n",
                    "### patches/json-ld-patch.html\n"
                    "将 JSON-LD `<script>` 代码块复制到 `<head>` 区域内。\n\n",
                ))
                break

        for f in self.fix_items:
            if f.fix_key and "security" in f.fix_key:
                lines.append(self._t(
                    "### patches/security-headers-nginx.conf\n"
                    "Copy the config into your nginx server block. Test with `nginx -t` before reloading.\n\n"
                    "### patches/security-headers-htaccess.txt\n"
                    "Upload to your site root as `.htaccess` if you use Apache.\n\n",
                    "### patches/security-headers-nginx.conf\n"
                    "将配置复制到 nginx server 块中，重载前先用 `nginx -t` 测试。\n\n"
                    "### patches/security-headers-htaccess.txt\n"
                    "如果使用 Apache，将此文件上传到站点根目录作为 `.htaccess`。\n\n",
                ))
                break

        for f in self.fix_items:
            if f.fix_key and "humans" in f.fix_key:
                lines.append(self._t(
                    "### humans.txt\n"
                    f"Upload to your site root (`{base}/humans.txt`).\n\n",
                    "### humans.txt\n"
                    f"上传到站点根目录（`{base}/humans.txt`）。\n\n",
                ))
                break

        for f in self.fix_items:
            if f.fix_key and "sitemap" in f.fix_key:
                lines.append(self._t(
                    "### sitemap.xml.example\n"
                    "Rename to `sitemap.xml`, customize the URLs, then submit at:\n"
                    "- Google Search Console: https://search.google.com/search-console\n"
                    "- Bing Webmaster: https://www.bing.com/webmasters\n\n",
                    "### sitemap.xml.example\n"
                    "重命名为 `sitemap.xml`，自定义 URL 后提交至：\n"
                    "- Google Search Console：https://search.google.com/search-console\n"
                    "- Bing Webmaster：https://www.bing.com/webmasters\n\n",
                ))
                break

        for f in self.fix_items:
            if f.fix_key and "content_quality" in f.fix_key:
                lines.append(self._t(
                    "### content/gseo-suggestions.md\n"
                    "Review the content suggestions and apply them to your relevant pages.\n\n",
                    "### content/gseo-suggestions.md\n"
                    "查阅内���优化建议，并将其应用到网站的相关页面。\n\n",
                ))
                break

        lines.append("---\n")
        lines.append(self._t(
            f"Generated by GEO Checker — https://www.vigilath.com\nTimestamp: {ts}\n",
            f"由 GEO Checker 生成 — https://www.vigilath.com\n生成时间：{ts}\n",
        ))

        return "".join(lines)

    # ------------------------------------------------------------------
    # 3. Build ZIP
    # ------------------------------------------------------------------
    def build_zip(self) -> bytes:
        buf = io.BytesIO()
        domain = _domain_from_url(self.result.url)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
        zip_prefix = f"geo-fix-{domain}-{timestamp}"

        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                f"{zip_prefix}/fix-manifest.json",
                json.dumps(self._generate_manifest(), indent=2, ensure_ascii=False),
            )
            zf.writestr(f"{zip_prefix}/README.md", self._generate_readme())

            for filename, content in self._generate_robots_txt().items():
                zf.writestr(f"{zip_prefix}/{filename}", content)

            for filename, content in self._generate_llms_txt().items():
                zf.writestr(f"{zip_prefix}/{filename}", content)

            for filename, content in self._generate_meta_patches().items():
                zf.writestr(f"{zip_prefix}/{filename}", content)

            for filename, content in self._generate_jsonld_patches().items():
                zf.writestr(f"{zip_prefix}/{filename}", content)

            for filename, content in self._generate_security_config().items():
                zf.writestr(f"{zip_prefix}/{filename}", content)

            for filename, content in self._generate_sitemap_snippet().items():
                zf.writestr(f"{zip_prefix}/{filename}", content)

            for filename, content in self._generate_content_suggestions().items():
                zf.writestr(f"{zip_prefix}/{filename}", content)

        buf.seek(0)
        return buf.getvalue()
