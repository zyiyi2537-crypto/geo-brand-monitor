"""Model endpoint routing and transient gateway handling."""

from __future__ import annotations

from io import BytesIO
import json
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

from tools.model_client import chat_content, endpoint


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps({"choices": [{"message": {"content": "连接正常"}}]}).encode()


class _ResponsesReply(_Response):
    def read(self):
        return json.dumps({"status": "completed", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": "连接正常"},
        ]}]}).encode()


class _Stream(_Response):
    headers = {"Content-Type": "text/event-stream; charset=utf-8"}

    def __init__(self, events):
        self.events = events

    def __iter__(self):
        for event in self.events:
            yield ("data: " + json.dumps(event, ensure_ascii=False) + "\n").encode()
            yield b"\n"


def _gateway_error():
    return HTTPError("https://provider.example/api/v3/chat/completions", 502,
                     "Bad Gateway", {}, BytesIO(b"upstream unavailable"))


class ModelClientTests(unittest.TestCase):
    def test_endpoint_accepts_provider_base_and_full_request_url(self):
        self.assertEqual(endpoint("https://api.example.com"),
                         "https://api.example.com/v1/chat/completions")
        self.assertEqual(endpoint("https://provider.example/api/v3"),
                         "https://provider.example/api/v3/chat/completions")
        self.assertEqual(endpoint("https://provider.example/api/v3/chat/completions"),
                         "https://provider.example/api/v3/chat/completions")

    def test_gateway_502_is_retried_without_changing_the_request_path(self):
        with patch("tools.model_client.urlopen", side_effect=[
            _gateway_error(), _gateway_error(), _Response(),
        ]) as send, patch("tools.model_client.time.sleep") as pause:
            content = chat_content(
                base_url="https://provider.example/api/v3", api_key="secret",
                model="provider-model", messages=[{"role": "user", "content": "测试"}],
            )
        self.assertEqual(content, "连接正常")
        self.assertEqual(send.call_count, 3)
        self.assertEqual(pause.call_count, 2)
        self.assertEqual(send.call_args.args[0].full_url,
                         "https://provider.example/api/v3/chat/completions")

    def test_persistent_502_explains_the_actual_request_path(self):
        with patch("tools.model_client.urlopen", side_effect=[
            _gateway_error(), _gateway_error(), _gateway_error(),
        ]), patch("tools.model_client.time.sleep"):
            with self.assertRaisesRegex(ValueError, r"HTTP 502.*api/v3/chat/completions"):
                chat_content(base_url="https://provider.example/api/v3", api_key="secret",
                             model="provider-model", messages=[{"role": "user", "content": "测试"}])

    def test_responses_request_uses_codex_format_and_parses_completed_stream(self):
        stream = _Stream([
            {"type": "response.output_text.delta", "delta": "连接正常"},
            {"type": "response.completed", "response": {"status": "completed", "output": []}},
        ])
        with patch("tools.model_client.urlopen", return_value=stream) as send:
            content = chat_content(base_url="https://provider.example/v1", api_key="secret", model="model",
                                   messages=[{"role": "system", "content": "系统要求"}, {"role": "user", "content": "测试"}],
                                   wire_api="responses")
        self.assertEqual(content, "连接正常")
        request = send.call_args.args[0]
        self.assertEqual(request.full_url, "https://provider.example/v1/responses")
        body = json.loads(request.data)
        self.assertEqual(body["instructions"], "系统要求")
        self.assertEqual(body["input"][0]["content"], [{"type": "input_text", "text": "测试"}])
        self.assertFalse(body["store"])
        self.assertTrue(body["stream"])
        self.assertNotIn("messages", body)

    def test_accepts_json_responses_and_preserves_full_endpoint(self):
        with patch("tools.model_client.urlopen", return_value=_ResponsesReply()):
            text = chat_content(base_url="https://provider.example/responses", api_key="secret", model="model",
                                messages=[{"role": "user", "content": "测试"}], wire_api="responses")
        self.assertEqual(text, "连接正常")
        self.assertEqual(endpoint("https://provider.example/responses", "responses"), "https://provider.example/responses")
        self.assertEqual(endpoint("https://provider.example/api/v2", "responses"), "https://provider.example/api/v2/responses")

    def test_incomplete_stream_is_not_accepted_as_success(self):
        stream = _Stream([{"type": "response.output_text.delta", "delta": "不完整"}])
        with patch("tools.model_client.urlopen", return_value=stream):
            with self.assertRaisesRegex(ValueError, "输出中断"):
                chat_content(base_url="https://provider.example/v1", api_key="secret", model="model",
                             messages=[{"role": "user", "content": "测试"}], wire_api="responses")

    def test_key_echoed_in_provider_error_is_redacted(self):
        error = HTTPError("https://provider.example/v1/responses", 401, "Unauthorized", {},
                          BytesIO(b'{"error":{"message":"Invalid key: secret-value"}}'))
        with patch("tools.model_client.urlopen", side_effect=error):
            with self.assertRaises(ValueError) as raised:
                chat_content(base_url="https://provider.example/v1", api_key="secret-value", model="model",
                             messages=[{"role": "user", "content": "测试"}], wire_api="responses")
        self.assertNotIn("secret-value", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
