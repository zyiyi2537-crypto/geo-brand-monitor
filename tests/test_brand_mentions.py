"""Grounding, identity merging and report evidence for other-brand rankings."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'services/telemetry-service'))
from app.brand_mentions import mention_data, summarize_mentions, validate_mentions
from app.qualified_report import build_report, render_html
from tools.ai_verifier import extract_brand_mentions

CONFIG = {'brand': '目标', 'questions': ['问题一', '问题二'], 'articles': []}

def entity(name, alias, quote):
    return {'name': name, 'aliases': [alias], 'evidence_quote': quote}

def row(engine, question, answer, mentions):
    return {'engine': engine, 'query': question, 'answer': answer, 'brand_mentions': mentions}

class BrandMentionTests(unittest.TestCase):
    def test_alias_union_deduplicates_answers_and_excludes_target(self):
        rows = [row('doubao', '问题一', '相干 Coherent 和目标稳定。', [
            entity('相干', '相干', '相干 Coherent 和目标稳定。'),
            entity('Coherent', 'Coherent', '相干 Coherent 和目标稳定。'),
            entity('目标', '目标', '相干 Coherent 和目标稳定。')]),
            row('qwen', '问题一', 'Coherent（相干）可选。', [
                {'name': '相干', 'aliases': ['Coherent', '相干'], 'evidence_quote': 'Coherent（相干）可选。'}]),
            row('qwen', '问题二', 'coherent可选。', [entity('Coherent', 'coherent', 'coherent可选。')])]
        summary = summarize_mentions(CONFIG, rows + rows[:1])
        self.assertEqual(summary['answered'], 3)
        self.assertEqual(len(summary['brands']), 1)
        brand = summary['brands'][0]
        self.assertEqual((brand['count'], brand['questions']), (3, 2))
        self.assertEqual(brand['platforms']['qwen'], 2)
        self.assertEqual(summary['target']['count'], 1)

    def test_missing_invalid_and_empty_are_distinct(self):
        rows = [row('doubao', '问题一', '无厂商品牌', []),
                row('qwen', '问题一', '无厂商品牌', None),
                row('wenxin', '问题二', '普通回答', [entity('幽灵', '幽灵', '幽灵')])]
        summary = summarize_mentions(CONFIG, rows)
        self.assertEqual((summary['answered'], summary['analyzed']), (3, 1))
        self.assertEqual(summary['brands'], [])
        self.assertEqual(mention_data(rows[0]), [])
        self.assertIsNone(mention_data(rows[1]))
        self.assertIsNone(mention_data(rows[2]))
        pending = build_report(CONFIG, rows[1:])
        self.assertIn('暂不能生成其他品牌排名', pending)
        self.assertNotIn('未发现其他企业', pending)

    def test_ungrounded_quote_and_substring_alias_are_rejected(self):
        for value, answer in [([entity('品牌甲', '品牌甲', '品牌甲很好')], '品牌甲一般'),
                              ([entity('SM', 'SM', 'DSM很好')], 'DSM很好')]:
            with self.assertRaises(ValueError):
                validate_mentions(value, answer)

    def test_each_platform_has_its_own_denominator_and_evidence_is_safe(self):
        answer = '厂商甲 <script>alert(1)</script> [跳转](javascript:bad)'
        rows = [row('doubao', '问题一', answer, [entity('厂商甲', '厂商甲', answer)]),
                row('qwen', '问题一', '无其他品牌', []),
                row('qwen', '问题二', '无其他品牌', None)]
        report = build_report(CONFIG, rows)
        self.assertIn('| 1 | [厂商甲](#brand-1) | 1/2（50%） | 1/1（100%） | 待分析 | 1/1 | 待分析 | 待分析 | 0/1 |', report)
        markup = render_html(report, config=CONFIG, results=rows)
        self.assertIn('class="brand-evidence"', markup)
        self.assertIn('class="brand-all-evidence"', markup)
        self.assertIn('id="brand-1"', markup)
        self.assertIn('href="#q1-doubao"', markup)
        self.assertIn('&lt;script&gt;', markup)
        self.assertNotIn('<script>', markup)
        self.assertNotIn('href="javascript:', markup)

    def test_extraction_uses_saved_answer_without_citation_only_brand(self):
        rows = [{'engine': 'doubao', 'answer': '厂商甲可选。',
                 'citations': [{'title': '引用专有品牌', 'url': 'https://example.com'}]}]
        response = {'verdicts': [{'engine': 'doubao', 'mentioned_brands': [entity('厂商甲', '厂商甲', '厂商甲可选。')]}]}
        with patch('tools.ai_verifier._chat', return_value=json.dumps(response)) as chat:
            output = extract_brand_mentions(target_brand='目标', rows=rows, base_url='x', api_key='x', model='x')
        self.assertEqual(len(output['doubao']), 1)
        self.assertNotIn('引用专有品牌', chat.call_args.kwargs['prompt'])
        with patch('tools.ai_verifier._chat', return_value='{"verdicts": []}'):
            with self.assertRaises(ValueError):
                extract_brand_mentions(target_brand='目标', rows=rows, base_url='x', api_key='x', model='x')

if __name__ == '__main__':
    unittest.main()
