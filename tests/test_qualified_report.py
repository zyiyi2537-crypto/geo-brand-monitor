"""Focused tests for complete, auditable AI citation reports."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "telemetry-service"))
from app.qualified_report import build_report, render_html  # noqa: E402

ARTICLE = "https://example.com/published/guide"
OTHER = "https://other.example/article"
ENGINES = ("deepseek", "doubao", "yuanbao", "wenxin", "qwen")
CONFIG = {"brand": "示例品牌", "questions": ["供应商怎么选？"],
          "articles": [{"title": "产品指南", "url": ARTICLE}]}


def row(engine: str, answer: str, status: str, brand: bool,
        *, source: str | None = None, query: str | None = None) -> dict:
    target = status == "cited"
    return {
        "engine": engine, "query": query or CONFIG["questions"][0], "answer": answer,
        "citations": [{"url": source}] if source else [], "error": None,
        "ai_verdict": {
            "brand_mentioned": brand, "citation_status": status,
            "matched_article_urls": [ARTICLE] if target else [],
            "evidence_urls": [source] if target and source else [],
            "reason": "根据本次回答的引用来源核对", "model": "my-model",
        },
    }


class QualifiedReportTests(unittest.TestCase):
    def test_qualified_question_requires_both_conditions_on_one_platform(self) -> None:
        rows = [
            row("doubao", "BRAND_ANSWER", "cited", True, source=ARTICLE),
            row("deepseek", "MENTION_ONLY_ANSWER", "not_cited", True, source=OTHER),
            row("qwen", "CITATION_ONLY_ANSWER", "cited", False, source=ARTICLE),
            row("yuanbao", "OTHER_ANSWER", "not_cited", False, source=OTHER),
        ]
        report = build_report(CONFIG, rows)
        self.assertIn("1/1（100%）", report)
        self.assertNotIn("GEO_REPORT_CHART", report)
        self.assertIn("| 已完成明确引用核对的平台结果 | 4/5 |", report)
        self.assertIn("## 全部问题核查明细", report)
        self.assertIn("| 问题 1：供应商怎么选？ | 豆包 | 已提及 | 已引用（文章 1） |", report)
        self.assertIn("| 问题 1：供应商怎么选？ | DeepSeek | 已提及 | 未引用 |", report)
        self.assertIn("| 问题 1：供应商怎么选？ | 千问 | 未提及 | 已引用（文章 1） |", report)
        self.assertIn(f"[来源 1]({ARTICLE})", report)
        for answer in ("BRAND_ANSWER", "MENTION_ONLY_ANSWER", "CITATION_ONLY_ANSWER", OTHER):
            self.assertIn(answer, report)
        for unwanted in ("my-model", "无法判断"):
            self.assertNotIn(unwanted, report)

    def test_zero_qualified_questions_keep_all_answers_and_sources(self) -> None:
        rows = [
            row("doubao", "PRIVATE_BRAND_ANSWER", "cited", False, source=ARTICLE),
            row("deepseek", "PRIVATE_MENTION_ANSWER", "not_cited", True, source=OTHER),
            *[row(engine, "PRIVATE_OTHER_ANSWER", "not_cited", False, source=OTHER)
              for engine in ("yuanbao", "wenxin", "qwen")],
        ]
        report = build_report(CONFIG, rows, completed_questions=1)
        self.assertIn("达到记录条件的问题 | 0/1（0%）", report)
        self.assertIn("本次没有问题达到记录条件", report)
        self.assertIn("供应商怎么选", report)
        self.assertIn("豆包", report)
        self.assertIn("DeepSeek", report)
        self.assertIn("PRIVATE_", report)
        self.assertIn(ARTICLE, report)
        self.assertIn(OTHER, report)
        self.assertNotIn("## 达标问题核查明细", report)
        rendered = render_html(report)
        self.assertIn("问题达标率：0/1，0%", rendered)
        self.assertIn("DeepSeek", rendered)
        self.assertIn("豆包", rendered)

    def test_all_questions_contribute_to_details_and_rates(self) -> None:
        config = {**CONFIG, "questions": ["达标问题", "只提及不引用的问题"]}
        rows = []
        for engine in ENGINES:
            rows.append(row(
                engine, "达标回答", "cited" if engine == "deepseek" else "not_cited",
                engine in ("deepseek", "doubao"),
                source=ARTICLE if engine == "deepseek" else OTHER,
                query="达标问题",
            ))
            rows.append(row(
                engine, "UNQUALIFIED_PRIVATE_ANSWER", "not_cited", engine == "qwen",
                source=OTHER, query="只提及不引用的问题",
            ))
        report = build_report(config, rows)
        self.assertIn("1/2（50%）", report)
        self.assertIn("问题 1：达标问题", report)
        self.assertIn("只提及不引用的问题", report)
        self.assertIn("UNQUALIFIED_PRIVATE_ANSWER", report)
        self.assertIn("| DeepSeek | 1/2（50%） | 1/2（50%） |", report)
        self.assertIn("| 豆包 | 1/2（50%） | 0/2（0%） |", report)

    def test_missing_verdicts_retain_answers_without_claiming_no_citation(self) -> None:
        rows = [{
            "engine": engine, "query": CONFIG["questions"][0], "answer": "BRAND_AND_URL",
            "citations": [{"url": ARTICLE}], "error": None, "ai_error": "接口超时",
        } for engine in ENGINES]
        report = build_report(CONFIG, rows)
        self.assertIn("检查已结束，尚未核实到符合条件的问题", report)
        self.assertIn("| 已完成明确引用核对的平台结果 | 0/5 |", report)
        self.assertIn("| 尚未完成引用核对的平台结果 | 5 |", report)
        self.assertNotIn("接口超时", report)
        self.assertIn("BRAND_AND_URL", report)
        self.assertNotIn("无法判断", report)
        self.assertNotIn("| 未引用 |", report)

    def test_partial_run_uses_full_question_count_as_qualification_denominator(self) -> None:
        config = {**CONFIG, "questions": ["Q1", "Q2", "Q3", "Q4"]}
        rows = [row(engine, "ANSWER", "not_cited", engine == "doubao",
                    source=OTHER, query="Q1") for engine in ENGINES]
        report = build_report(config, rows,
                              completed_questions=1)
        self.assertIn("目前还没有问题达到记录条件，检测仍在进行", report)
        self.assertIn("| 达到记录条件的问题 | 0/4（0%） |", report)
        self.assertIn("Q1", report)

    def test_uncertain_source_list_does_not_become_no_citation(self) -> None:
        partial = row("qwen", "已完成分析，共参考 29 篇资料\n回答", "not_cited", False,
                      source=OTHER)
        report = build_report(CONFIG, [partial])
        self.assertIn("0/1（0%）", report)
        self.assertIn("尚未完成引用核对的平台结果 | 5", report)
        self.assertIn("| 待核对 |", report)
        self.assertIn("供应商怎么选", report)

    def test_qualified_question_has_ai_confirmed_article_and_source_site_rankings(self) -> None:
        second_article = "https://example.com/published/second"
        config = {**CONFIG, "articles": [
            {"title": "产品指南", "url": ARTICLE},
            {"title": "第二篇指南", "url": second_article},
        ]}
        first_citation = "https://example.com/published/guide"
        second_citation = "https://example.com/guide-copy"
        third_citation = "https://example.com/guide-extra"
        shared_source = "https://news.example/story"
        rows = [
            {
                "engine": "doubao", "query": CONFIG["questions"][0], "answer": "示例品牌稳定可靠。",
                "citations": [
                    {"url": first_citation}, {"url": second_citation}, {"url": third_citation},
                    {"url": shared_source}, {"url": "https://www.news.example/other"},
                    {"url": shared_source},
                ],
                "citation_collection": {"complete": True, "expected_count": 6}, "error": None,
                "ai_verdict": {
                    "brand_mentioned": True, "citation_status": "cited",
                    "matched_article_urls": [ARTICLE, second_article],
                    "evidence_urls": [first_citation, second_citation, third_citation],
                    "matched_citations": [
                        {"article_url": ARTICLE, "citation_url": first_citation},
                        {"article_url": ARTICLE, "citation_url": second_citation},
                        {"article_url": second_article, "citation_url": third_citation},
                    ],
                    "brand_sentiment": "positive",
                    "brand_evaluation_tags": ["稳定可靠", "交付能力强"],
                    "brand_evidence_quote": "示例品牌稳定可靠。",
                },
            },
            {
                "engine": "deepseek", "query": CONFIG["questions"][0], "answer": "示例品牌被提及。",
                "citations": [{"url": shared_source}],
                "citation_collection": {"complete": False, "expected_count": 2}, "error": None,
                "ai_verdict": {
                    "brand_mentioned": True, "citation_status": "not_cited",
                    "matched_article_urls": [], "evidence_urls": [], "matched_citations": [],
                    "brand_sentiment": "neutral", "brand_evaluation_tags": ["僅提及，未評價"],
                    "brand_evidence_quote": "示例品牌被提及。",
                },
            },
        ]

        report = build_report(config, rows, completed_questions=1)
        self.assertIn("| 1 | [产品指南](https://example.com/published/guide) | 1 | 2 |", report)
        self.assertIn("| 2 | [第二篇指南](https://example.com/published/second) | 1 | 1 |", report)
        self.assertIn("AI 确认引用链接数", report)
        self.assertIn("https://news.example", report)
        self.assertIn("| 1 | [news\\.example](https://news.example) | 2 | 3 | 2/2（100%） |", report)
        self.assertIn("引用采集状态：已取得回答 2/5 个平台，其中完整 1 个、不完整 1 个", report)
        self.assertIn("正面", report)
        self.assertIn("稳定可靠", report)
        self.assertIn("交付能力强", report)
        self.assertIn("“示例品牌稳定可靠。”", report)
        self.assertIn("中性", report)
        self.assertIn("“示例品牌被提及。”", report)

        rendered = render_html(report)
        self.assertIn("<h4>目标文章排名</h4>", rendered)
        self.assertIn("<h4>来源网站排名</h4>", rendered)
        self.assertIn("https://news.example", rendered)
        self.assertIn('class="rank-track" role="meter"', rendered)

    def test_html_has_self_contained_percentage_chart_and_safe_question_text(self) -> None:
        question = '<script>alert(1)</script> | 供应商？'
        config = {**CONFIG, "questions": [question]}
        rows = [row("doubao", "DO_NOT_RENDER_ANSWER", "cited", True, source=ARTICLE,
                    query=question)]
        report = render_html(build_report(config, rows))
        self.assertIn("class=\"report-chart\"", report)
        self.assertIn("role=\"meter\"", report)
        self.assertIn("aria-valuenow=\"100\"", report)
        self.assertIn("100%", report)
        self.assertIn("&lt;script&gt;", report)
        self.assertNotIn("<script>", report)
        self.assertIn("DO_NOT_RENDER_ANSWER", report)
        self.assertIn(f'href="{ARTICLE}"', report)
        self.assertNotIn("<script src=", report)

    def test_report_without_custom_chart_directive_still_renders_older_markdown(self) -> None:
        report = render_html("# 旧 GEO 记录\n\n## 已引用记录\n\n| 结果 |\n| --- |\n| 已引用 |\n")
        self.assertIn("<h1>旧 GEO 记录</h1>", report)
        self.assertIn("<h2>已引用记录</h2>", report)
        self.assertIn("已引用", report)

    def test_html_preserves_unqualified_answer_all_sources_and_saved_evidence(self) -> None:
        with TemporaryDirectory() as directory:
            screenshot = Path(directory) / "saved.png"
            screenshot.write_bytes(b"saved evidence")
            saved = row("doubao", "第一段原文\n第二段原文 <script>bad()</script>",
                        "not_cited", True, source=OTHER)
            saved.update({"source_url": "https://chat.example/conversation",
                          "screenshot": "saved.png", "page_evidence": "not-saved.txt"})
            saved["citations"] = [{"url": f"https://source.example/{i}", "title": f"来源文章{i}"}
                                  for i in range(150)]
            saved["citation_collection"] = {"complete": True, "expected_count": 150}
            rendered = render_html(build_report(CONFIG, [saved]), config=CONFIG,
                                   results=[saved], report_directory=directory)
            self.assertIn('id="q1-doubao"', rendered)
            self.assertIn('href="#q1-doubao"', rendered)
            self.assertIn("第一段原文\n第二段原文 &lt;script&gt;bad()&lt;/script&gt;", rendered)
            self.assertNotIn("<script>", rendered)
            self.assertIn("全部引用来源（150 条）", rendered)
            self.assertIn("来源文章149", rendered)
            self.assertIn(screenshot.as_uri(), rendered)
            self.assertNotIn("not-saved.txt", rendered)
            self.assertIn("打开实际会话", rendered)
            self.assertIn("品牌已提及 · 未引用", rendered)
            self.assertIn("来源文章排名", rendered)

    def test_article_ranking_deduplicates_platform_coverage_without_discarding_sources(self) -> None:
        rows = [row("doubao", "回答一", "not_cited", True, source=OTHER),
                row("deepseek", "回答二", "not_cited", False, source=OTHER)]
        rows[0]["citations"] = [{"url": OTHER, "title": "共同来源"},
                                 {"url": OTHER, "title": "共同来源"},
                                 {"url": "https://single.example/source", "title": "单平台来源"}]
        report = build_report(CONFIG, rows)
        self.assertIn("| 1 | [共同来源](https://other.example/article) | other\\.example | 2 | 2/2（100%） | DeepSeek、豆包 |", report)
        rendered = render_html(report, config=CONFIG, results=rows)
        self.assertIn("全部引用来源（3 条）", rendered)
        self.assertIn("共同来源", rendered)

    def test_answer_code_fence_cannot_inject_html_or_truncate_the_answer(self) -> None:
        answer = "第一段\n```\n</pre><script>bad()</script>\n````\n最后一段"
        rows = [row("doubao", answer, "not_cited", True, source=OTHER)]
        rendered = render_html(build_report(CONFIG, rows))
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;/pre&gt;&lt;script&gt;bad()&lt;/script&gt;", rendered)
        self.assertIn("最后一段", rendered)


if __name__ == "__main__":
    unittest.main()
