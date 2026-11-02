"""Focused tests for qualification-gated local history trends."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.history_trends import available_brands, build_trend_html  # noqa: E402


ENGINES = ("deepseek", "doubao", "yuanbao", "wenxin", "qwen")
ARTICLE = "https://publisher.example/article/one"
QUESTION = "光芯片企业怎么选？"


def make_row(engine: str, query: str, *, brand: bool = False, status: str = "not_cited",
             source: str | None = None, model: str = "model-a", mapping: bool = True,
             sentiment: str | None = None, tags: list[str] | None = None) -> dict:
    verdict = {
        "brand_mentioned": brand,
        "citation_status": status,
        "matched_article_urls": [ARTICLE] if status == "cited" else [],
        "evidence_urls": [source] if status == "cited" and source else [],
        "model": model,
    }
    if mapping:
        verdict["matched_citations"] = (
            [{"article_url": ARTICLE, "citation_url": source}]
            if status == "cited" and source else []
        )
    if sentiment is not None:
        verdict["brand_sentiment"] = sentiment
        verdict["brand_evaluation_tags"] = tags or ["交付稳定"]
    return {
        "engine": engine, "query": query, "answer": "示例品牌交付稳定。" if brand else "其他回答。",
        "citations": [{"url": source}] if source else [], "ai_verdict": verdict,
    }


def full_run(*, when: str, brand: str = "示例品牌", questions: list[str] | None = None,
             articles: list[str] | None = None, rows: list[dict] | None = None,
             completed: int | None = None, error: str | None = None,
             folder: str | None = None) -> tuple[str, dict]:
    questions = questions or [QUESTION]
    data = {
        "generated_at": when,
        "brand": brand,
        "config": {"brand": brand, "questions": questions,
                   "articles": [{"title": url, "url": url} for url in (articles or [ARTICLE])]},
        "completed_questions": len(questions) if completed is None else completed,
        "total_questions": len(questions), "run_error": error, "results": rows or [],
    }
    return folder or "", data


def save_run(root: Path, data: dict, folder: str) -> None:
    directory = root / folder
    directory.mkdir(parents=True)
    (directory / "results.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


class HistoryTrendsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.now = datetime(2026, 10, 15, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _qualified_rows(self, query: str = QUESTION, *, source: str = "https://www.alpha.example/a",
                        model: str = "model-a", mapping: bool = True) -> list[dict]:
        return [
            make_row("deepseek", query, brand=True, status="cited", source=source,
                     model=model, mapping=mapping, sentiment="positive", tags=["交付稳定"]),
            *[make_row(engine, query, source=source, model=model)
              for engine in ENGINES[1:]],
        ]

    def test_complete_batch_rate_and_gate_hide_unqualified_question_details(self) -> None:
        second = "品牌没有引用的私密问题"
        rows = self._qualified_rows()
        rows.extend(make_row(engine, second, brand=True, status="not_cited", source="https://private.example/x")
                    for engine in ENGINES)
        _, data = full_run(when="2026-10-14T09:00:00+08:00", questions=[QUESTION, second], rows=rows)
        save_run(self.root, data, "geo-record-20261014-010000-a")

        html = build_trend_html(self.root, brand="示例品牌", now=self.now)
        self.assertIn("1/2（50.0%）", html)
        self.assertIn(QUESTION, html)
        self.assertNotIn(second, html)
        self.assertNotIn("private.example", html)
        self.assertIn("仅统计完整结束的检测批次", html)

    def test_partial_run_can_show_confirmed_hit_but_not_enter_batch_rate(self) -> None:
        rows = [self._qualified_rows()[0]]
        _, data = full_run(when="2026-10-14T09:00:00+08:00", rows=rows, completed=0,
                           error="interrupted")
        save_run(self.root, data, "geo-record-20261014-010000-partial")

        html = build_trend_html(self.root, now=self.now)
        self.assertIn("问题已达标", html)
        self.assertIn("本次检测未完整结束", html)
        self.assertIn("没有完整且至少含一个可判问题的检测批次", html)
        self.assertIn("alpha.example", html)

    def test_question_and_target_article_changes_start_separate_series(self) -> None:
        newer_article = "https://publisher.example/article/two"
        first = full_run(when="2026-10-13T09:00:00+08:00", rows=self._qualified_rows())[1]
        second = full_run(
            when="2026-10-14T09:00:00+08:00", questions=["  光芯片企业怎么选？  "],
            articles=[newer_article],
            rows=[make_row(row["engine"], "  光芯片企业怎么选？  ", brand=row["engine"] == "deepseek",
                           status="cited" if row["engine"] == "deepseek" else "not_cited",
                           source="https://beta.example/new", model="model-b",
                           sentiment="negative" if row["engine"] == "deepseek" else None,
                           tags=["响应较慢"] if row["engine"] == "deepseek" else None)
                  for row in self._qualified_rows()],
        )[1]
        save_run(self.root, first, "geo-record-20261013-010000-old")
        save_run(self.root, second, "geo-record-20261014-010000-new")

        html = build_trend_html(self.root, now=self.now)
        self.assertEqual(html.count('class="query-series"'), 2)
        self.assertIn(ARTICLE, html)
        self.assertIn(newer_article, html)
        self.assertIn("模型变化", html)

    def test_ai_article_mapping_and_site_rank_changes_are_reported(self) -> None:
        old = full_run(when="2026-10-13T09:00:00+08:00",
                       rows=self._qualified_rows(source="https://www.alpha.example/a"))[1]
        new = full_run(when="2026-10-14T09:00:00+08:00",
                       rows=self._qualified_rows(source="https://beta.example/b", model="model-b"))[1]
        save_run(self.root, old, "geo-record-20261013-010000-old")
        save_run(self.root, new, "geo-record-20261014-010000-new")

        html = build_trend_html(self.root, now=self.now)
        self.assertIn("alpha.example", html)
        self.assertIn("beta.example", html)
        self.assertNotIn("www.alpha.example", html)
        self.assertIn("新增", html)
        self.assertIn("目标文章排名变化", html)
        self.assertIn("正面", html)
        self.assertIn("交付稳定", html)
        self.assertIn("./geo-record-20261014-010000-new/record.html", html)

    def test_legacy_article_urls_without_ai_pair_mapping_are_not_script_matched(self) -> None:
        rows = self._qualified_rows(source="https://publisher.example/redirect", mapping=False)
        legacy = full_run(when="2026-10-14T09:00:00+08:00", rows=rows)[1]
        save_run(self.root, legacy, "geo-record-20261014-010000-legacy")

        html = build_trend_html(self.root, now=self.now)
        self.assertIn("历史数据缺少完整的 AI 文章与引用链接配对，排名不可用", html)
        self.assertIn("publisher.example", html)

    def test_unknown_verdicts_are_not_zero_and_user_text_is_escaped(self) -> None:
        rows = [
            make_row("deepseek", "<问题 & 关键词>", brand=True, status="cited", source="https://x.example"),
            make_row("deepseek", "未完成核查的问题", brand=True, status="uncertain", source="https://hidden.example"),
        ]
        _, data = full_run(when="2026-10-14T09:00:00+08:00", brand="<script>alert(1)</script>",
                           questions=["<问题 & 关键词>", "未完成核查的问题"], rows=rows, completed=2)
        save_run(self.root, data, "geo-record-20261014-010000-unknown")

        html = build_trend_html(self.root, brand="<script>alert(1)</script>", now=self.now)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertIn("&lt;问题 &amp; 关键词&gt;", html)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertNotIn("未完成核查的问题", html)
        self.assertIn("1/1（100.0%）", html)

    def test_brand_and_days_filters(self) -> None:
        recent = full_run(when="2026-10-14T09:00:00+08:00", rows=self._qualified_rows())[1]
        old = full_run(when="2026-08-01T09:00:00+08:00", brand="其他品牌",
                       rows=self._qualified_rows())[1]
        save_run(self.root, recent, "geo-record-20261014-010000-recent")
        save_run(self.root, old, "geo-record-20260801-010000-old")
        self.assertEqual(set(available_brands(self.root)), {"示例品牌", "其他品牌"})
        html = build_trend_html(self.root, brand="示例品牌", days=30, now=self.now)
        self.assertIn("1 个检测批次", html)
        self.assertNotIn("其他品牌", html)

    def test_missing_article_configuration_does_not_enter_query_trends(self) -> None:
        _, data = full_run(when="2026-10-14T09:00:00+08:00", rows=self._qualified_rows())
        data["config"]["articles"] = []
        save_run(self.root, data, "geo-record-20261014-010000-no-articles")
        html = build_trend_html(self.root, now=self.now)
        self.assertIn("没有可展示的达标问题趋势", html)


if __name__ == "__main__":
    unittest.main()

