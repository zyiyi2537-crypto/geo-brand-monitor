"""End-to-end tests for the lightweight GEO record client."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading
import unittest
from datetime import datetime, timezone
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import geo_record  # noqa: E402


ARTICLE = "https://example.com/published/article"
ENGINES = list(geo_record.ENGINES)


class BrowserHandler(BaseHTTPRequestHandler):
    calls: list[tuple[str, str]] = []
    mode = "normal"
    failed_session: str | None = None

    def log_message(self, format: str, *args: object) -> None:
        pass

    def _send(self, value: object) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.endswith("/sessions/verify"):
            self._send([{
                "engine": engine,
                "name": geo_record.ENGINE_DISPLAY_NAMES[engine],
                "status": "expired" if engine == self.failed_session else "ok",
                "logged_in": engine != self.failed_session,
                "detail": "页面未显示可用对话输入框" if engine == self.failed_session else "登录态可用",
            } for engine in ENGINES])
        else:
            self._send({"region": "cn", "engines": ENGINES})

    def do_POST(self) -> None:
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        engine, query = request["engine"], request["query"]
        self.calls.append((engine, query))
        if self.mode == "failure":
            self._send({"engine": engine, "query": query, "answer": "", "citations": [],
                        "error": "登录失效"})
            return
        if self.mode == "mismatch" and engine == "deepseek":
            self._send({"engine": "doubao", "query": query, "answer": "示例品牌",
                        "citations": [{"url": ARTICLE}], "error": None})
            return
        if self.mode == "full_sources":
            self._send({
                "engine": engine, "query": query, "answer": "已完成回答，共参考150篇资料",
                "citations": [{"url": f"https://source.example/{i}", "title": f"文章{i}"}
                              for i in range(150)],
                "citation_collection": {"complete": True, "expected_count": 150, "captured_count": 150},
                "source_url": "https://chat.example/conversation", "error": None,
            })
            return
        if self.mode == "display_names":
            engine_name = geo_record.ENGINE_DISPLAY_NAMES[engine]
        else:
            engine_name = engine
        qualified = query == "合格问题" and engine == "deepseek"
        self._send({
            "engine": engine_name, "query": query,
            "answer": "示例品牌的产品适合这个场景。" if qualified or engine == "qwen" else "其他产品。",
            "citations": [{"url": ARTICLE}] if qualified else [],
            "error": None,
        })


class GeoRecordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), BrowserHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def setUp(self) -> None:
        BrowserHandler.calls = []
        BrowserHandler.mode = "normal"
        BrowserHandler.failed_session = None
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config_path = Path(self.temp.name) / "config.json"
        self.config_path.write_text(json.dumps({
            "brand": "示例品牌",
            "questions": ["合格问题", "不合格问题"],
            "articles": [{"title": "已发布文章", "url": ARTICLE}],
        }, ensure_ascii=False), encoding="utf-8")
        self.config = geo_record.load_config(self.config_path)

    def test_collects_five_platforms_and_keeps_all_question_details(self) -> None:
        def ai_result(**kwargs: object) -> dict:
            query = kwargs["question"]
            return {
                engine: {
                    "brand_mentioned": query == "合格问题" and engine == "deepseek",
                    "citation_status": "cited" if query == "合格问题" and engine == "deepseek" else "uncertain",
                    "matched_article_urls": [ARTICLE] if query == "合格问题" and engine == "deepseek" else [],
                    "evidence_urls": [ARTICLE] if query == "合格问题" and engine == "deepseek" else [],
                    "matched_citations": ([{"article_url": ARTICLE, "citation_url": ARTICLE}]
                                          if query == "合格问题" and engine == "deepseek" else []),
                    "brand_sentiment": "positive" if query == "合格问题" and engine == "deepseek" else None,
                    "brand_evaluation_tags": ["场景适配"]
                    if query == "合格问题" and engine == "deepseek" else [],
                    "brand_evidence_quote": "示例品牌的产品适合这个场景。"
                    if query == "合格问题" and engine == "deepseek" else None,
                    "reason": "模拟模型判定", "model": "test-model",
                }
                for engine in ENGINES
            }

        with patch.object(geo_record, "verify_question", side_effect=ai_result) as verify:
            rows = geo_record.collect_results(
                self.config, self.base_url,
                ai_settings={"base_url": "https://model.example/v1", "api_key": "test", "model": "test-model"},
            )
        self.assertEqual(verify.call_count, 2)
        self.assertEqual(len(rows), 10)
        self.assertEqual(set(BrowserHandler.calls), {
            (engine, query) for engine in ENGINES for query in self.config["questions"]
        })
        paths = geo_record.write_record(self.config, rows, self.temp.name)
        report = paths["markdown"].read_text(encoding="utf-8")
        self.assertIn("| 达到记录条件的问题 | 1/2（50%） |", report)
        self.assertIn("| 问题 1：合格问题 | DeepSeek | 已提及 | 已引用（文章 1） |", report)
        self.assertIn("目标文章排名", report)
        self.assertIn("来源网站排名", report)
        self.assertIn("场景适配", report)
        self.assertIn("示例品牌的产品适合这个场景", report)
        self.assertIn("不合格问题", report)
        self.assertIn(f"[来源 1]({ARTICLE})", report)
        self.assertIn("模拟模型判定", report)
        self.assertNotIn("test-model", report)
        self.assertTrue(paths["html"].read_text(encoding="utf-8").startswith("<!doctype html>"))
        self.assertEqual(sorted(path.name for path in paths["directory"].iterdir()),
                         ["record.html", "record.md"])

    def test_mismatched_response_is_an_error_and_never_qualifies(self) -> None:
        BrowserHandler.mode = "mismatch"
        rows = geo_record.collect_results(self.config, self.base_url)
        mismatch = next(row for row in rows if row["engine"] == "deepseek" and
                        row["query"] == "合格问题")
        self.assertIn("不一致", mismatch["error"])
        report = geo_record.write_record(self.config, rows, self.temp.name)["markdown"].read_text(
            encoding="utf-8"
        )
        self.assertIn("尚未核实到符合条件的问题", report)
        self.assertIn("尚未完成引用核对的平台结果 | 10", report)
        self.assertIn("合格问题", report)
        self.assertNotIn("| 未引用 |", report)

    def test_search_preserves_full_source_list_and_collection_metadata(self) -> None:
        BrowserHandler.mode = "full_sources"
        row = geo_record._search_one(self.base_url, "doubao", "核对全部来源", 5)
        self.assertIsNone(row["error"])
        self.assertEqual(len(row["citations"]), 150)
        self.assertEqual(row["citations"][-1]["url"], "https://source.example/149")
        self.assertTrue(row["citation_collection"]["complete"])
        self.assertEqual(row["citation_collection"]["expected_count"], 150)
        self.assertEqual(row["source_url"], "https://chat.example/conversation")

    def test_failed_batch_rechecks_saved_answers_and_isolates_platform_failure(self) -> None:
        def verify(**kwargs: object) -> dict:
            rows = kwargs["rows"]
            if len(rows) > 1:
                raise ValueError("batch timed out")
            engine = rows[0]["engine"]
            if engine == "yuanbao":
                raise ValueError("provider unavailable")
            return {engine: {"citation_status": "uncertain", "brand_mentioned": False,
                             "matched_article_urls": [], "evidence_urls": [], "reason": "无来源"}}

        config = {**self.config, "questions": ["合格问题"]}
        with patch.object(geo_record, "verify_question", side_effect=verify):
            rows = geo_record.collect_results(config, self.base_url, ai_settings={})
        self.assertEqual(len(BrowserHandler.calls), 5)
        self.assertEqual(sum("ai_verdict" in row for row in rows), 4)
        failed = next(row for row in rows if row["engine"] == "yuanbao")
        self.assertEqual(failed["ai_error"], "provider unavailable")

    def test_accepts_platform_display_names_from_live_browser_service(self) -> None:
        BrowserHandler.mode = "display_names"
        rows = geo_record.collect_results(self.config, self.base_url)
        self.assertEqual(sum(not row["error"] for row in rows), 10)
        report = geo_record.write_record(self.config, rows, self.temp.name)["markdown"].read_text(
            encoding="utf-8"
        )
        self.assertIn("尚未核实到符合条件的问题", report)
        self.assertIn("尚未完成引用核对的平台结果 | 10", report)

    def test_login_preflight_blocks_queries_and_saves_actionable_report(self) -> None:
        BrowserHandler.failed_session = "doubao"
        with patch.object(geo_record, "check_model"), patch.dict(
            geo_record.os.environ, {"GEO_AI_BASE_URL": "https://model.example/v1",
                                    "GEO_AI_MODEL": "test-model", "GEO_AI_API_KEY": "test"},
        ):
            code = geo_record.main([
                "run", "--config", str(self.config_path), "--output-dir", self.temp.name,
                "--browser-url", self.base_url,
            ])
        self.assertEqual(code, 2)
        self.assertEqual(BrowserHandler.calls, [])
        reports = list(Path(self.temp.name).glob("geo-record-*/record.md"))
        self.assertEqual(len(reports), 1)
        report = reports[0].read_text(encoding="utf-8")
        self.assertIn("未开始：登录预检未通过", report)
        self.assertIn("已完成明确引用核对的平台结果 | 0/10", report)
        self.assertIn("尚未完成引用核对的平台结果 | 10", report)
        self.assertIn("平台问题尚未发送，当前没有达标记录", report)
        self.assertNotIn("| 未引用 |", report)
        self.assertIn("问题尚未发送", report)

    def test_logged_in_but_not_ready_blocks_all_queries(self) -> None:
        sessions = [{"engine": engine, "status": "ok", "logged_in": True}
                    for engine in ENGINES]
        sessions[-1].update(status="unavailable", ready=False, detail="对话页面尚未就绪")
        with patch.object(geo_record, "_check_sessions", return_value=sessions):
            with self.assertRaisesRegex(RuntimeError, "页面尚未就绪"):
                geo_record.collect_results(self.config, self.base_url)
        self.assertEqual(BrowserHandler.calls, [])

    def test_all_failed_writes_inconclusive_report(self) -> None:
        BrowserHandler.mode = "failure"
        with patch.object(geo_record, "check_model"), patch.dict(
            geo_record.os.environ, {"GEO_AI_BASE_URL": "https://model.example/v1",
                                    "GEO_AI_MODEL": "test-model", "GEO_AI_API_KEY": "test"},
        ):
            code = geo_record.main([
                "run", "--config", str(self.config_path), "--output-dir", self.temp.name,
                "--browser-url", self.base_url,
            ])
        self.assertEqual(code, 0)
        reports = list(Path(self.temp.name).glob("geo-record-*/record.html"))
        self.assertEqual(len(reports), 1)
        report = reports[0].read_text(encoding="utf-8")
        self.assertIn("尚未核实到符合条件的问题", report)
        self.assertNotIn("无法判断", report)
        self.assertNotIn("| 未引用 |", report)

    def test_progress_callback_writes_report_after_each_question(self) -> None:
        progress: list[int] = []
        rows = geo_record.collect_results(
            self.config,
            self.base_url,
            on_question=lambda current, completed: progress.append(completed),
        )
        self.assertEqual(progress, [1, 2])
        self.assertEqual(len(rows), 10)

    def test_save_run_progress_writes_readable_and_raw_files(self) -> None:
        rows = [
            {"engine": "deepseek", "query": "合格问题", "answer": "", "citations": [],
             "error": "登录失效"},
        ]
        directory = Path(self.temp.name) / "geo-record-progress"
        directory.mkdir()
        geo_record.save_run_progress(
            directory, self.config, rows, 1, datetime.now(timezone.utc),
        )
        self.assertTrue((directory / "record.html").exists())
        self.assertTrue((directory / "record.md").exists())
        self.assertTrue((directory / "results.json").exists())
        report = (directory / "record.md").read_text(encoding="utf-8")
        self.assertIn("目前还没有问题达到记录条件，检测仍在进行", report)
        self.assertIn("达到记录条件的问题 | 0/2（0%）", report)
        self.assertIn("尚未完成引用核对的平台结果 | 10", report)

    def test_technical_details_stay_in_raw_data_and_snapshot_excludes_model_key(self) -> None:
        directory = Path(self.temp.name) / "geo-record-details"
        directory.mkdir()
        config = {**self.config, "api_key": "SECRET_DO_NOT_SAVE"}
        rows = [{"engine": "doubao", "query": "合格问题", "answer": "", "citations": [],
                 "error": "INTERNAL_LONG_BROWSER_ERROR", "ai_error": "INTERNAL_MODEL_ERROR"}]
        geo_record.save_run_progress(directory, config, rows, 1, datetime.now(timezone.utc),
                                     run_error="INTERNAL_RUN_ERROR")
        report = (directory / "record.md").read_text(encoding="utf-8")
        saved = (directory / "results.json").read_text(encoding="utf-8")
        data = json.loads(saved)
        self.assertIn("已中断", report)
        self.assertIn("运行状态：已中断", (directory / "record.html").read_text(encoding="utf-8"))
        for error in ("INTERNAL_LONG_BROWSER_ERROR", "INTERNAL_MODEL_ERROR", "INTERNAL_RUN_ERROR"):
            self.assertNotIn(error, report)
            self.assertIn(error, saved)
        self.assertEqual(data["config"], self.config)
        self.assertNotIn("SECRET_DO_NOT_SAVE", saved)

    def test_initial_report_does_not_claim_no_match_before_queries_finish(self) -> None:
        directory = Path(self.temp.name) / "geo-record-initial"
        directory.mkdir()
        geo_record.save_run_progress(directory, self.config, [], 0, datetime.now(timezone.utc))
        report = (directory / "record.md").read_text(encoding="utf-8")
        self.assertIn("正在等待第一个问题", report)
        self.assertIn("正在等待第一个问题", (directory / "record.html").read_text(encoding="utf-8"))
        self.assertIn("达到记录条件的问题 | 0/2（0%）", report)
        self.assertNotIn("本次没有符合记录条件的问题", report)

    def test_rejects_toutiao_preview_url(self) -> None:
        self.config_path.write_text(json.dumps({
            "brand": "示例品牌", "questions": ["问题"],
            "articles": [{"url": "https://mp.toutiao.com/profile_v4/graphic/preview?pgc_id=123456789012"}],
        }), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "后台预览"):
            geo_record.load_config(self.config_path)

    def test_rejects_empty_config_values(self) -> None:
        self.config_path.write_text(json.dumps({
            "brand": " ", "questions": ["问题"], "articles": [{"url": ARTICLE}],
        }), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "brand"):
            geo_record.load_config(self.config_path)


if __name__ == "__main__":
    unittest.main()
