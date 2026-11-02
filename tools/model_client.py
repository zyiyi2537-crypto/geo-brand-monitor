"""OpenAI-compatible Chat Completions and Responses client."""

from __future__ import annotations

import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


_RETRYABLE_HTTP = {502, 503, 504}


class _IncompleteResponseStream(ValueError):
    """The provider closed an SSE stream before sending response.completed."""


def endpoint(base_url: str, wire_api: str = "chat") -> str:
    """Accept a provider base or full endpoint, retaining provider-specific paths."""
    if wire_api not in {"chat", "responses"}:
        raise ValueError("模型接口协议必须是 chat 或 responses")
    value = base_url.strip().rstrip("/")
    if not value:
        raise ValueError("模型接口地址不能为空")
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("模型接口地址必须是 http(s) 网址")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("模型接口地址不能包含账号、密码、查询参数或片段")
    path = parsed.path.rstrip("/")
    full_endpoint = False
    for suffix in ("/chat/completions", "/responses"):
        if path.endswith(suffix):
            full_endpoint = True
            path = path[:-len(suffix)]
            break
    suffix = "/responses" if wire_api == "responses" else "/chat/completions"
    final_path = (path if full_endpoint else path or "/v1") + suffix
    return urlunsplit((parsed.scheme, parsed.netloc, final_path, "", ""))


def _response_text(payload: dict) -> str:
    if payload.get("error") or payload.get("status") in {"failed", "incomplete", "cancelled"}:
        error = payload.get("error") or payload.get("incomplete_details") or {}
        raise ValueError("Responses 请求未完成：" + str(error.get("message") or error.get("reason") or payload.get("status")))
    pieces = [part.get("text", "") for item in payload.get("output", [])
              if item.get("type") == "message" for part in item.get("content", [])
              if part.get("type") == "output_text"]
    return "".join(pieces)


def _read_response_stream(response) -> str:
    deltas: list[str] = []
    data: list[str] = []
    completed = False

    def consume(value: str) -> str | None:
        nonlocal completed
        if value == "[DONE]":
            return None
        event = json.loads(value)
        kind = event.get("type")
        if kind == "response.output_text.delta":
            delta = event.get("delta", "")
            if isinstance(delta, str):
                deltas.append(delta)
        elif kind == "response.completed":
            completed = True
            return _response_text(event.get("response") or {}) or "".join(deltas)
        elif kind in {"response.failed", "response.incomplete"}:
            _response_text(event.get("response") or {"status": "failed"})
        elif kind == "error":
            raise ValueError("Responses 接口错误：" + str(event.get("message") or "未知错误"))
        return None

    for raw_line in response:
        line = raw_line.decode("utf-8").rstrip("\r\n")
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
        elif not line and data:
            value = "\n".join(data)
            data.clear()
            result = consume(value)
            if result is not None:
                return result
    # Some compatible gateways close immediately after the final SSE event and
    # omit the blank separator. Do not discard that buffered event.
    if data:
        result = consume("\n".join(data))
        if result is not None:
            return result
    if completed:
        return "".join(deltas)
    raise _IncompleteResponseStream(
        "Responses 输出中断，未收到完成事件，请重试或检查服务商状态"
    )


def chat_content(
    *, base_url: str, api_key: str, model: str, messages: list[dict[str, str]],
    timeout: float = 90, wire_api: str = "chat",
) -> str:
    """Send one chat request; retry short lived gateway failures twice."""
    if not model.strip():
        raise ValueError("模型名称不能为空")
    if not api_key.strip():
        raise ValueError("API Key 不能为空")
    url = endpoint(base_url, wire_api)
    payload_body: dict = {"model": model.strip()}
    if wire_api == "responses":
        payload_body.update({
            "instructions": "\n".join(msg["content"] for msg in messages if msg["role"] in {"system", "developer"}),
            "input": [{"role": msg["role"], "content": [{
                "type": "output_text" if msg["role"] == "assistant" else "input_text", "text": msg["content"],
            }]} for msg in messages if msg["role"] not in {"system", "developer"}],
            "store": False, "stream": True,
        })
    else:
        payload_body["messages"] = messages
    def make_request(body_payload: dict, *, streaming: bool) -> Request:
        body = json.dumps(body_payload, ensure_ascii=False).encode("utf-8")
        return Request(url, data=body, method="POST", headers={
            "Accept": "text/event-stream, application/json" if streaming else "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {api_key.strip()}",
        })

    def request_once(body_payload: dict, *, streaming: bool) -> str:
        for attempt in range(3):
            request = make_request(body_payload, streaming=streaming)
            try:
                with urlopen(request, timeout=timeout) as response:
                    content_type = getattr(response, "headers", {}).get("Content-Type", "")
                    if streaming and "text/event-stream" in content_type:
                        return _read_response_stream(response)
                    payload = json.loads(response.read().decode("utf-8"))
                    return _response_text(payload) if wire_api == "responses" else payload["choices"][0]["message"]["content"]
            except HTTPError as exc:
                if exc.code in _RETRYABLE_HTTP and attempt < 2:
                    exc.close()
                    time.sleep(attempt + 1)
                    continue
                detail = exc.read(1000).decode("utf-8", errors="replace").strip()
                try:
                    data = json.loads(detail)
                    error = data.get("error", data) if isinstance(data, dict) else data
                    detail = error.get("message", detail) if isinstance(error, dict) else detail
                except (ValueError, TypeError):
                    pass
                hint = "；这是接口网关或上游模型返回的错误，请核对请求地址和服务商状态" if exc.code in _RETRYABLE_HTTP else ""
                detail = str(detail).replace(api_key.strip(), "[Key 已隐藏]")
                raise ValueError(f"模型接口 HTTP {exc.code}：{url}；{detail[:250] or '无错误详情'}{hint}") from None
            except (URLError, TimeoutError, OSError) as exc:
                raise ValueError(f"模型接口连接失败：{url}；{exc}") from exc
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"模型接口返回了无效 JSON：{url}；{exc}") from exc
            except (KeyError, IndexError, TypeError, AttributeError):
                raise ValueError(f"模型接口返回格式不符合 {wire_api} 协议：{url}") from None
        raise AssertionError("unreachable")

    try:
        content = request_once(payload_body, streaming=wire_api == "responses")
    except _IncompleteResponseStream:
        if wire_api != "responses":
            raise
        # A few OpenAI-compatible gateways proxy SSE unreliably. Retry the
        # same request once without streaming, which is also easier to parse.
        fallback_payload = dict(payload_body)
        fallback_payload["stream"] = False
        content = request_once(fallback_payload, streaming=False)
        if not isinstance(content, str) or not content.strip():
            raise _IncompleteResponseStream(
                "Responses 输出中断，未收到完成事件，请重试或检查服务商状态"
            )
    except ValueError as exc:
        raise ValueError(str(exc).replace(api_key.strip(), "[Key 已隐藏]")) from None
    if not isinstance(content, str) or not content.strip():
        raise ValueError("模型没有返回文字内容")
    return content.strip()
