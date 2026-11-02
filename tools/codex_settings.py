"""Read the active local Codex / CC Switch configuration without modifying it."""

from __future__ import annotations

from dataclasses import dataclass, field
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tomllib
from typing import Mapping


@dataclass(frozen=True)
class CodexSettings:
    base_url: str
    model: str
    api_key: str = field(repr=False)
    wire_api: str = "responses"
    source: str = "Codex 全局配置"

    def request_settings(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in ("base_url", "model", "api_key", "wire_api")}


def _json_file(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise ValueError(f"无法读取本机配置文件：{path.name}") from None
    return value if isinstance(value, dict) else {}


def _cc_switch_provider(directory: Path) -> dict:
    """Only read the selected Codex provider, never other providers' credentials."""
    database = directory / "cc-switch.db"
    if not database.is_file():
        return {}
    selected = _json_file(directory / "settings.json").get("currentProviderCodex")
    try:
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            row = None
            if selected:
                row = conn.execute(
                    "SELECT settings_config FROM providers WHERE app_type='codex' AND id=?",
                    (selected,),
                ).fetchone()
            if row is None:
                rows = conn.execute(
                    "SELECT settings_config FROM providers WHERE app_type='codex' AND is_current=1"
                ).fetchall()
                if len(rows) == 1:
                    row = rows[0]
            value = json.loads(row[0]) if row else {}
            return value if isinstance(value, dict) else {}
    except (sqlite3.Error, ValueError, TypeError):
        raise ValueError("无法读取 CC Switch 当前 Codex 配置，请在 CC Switch 中确认已启用的服务商") from None


def _parse(config: dict, auth: dict, env: Mapping[str, str], source: str) -> CodexSettings:
    provider_id = config.get("model_provider") or "openai"
    provider = config.get("model_providers", {}).get(provider_id, {})
    base_url = str(provider.get("base_url") or ("https://api.openai.com/v1" if provider_id == "openai" else "")).strip()
    model = str(config.get("model") or "").strip()
    env_key = provider.get("env_key")
    # Explicit provider credentials take priority over the default OpenAI key.
    key = provider.get("experimental_bearer_token") or (env.get(env_key) if env_key else None)
    if not key and not env_key:
        key = auth.get("OPENAI_API_KEY") or env.get("OPENAI_API_KEY")
    if not base_url or not model:
        raise ValueError("当前 Codex 配置缺少接口地址或模型名称，请先在 CC Switch 中启用一个 Codex 服务商")
    if not isinstance(key, str) or not key.strip():
        if env_key:
            raise ValueError("Codex 服务商指定的 Key 环境变量尚未设置")
        raise ValueError("当前 Codex 配置没有可用的 API Key；ChatGPT 登录凭据不能直接当 API Key 使用")
    wire_api = provider.get("wire_api") or "responses"
    if wire_api not in {"responses", "chat"}:
        raise ValueError("当前 Codex 服务商的接口协议不受支持")
    return CodexSettings(base_url, model, key.strip(), wire_api, source)


def load_codex_settings(
    *, codex_dir: Path | None = None, cc_switch_dir: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> CodexSettings:
    env = os.environ if environ is None else environ
    cc_dir = cc_switch_dir if cc_switch_dir is not None else Path.home() / ".cc-switch"
    if codex_dir is None:
        cc_preferences = _json_file(cc_dir / "settings.json")
        configured_dir = env.get("CODEX_HOME") or cc_preferences.get("codexConfigDir")
        codex_dir = Path(configured_dir).expanduser() if configured_dir else Path.home() / ".codex"
    live = codex_dir / "config.toml"
    if live.is_file():
        try:
            config = tomllib.loads(live.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            raise ValueError("无法解析 Codex 全局 config.toml，请在 CC Switch 中重新启用当前服务商") from None
        auth = _json_file(codex_dir / "auth.json")
        try:
            return _parse(config, auth, env, "Codex 全局配置（随 CC Switch 切换）")
        except ValueError:
            # CC Switch may store the key in its database rather than auth.json.
            # Only borrow it if the live configuration describes the same provider.
            selected = _cc_switch_provider(cc_dir)
            try:
                saved = tomllib.loads(selected.get("config") or "")
            except (ValueError, TypeError):
                saved = {}
            if config.get("model_provider") == saved.get("model_provider") and config.get("model_providers") == saved.get("model_providers"):
                return _parse(config, selected.get("auth") or {}, env, "Codex 全局配置 + CC Switch 当前 Key")
            raise
    selected = _cc_switch_provider(cc_dir)
    if not selected:
        raise ValueError("未找到 Codex / CC Switch 的全局模型配置，可取消自动读取后手动填写")
    try:
        config = tomllib.loads(selected.get("config") or "")
    except (ValueError, TypeError):
        raise ValueError("CC Switch 当前 Codex 配置格式无效") from None
    return _parse(config, selected.get("auth") or {}, env, "CC Switch 当前 Codex 服务商")
