"""Check model evidence handling before it can mark a citation as confirmed."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from tools.ai_verifier import verify_question


ARTICLE = "https://publisher.example/article/example-article/"
MOBILE = "https://m.publisher.example/article/example-article/"
CONFIG = {"brand": "示例品牌", "articles": [{"title": "已发布文章", "url": ARTICLE}]}
ROWS = [{"engine": "doubao", "answer": "示例品牌有量产能力。",
         "citations": [{"url": MOBILE, "title": "文章来源"}], "error": None}]


def reply(*, source: str = MOBILE, status: str = "cited", brand_mentioned: bool = True,
          sentiment: str = "positive", tags: list[str] | None = None,
          quote: str | None = "示例品牌有量产能力。", pairs: list[dict] | None = None) -> str:
    targets = [ARTICLE] if status == "cited" else []
    sources = [source] if status == "cited" else []
    citation_pairs = pairs if pairs is not None else (
        [{"article_url": ARTICLE, "citation_url": source}] if status == "cited" else [])
    if not brand_mentioned:
        sentiment, tags, quote = None, [], None
    return json.dumps({"verdicts": [{
        "engine": "doubao", "brand_mentioned": brand_mentioned,
        "citation_status": status,
        "matched_citations": citation_pairs,
        "matched_article_urls": targets,
        "evidence_urls": sources,
        "reason": "移动版与目标文章对应",
        "brand_sentiment": sentiment,
        "brand_evaluation_tags": tags if tags is not None else ["量产能力强"],
        "brand_evidence_quote": quote,
    }]}, ensure_ascii=False)


class AiVerifierTests(unittest.TestCase):
    def test_other_brand_analysis_is_saved_without_changing_citation_verdict(self) -> None:
        payload = json.loads(reply())
        payload['verdicts'][0]['mentioned_brands'] = [
            {'name': '示例品牌', 'aliases': ['示例品牌'], 'evidence_quote': ROWS[0]['answer']}]
        with patch('tools.ai_verifier._chat', return_value=json.dumps(payload)):
            verdict = self.run_verification()['doubao']
        self.assertEqual(verdict['mentioned_brands'][0]['name'], '示例品牌')
        self.assertEqual(verdict['citation_status'], 'cited')
        payload['verdicts'][0]['mentioned_brands'][0]['evidence_quote'] = '不存在的摘录'
        with patch('tools.ai_verifier._chat', return_value=json.dumps(payload)):
            verdict = self.run_verification()['doubao']
        self.assertEqual(verdict['citation_status'], 'cited')
        self.assertIn('brand_mentions_error', verdict)
        self.assertNotIn('mentioned_brands', verdict)

    def test_responses_protocol_is_forwarded_to_the_shared_client(self) -> None:
        with patch("tools.ai_verifier.chat_content", return_value=reply()) as send:
            verify_question(config=CONFIG, question="光芯片哪家好？", rows=ROWS,
                            base_url="https://model.example/v1", api_key="test", model="test-model", wire_api="responses")
        self.assertEqual(send.call_args.kwargs["wire_api"], "responses")

    def run_verification(self) -> dict:
        return verify_question(config=CONFIG, question="光芯片哪家好？", rows=ROWS,
                               base_url="https://model.example/v1", api_key="test", model="test-model")

    def test_accepts_model_judgment_with_captured_citation_evidence(self) -> None:
        with patch("tools.ai_verifier._chat", return_value=reply()):
            verdict = self.run_verification()["doubao"]
        self.assertEqual(verdict["citation_status"], "cited")
        self.assertEqual(verdict["matched_citations"], [{"article_url": ARTICLE, "citation_url": MOBILE}])
        self.assertEqual(verdict["matched_article_urls"], [ARTICLE])
        self.assertEqual(verdict["evidence_urls"], [MOBILE])
        self.assertEqual(verdict["brand_sentiment"], "positive")
        self.assertEqual(verdict["brand_evaluation_tags"], ["量产能力强"])
        self.assertEqual(verdict["brand_evidence_quote"], "示例品牌有量产能力。")

    def test_brand_not_mentioned_has_no_evaluation_fields(self) -> None:
        rows = [{**ROWS[0], "answer": "该行业有多家企业。"}]
        with patch("tools.ai_verifier._chat", return_value=reply(brand_mentioned=False)):
            verdict = verify_question(config=CONFIG, question="测试", rows=rows,
                                      base_url="https://model.example/v1", api_key="test", model="test-model")["doubao"]
        self.assertFalse(verdict["brand_mentioned"])
        self.assertIsNone(verdict["brand_sentiment"])
        self.assertEqual(verdict["brand_evaluation_tags"], [])
        self.assertIsNone(verdict["brand_evidence_quote"])

    def test_rejects_brand_evidence_quote_not_in_answer(self) -> None:
        with patch("tools.ai_verifier._chat", return_value=reply(quote="示例品牌交付很稳定。")):
            with self.assertRaisesRegex(ValueError, "不是回答中的原文"):
                self.run_verification()

    def test_rejects_invalid_brand_sentiment(self) -> None:
        with patch("tools.ai_verifier._chat", return_value=reply(sentiment="mostly_positive")):
            with self.assertRaisesRegex(ValueError, "评价倾向无效"):
                self.run_verification()

    def test_rejects_model_hallucinated_evidence_url(self) -> None:
        with patch("tools.ai_verifier._chat", return_value=reply(source="https://other.example/article")):
            with self.assertRaisesRegex(ValueError, "不存在的网址"):
                self.run_verification()

    def test_rejects_unpaired_citation_even_if_urls_are_allowed(self) -> None:
        inconsistent_pairs = [{"article_url": ARTICLE, "citation_url": "https://m.toutiao.com/other"}]
        with patch("tools.ai_verifier._chat", return_value=reply(pairs=inconsistent_pairs)):
            with self.assertRaisesRegex(ValueError, "不存在的网址配对"):
                self.run_verification()

    def test_preserves_each_confirmed_article_to_source_pair(self) -> None:
        second_article = "https://www.toutiao.com/article/second/"
        second_source = "https://m.toutiao.com/isecond/"
        config = {"brand": "示例品牌", "articles": [
            {"title": "文章一", "url": ARTICLE}, {"title": "文章二", "url": second_article},
        ]}
        rows = [{**ROWS[0], "citations": [
            {"url": MOBILE, "title": "来源一"}, {"url": second_source, "title": "来源二"},
        ]}]
        pairs = [
            {"article_url": ARTICLE, "citation_url": MOBILE},
            {"article_url": second_article, "citation_url": second_source},
        ]
        payload = reply()
        parsed = json.loads(payload)
        parsed["verdicts"][0]["matched_citations"] = pairs
        parsed["verdicts"][0]["matched_article_urls"] = [ARTICLE, second_article]
        parsed["verdicts"][0]["evidence_urls"] = [MOBILE, second_source]
        with patch("tools.ai_verifier._chat", return_value=json.dumps(parsed)):
            result = verify_question(config=config, question="测试", rows=rows,
                                     base_url="https://model.example/v1", api_key="test", model="test-model")
        self.assertEqual(result["doubao"]["matched_citations"], pairs)

    def test_rejects_no_citation_claim_without_citation_data(self) -> None:
        without_citations = [{**ROWS[0], "citations": []}]
        with patch("tools.ai_verifier._chat", return_value=reply(status="not_cited")):
            with self.assertRaisesRegex(ValueError, "没有引用数据"):
                verify_question(config=CONFIG, question="光芯片哪家好？", rows=without_citations,
                                base_url="https://model.example/v1", api_key="test", model="test-model")

    def test_incomplete_reference_list_cannot_be_confirmed_not_cited(self) -> None:
        rows = [{**ROWS[0], "answer": "已完成分析，共参考 9 篇资料\n示例品牌有量产能力。"}]
        with patch("tools.ai_verifier._chat", return_value=reply(status="not_cited")) as chat:
            result = verify_question(config=CONFIG, question="光芯片哪家好？", rows=rows,
                                     base_url="https://model.example/v1", api_key="test", model="test-model")
        self.assertEqual(result["doubao"]["citation_status"], "uncertain")
        self.assertIn("9 篇", result["doubao"]["reason"])
        self.assertIn('"captured_reference_count": 1', chat.call_args.kwargs["prompt"])

    def test_all_sources_are_sent_to_ai_including_last_entry(self) -> None:
        citations = [{"url": f"https://source.example/{i}", "title": f"文章{i}"} for i in range(150)]
        rows = [{**ROWS[0], "citations": citations,
                 "citation_collection": {"complete": True, "expected_count": 150}}]
        with patch("tools.ai_verifier._chat", return_value=reply(status="not_cited")) as chat:
            result = verify_question(config=CONFIG, question="测试", rows=rows,
                                     base_url="https://model.example/v1", api_key="test", model="test-model")
        self.assertEqual(result["doubao"]["citation_status"], "not_cited")
        self.assertIn('https://source.example/149', chat.call_args.kwargs["prompt"])

    def test_browser_reports_incomplete_even_when_counts_match(self) -> None:
        rows = [{**ROWS[0], "citation_collection": {"complete": False, "expected_count": 1,
                                                   "reason": "来源面板读取中断"}}]
        with patch("tools.ai_verifier._chat", return_value=reply(status="not_cited")):
            result = verify_question(config=CONFIG, question="测试", rows=rows,
                                     base_url="https://model.example/v1", api_key="test", model="test-model")
        self.assertEqual(result["doubao"]["citation_status"], "uncertain")

    def test_platform_explicitly_has_zero_sources(self) -> None:
        rows = [{**ROWS[0], "citations": [], "citation_collection": {"complete": True, "expected_count": 0}}]
        with patch("tools.ai_verifier._chat", return_value=reply(status="not_cited")):
            result = verify_question(config=CONFIG, question="测试", rows=rows,
                                     base_url="https://model.example/v1", api_key="test", model="test-model")
        self.assertEqual(result["doubao"]["citation_status"], "not_cited")


if __name__ == "__main__":
    unittest.main()
