"""Persist desktop inputs; protect manually entered keys with Windows DPAPI."""

from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path


def _crypt(value: bytes, *, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise ValueError("模型 Key 的本机加密保存需要 Windows")

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(value)
    source = Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    operation = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    operation.restype = wintypes.BOOL
    operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob),
                          ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise ValueError("无法读取或保存当前 Windows 用户的模型 Key")
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel32.LocalFree(output.data)


def save_state(path: Path, inputs: dict) -> None:
    """Save drafts without task validation, including partially filled fields."""
    data = {key: inputs.get(key, "") for key in
            ("brand", "article_text", "keyword_text", "question_text")}
    data["version"] = 1
    data["follow_codex"] = bool(inputs.get("follow_codex", True))
    if not data["follow_codex"]:
        model = inputs.get("manual_model") or {}
        data["manual_model"] = {key: str(model.get(key, "")) for key in ("base_url", "model", "wire_api")}
        key = model.get("api_key") or ""
        if key:
            data["manual_model"]["protected_api_key"] = base64.b64encode(_crypt(key.encode())).decode("ascii")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def load_state(path: Path, legacy_task: Path | None = None) -> dict:
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("保存的填写信息格式不正确")
        result = {key: data.get(key, "") if isinstance(data.get(key, ""), str) else ""
                  for key in ("brand", "article_text", "keyword_text", "question_text")}
        result["follow_codex"] = data.get("follow_codex") is not False
        model = data.get("manual_model")
        if not result["follow_codex"] and isinstance(model, dict):
            result["manual_model"] = {key: model.get(key, "") if isinstance(model.get(key, ""), str) else ""
                                      for key in ("base_url", "model", "wire_api")}
            if model.get("protected_api_key"):
                try:
                    result["manual_model"]["api_key"] = _crypt(
                        base64.b64decode(model["protected_api_key"], validate=True), decrypt=True,
                    ).decode()
                except (ValueError, UnicodeError, TypeError):
                    result["key_restore_failed"] = True
        return result
    if legacy_task and legacy_task.is_file():
        data = json.loads(legacy_task.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict):
            return {
                "brand": data.get("brand", ""),
                "article_text": "\n".join(item["url"] for item in data.get("articles", [])
                                          if isinstance(item, dict) and isinstance(item.get("url"), str)),
                "question_text": "\n".join(item for item in data.get("questions", []) if isinstance(item, str)),
                "keyword_text": "", "follow_codex": True,
            }
    return {}
