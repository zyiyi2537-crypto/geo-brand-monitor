"""Desktop control center for the five-platform GEO monitor.

The GUI owns the local browser service and the login helpers. Operators do not
need to open a terminal or remember platform-specific commands.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import re
import socket
import subprocess
import threading
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext, simpledialog, ttk
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from tools.agent_planner import generate_questions as generate_agent_questions
from tools.ai_verifier import check_model
from tools.codex_settings import load_codex_settings
from tools.desktop_state import load_state, save_state
from tools.model_client import endpoint as model_endpoint
from tools.session_status import complete_session_results, session_label, session_ready
from tools.background_browser import (
    BrowserDesktop, background_service_ready, service_environment, stop_service,
)


ROOT = Path(__file__).resolve().parent
LOGO = ROOT / "assets" / "geo-logo-48.png"
PYTHON = Path(os.environ.get("GEO_RUNTIME_PYTHON", str(ROOT / ".venv" / "Scripts" / "python.exe")))
SERVICE_DIR = ROOT / "services" / "browser-service"
SERVICE_SCRIPT = SERVICE_DIR / "manual_login.py"
RECORD_TOOL = ROOT / "tools" / "geo_record.py"
DATA_DIR = Path(os.environ.get("GEO_DATA_DIR", str(ROOT)))
REPORTS = DATA_DIR / "reports"
SESSIONS = DATA_DIR / "browser_sessions" if os.environ.get("GEO_DATA_DIR") else SERVICE_DIR / "data" / "browser_sessions"
STATE_FILE = DATA_DIR / "settings.json" if os.environ.get("GEO_DATA_DIR") else REPORTS / ".geo-ui-state.json"
BROWSER_PORT = int(os.environ.get("GEO_BROWSER_PORT", "8091"))
BROWSER_URL = f"http://127.0.0.1:{BROWSER_PORT}"
ENGINES = (
    ("deepseek", "DeepSeek"),
    ("doubao", "豆包"),
    ("yuanbao", "元宝"),
    ("wenxin", "文心一言"),
    ("qwen", "通义千问"),
)


class GeoMonitorApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("GEO 监测中心")
        self.logo_image = tk.PhotoImage(file=str(LOGO)) if LOGO.is_file() else None
        if self.logo_image is not None:
            self.root.iconphoto(True, self.logo_image)
        window_height = min(980, self.root.winfo_screenheight() - 100)
        self.root.geometry(f"980x{window_height}")
        self.root.minsize(780, min(680, window_height))
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.config_path: Path | None = None
        self.brand_input_var = tk.StringVar()
        self.brand_var = tk.StringVar(value="未建立核对任务")
        self.title_var = tk.StringVar(value="GEO 监测中心")
        self.question_count_var = tk.StringVar(value="0")
        self.task_status_var = tk.StringVar(value="输入品牌、文章链接和关键词后生成核对任务")
        self.model_base_var = tk.StringVar()
        self.model_name_var = tk.StringVar()
        self.model_key_var = tk.StringVar()
        self.model_wire_var = tk.StringVar(value="chat")
        self.follow_codex_var = tk.BooleanVar(value=True)
        self.model_entries: list[ttk.Entry] = []
        self.model_endpoint_var = tk.StringVar(value="实际请求地址：请填写模型接口地址")
        self.model_status_var = tk.StringVar(value="出题可用本地模板；引用判定需配置模型")
        self.events: queue.Queue[tuple] = queue.Queue()
        self.login_processes: dict[tuple[str, str], subprocess.Popen] = {}
        self.service_process: subprocess.Popen | None = None
        self.service_lock = threading.Lock()
        self.browser_desktop: BrowserDesktop | None = None
        self.browser_port = BROWSER_PORT
        self.browser_url = BROWSER_URL
        self.monitor_process: subprocess.Popen | None = None
        self.active_report_dir: Path | None = None
        self.history_window: tk.Toplevel | None = None
        self.history_tree: ttk.Treeview | None = None
        self.trend_window: tk.Toplevel | None = None
        self.trend_brand_var = tk.StringVar(value="全部品牌")
        self.trend_period_var = tk.StringVar(value="全部时间")
        self.trend_keyword_var = tk.StringVar()
        self.status_vars: dict[str, tk.StringVar] = {}
        self.login_buttons: dict[str, ttk.Button] = {}
        self.session_verified: dict[str, str] = {}
        self.session_verified_at: dict[str, tuple[float, tuple[int, int] | None]] = {}
        self.session_check_pending = False
        self.session_check_auto_start = False
        self.model_check_pending = False
        self.active_ai_settings: dict[str, str] = {}
        self.autosave_timer: str | None = None
        self.closing = False

        self._build_ui()
        self._restore_inputs()
        self.model_base_var.trace_add("write", self._show_model_endpoint)
        self.model_wire_var.trace_add("write", self._show_model_endpoint)
        self._model_source_changed()
        self._enable_autosave()
        self.root.after(100, self._drain_events)
        self.root.after(800, self._refresh_status)
        threading.Thread(target=self._ensure_service, daemon=True).start()

    def _build_ui(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass

        header = ttk.Frame(self.root, padding=(22, 18, 22, 8))
        header.pack(fill="x")
        if self.logo_image is not None:
            ttk.Label(header, image=self.logo_image).pack(side="left", padx=(0, 12))
        heading = ttk.Frame(header)
        heading.pack(side="left", fill="x", expand=True)
        ttk.Label(heading, textvariable=self.title_var, font=("Microsoft YaHei UI", 18, "bold")).pack(anchor="w")
        ttk.Label(
            heading,
            text="输入品牌和文章链接，自动规划问题并核对五个平台",
            foreground="#555555",
        ).pack(anchor="w", pady=(4, 0))

        model = ttk.LabelFrame(self.root, text="AI 模型（出题与引用判定）", padding=10)
        model.pack(fill="x", padx=22, pady=(0, 10))
        ttk.Checkbutton(model, text="自动使用 CC Switch / Codex 全局配置", variable=self.follow_codex_var,
                        command=self._model_source_changed).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        ttk.Button(model, text="重新读取", command=self.use_codex_settings).grid(row=0, column=2, sticky="w", pady=(0, 8))
        protocol = ttk.Frame(model)
        protocol.grid(row=0, column=3, sticky="e", pady=(0, 8))
        ttk.Label(protocol, text="接口协议：").pack(side="left")
        self.model_protocol_box = ttk.Combobox(protocol, textvariable=self.model_wire_var,
                                               values=("responses", "chat"), state="readonly", width=12)
        self.model_protocol_box.pack(side="left")
        ttk.Label(model, text="接口地址：").grid(row=1, column=0, sticky="w")
        base_entry = ttk.Entry(model, textvariable=self.model_base_var, width=44)
        base_entry.grid(row=1, column=1, sticky="ew", padx=(8, 12))
        ttk.Label(model, text="模型名称：").grid(row=1, column=2, sticky="w")
        name_entry = ttk.Entry(model, textvariable=self.model_name_var, width=24)
        name_entry.grid(row=1, column=3, sticky="ew", padx=(8, 0))
        ttk.Label(model, text="API Key：").grid(row=2, column=0, sticky="w", pady=(7, 0))
        key_entry = ttk.Entry(model, textvariable=self.model_key_var, show="*", width=44)
        key_entry.grid(row=2, column=1, sticky="ew", padx=(8, 12), pady=(7, 0))
        self.model_entries.extend((base_entry, name_entry, key_entry))
        ttk.Label(model, textvariable=self.model_status_var, foreground="#555555").grid(
            row=4, column=0, columnspan=4, sticky="w", pady=(4, 0)
        )
        ttk.Button(model, text="测试模型", command=self.test_model_action).grid(
            row=2, column=3, sticky="e", pady=(7, 0)
        )
        ttk.Label(model, textvariable=self.model_endpoint_var, foreground="#555555").grid(
            row=3, column=0, columnspan=4, sticky="w", pady=(7, 0)
        )
        model.columnconfigure(1, weight=1)
        model.columnconfigure(3, weight=1)

        task = ttk.LabelFrame(self.root, text="本次核对任务（Agent 输入）", padding=10)
        task.pack(fill="x", padx=22, pady=(0, 10))
        ttk.Label(task, text="目标品牌（必填）：").grid(row=0, column=0, sticky="nw")
        ttk.Entry(task, textvariable=self.brand_input_var, width=32).grid(
            row=0, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=(0, 6)
        )
        ttk.Label(task, text="已发布文章链接：").grid(row=1, column=0, sticky="nw")
        self.article_input = scrolledtext.ScrolledText(task, height=3, width=72, wrap="word")
        self.article_input.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=(0, 6))
        ttk.Label(task, text="关键词/主题：").grid(row=2, column=0, sticky="nw")
        self.keyword_input = scrolledtext.ScrolledText(task, height=3, width=72, wrap="word")
        self.keyword_input.grid(row=2, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=(0, 6))
        ttk.Label(task, text="核对问题：").grid(row=3, column=0, sticky="nw")
        self.question_input = scrolledtext.ScrolledText(task, height=5, width=72, wrap="word")
        self.question_input.grid(row=3, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=(0, 6))
        ttk.Label(
            task,
            text="问题留空时，Agent 会根据关键词生成；生成后仍可直接编辑。每行一个网址或问题。",
            foreground="#555555",
        ).grid(row=4, column=1, columnspan=2, sticky="w", padx=(8, 0))
        task.columnconfigure(1, weight=1)
        self.generate_button = ttk.Button(task, text="生成核对问题", command=self.generate_questions_action)
        self.generate_button.grid(
            row=0, column=3, rowspan=2, padx=(12, 0), sticky="n"
        )
        ttk.Label(task, textvariable=self.task_status_var, foreground="#555555").grid(
            row=2, column=3, rowspan=3, padx=(12, 0), sticky="nw"
        )

        service = ttk.Frame(self.root, padding=(22, 4, 22, 10))
        service.pack(fill="x")
        self.service_var = tk.StringVar(value="浏览器服务：正在启动……")
        ttk.Label(service, textvariable=self.service_var).pack(side="left")
        ttk.Button(service, text="刷新状态", command=self.refresh_now).pack(side="right")

        platforms = ttk.LabelFrame(self.root, text="五个平台登录状态", padding=12)
        platforms.pack(fill="x", padx=22, pady=(0, 12))
        for row, (engine, name) in enumerate(ENGINES):
            ttk.Label(platforms, text=name, width=14).grid(row=row, column=0, sticky="w", pady=5)
            state = tk.StringVar(value="检查中")
            self.status_vars[engine] = state
            ttk.Label(platforms, textvariable=state, width=25).grid(row=row, column=1, sticky="w", pady=5)
            button = ttk.Button(platforms, text="打开登录窗口", command=lambda e=engine: self.login_one(e))
            button.grid(row=row, column=2, sticky="w", padx=(12, 0), pady=5)
            self.login_buttons[engine] = button
            ttk.Button(platforms, text="保存登录态", command=lambda e=engine: self.save_login(e)).grid(
                row=row, column=3, sticky="w", padx=(8, 0), pady=5
            )
            ttk.Button(platforms, text="账号管理", command=lambda e=engine: self.manage_accounts(e)).grid(
                row=row, column=4, sticky="w", padx=(8, 0), pady=5
            )

        actions = ttk.Frame(self.root, padding=(22, 0, 22, 12))
        actions.pack(fill="x")
        ttk.Button(actions, text="一次打开五个平台", command=self.login_all).pack(side="left")
        self.session_check_button = ttk.Button(actions, text="检查登录态", command=self.check_sessions_action)
        self.session_check_button.pack(side="left", padx=8)
        self.run_button = ttk.Button(actions, text="开始监测", command=self.run_monitor, state="disabled")
        self.run_button.pack(side="left", padx=8)
        self.open_button = ttk.Button(actions, text="打开最新报告", command=self.open_latest)
        self.open_button.pack(side="left")
        ttk.Button(actions, text="历史报告", command=self.open_history).pack(side="left", padx=(8, 0))

        log_frame = ttk.LabelFrame(self.root, text="运行信息", padding=8)
        log_frame.pack(fill="both", expand=True, padx=22, pady=(0, 18))
        self.log = tk.Text(log_frame, height=12, state="disabled", wrap="word", font=("Consolas", 10))
        self.log.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        scrollbar.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=scrollbar.set)
        self._write_log("请填写目标品牌和已发布文章链接；关键词可用于自动生成核对问题。")
        self._write_log("模型默认读取 CC Switch / Codex 全局配置。确认问题列表后，登录五个平台并开始监测。")

    @staticmethod
    def _lines(widget: tk.Text, *, split_commas: bool = False) -> list[str]:
        value = widget.get("1.0", "end")
        pattern = r"[\r\n,，、;；]+" if split_commas else r"[\r\n]+"
        return [item.strip() for item in re.split(pattern, value) if item.strip()]

    def _restore_inputs(self) -> None:
        try:
            saved = load_state(STATE_FILE, REPORTS / ".geo-current-task.json")
        except (ValueError, OSError) as exc:
            self._write_log(f"上次填写信息未能恢复：{exc}")
            return
        if not saved:
            return
        self.brand_input_var.set(saved.get("brand", ""))
        for widget, field in ((self.article_input, "article_text"), (self.keyword_input, "keyword_text"),
                              (self.question_input, "question_text")):
            widget.insert("1.0", saved.get(field, ""))
        self.follow_codex_var.set(saved.get("follow_codex", True))
        model = saved.get("manual_model", {})
        for variable, field in ((self.model_base_var, "base_url"), (self.model_name_var, "model"),
                                (self.model_key_var, "api_key"), (self.model_wire_var, "wire_api")):
            if model.get(field):
                variable.set(model[field])
        if saved.get("key_restore_failed"):
            self._write_log("已恢复上次输入；模型 Key 需要由当前 Windows 用户重新填写。")
        else:
            self._write_log("已恢复上次填写的信息，修改后可直接开始监测。")
        try:
            brand, _urls, _keywords = self._collect_task_inputs()
        except ValueError:
            self.task_status_var.set("已恢复上次填写的信息，请补全任务")
            return
        self.config_path = REPORTS / ".geo-current-task.json"
        count = len(self._lines(self.question_input))
        self.brand_var.set(brand)
        self.question_count_var.set(str(count))
        self.task_status_var.set("已恢复上次任务；修改后可直接开始监测")
        self.run_button.configure(state="normal", text=f"开始 {count} 个问题监测" if count else "开始监测")

    def _enable_autosave(self) -> None:
        for variable in (self.brand_input_var, self.model_base_var, self.model_name_var,
                         self.model_key_var, self.model_wire_var, self.follow_codex_var):
            variable.trace_add("write", self._schedule_save)
        for widget in (self.article_input, self.keyword_input, self.question_input):
            widget.edit_modified(False)
            widget.bind("<<Modified>>", self._text_changed)

    def _text_changed(self, event: tk.Event) -> None:
        if event.widget.edit_modified():
            event.widget.edit_modified(False)
            self._schedule_save()

    def _schedule_save(self, *_args: object) -> None:
        if self.closing:
            return
        if self.autosave_timer:
            self.root.after_cancel(self.autosave_timer)
        self.autosave_timer = self.root.after(500, self._save_inputs)

    def _save_inputs(self) -> None:
        self.autosave_timer = None
        try:
            save_state(STATE_FILE, {
                "brand": self.brand_input_var.get(),
                "article_text": self.article_input.get("1.0", "end-1c"),
                "keyword_text": self.keyword_input.get("1.0", "end-1c"),
                "question_text": self.question_input.get("1.0", "end-1c"),
                "follow_codex": self.follow_codex_var.get(),
                "manual_model": {"base_url": self.model_base_var.get(), "model": self.model_name_var.get(),
                                 "api_key": self.model_key_var.get(), "wire_api": self.model_wire_var.get()},
            })
        except (OSError, ValueError) as exc:
            self._write_log(f"填写信息保存失败：{exc}")

    @staticmethod
    def _validate_article_url(value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise ValueError(f"文章链接不是有效的 http(s) 网址：{value}")
        if parsed.username or parsed.password:
            raise ValueError("文章链接不能包含账号或密码")
        if parsed.hostname == "mp.toutiao.com" and "/preview" in parsed.path:
            raise ValueError("头条后台预览地址不能用于引用核对，请填写已发布文章的公开网址")
        return value

    @staticmethod
    def _make_questions(brand: str, keywords: list[str]) -> list[str]:
        templates = (
            "{keyword}企业推荐？",
            "{keyword}供应商怎么选？",
            "{keyword}哪家稳定？",
            "{keyword}如何选择？",
            "{keyword}哪家可以批量交付？",
        )
        seeds = keywords or [brand]
        questions: list[str] = []
        for seed in seeds:
            for template in templates:
                question = template.format(keyword=seed)
                if question not in questions:
                    questions.append(question)
        return questions

    def _collect_task_inputs(self) -> tuple[str, list[str], list[str]]:
        brand = self.brand_input_var.get().strip()
        if not brand:
            raise ValueError("请填写目标品牌")
        raw_urls = self._lines(self.article_input)
        if not raw_urls:
            raise ValueError("请至少填写一个已发布文章链接")
        article_urls: list[str] = []
        for raw_url in raw_urls:
            url = self._validate_article_url(raw_url)
            if url not in article_urls:
                article_urls.append(url)
        keywords = self._lines(self.keyword_input, split_commas=True)
        return brand, article_urls, keywords

    def generate_questions_action(self) -> None:
        """Use the configured model for planning, with a local fallback."""
        try:
            brand, article_urls, keywords = self._collect_task_inputs()
        except ValueError as exc:
            messagebox.showwarning("核对任务不完整", str(exc))
            return

        if self.follow_codex_var.get() and not self.reload_codex_settings():
            return
        base_url = self.model_base_var.get().strip()
        model = self.model_name_var.get().strip()
        api_key = self.model_key_var.get().strip()
        if not (base_url and model and api_key):
            questions = self._make_questions(brand, keywords)
            self.question_input.delete("1.0", "end")
            self.question_input.insert("1.0", "\n".join(questions))
            self.model_status_var.set("未完整配置模型，已使用本地问题模板")
            self.prepare_task()
            return

        self.generate_button.configure(state="disabled")
        self.model_status_var.set(f"正在调用 {model} 生成问题……")
        threading.Thread(
            target=self._model_question_worker,
            args=(brand, article_urls, keywords, base_url, api_key, model, self.model_wire_var.get()),
            daemon=True,
        ).start()

    def _model_question_worker(
        self,
        brand: str,
        article_urls: list[str],
        keywords: list[str],
        base_url: str,
        api_key: str,
        model: str,
        wire_api: str,
    ) -> None:
        try:
            questions = generate_agent_questions(
                brand=brand,
                article_urls=article_urls,
                keywords=keywords,
                base_url=base_url,
                api_key=api_key,
                model=model,
                wire_api=wire_api,
            )
            self.events.put(("model_done", questions, None, model))
        except Exception as exc:
            self.events.put(("model_done", self._make_questions(brand, keywords), str(exc), model))

    def prepare_task(self) -> bool:
        """Turn the operator's plain-language inputs into the private run config."""
        try:
            brand, article_urls, _keywords = self._collect_task_inputs()

            manual_questions = self._lines(self.question_input)
            questions = manual_questions or self._make_questions(brand, _keywords)
            if not questions:
                raise ValueError("请填写关键词，或直接填写核对问题")

            articles = [
                {"title": f"已发布文章 {index}", "url": url}
                for index, url in enumerate(article_urls, 1)
            ]
            task = {"brand": brand, "articles": articles, "questions": questions}
            REPORTS.mkdir(parents=True, exist_ok=True)
            self.config_path = REPORTS / ".geo-current-task.json"
            self.config_path.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")

            if not manual_questions:
                self.question_input.delete("1.0", "end")
                self.question_input.insert("1.0", "\n".join(questions))
            self.brand_var.set(brand)
            self.question_count_var.set(str(len(questions)))
            self.task_status_var.set(f"已生成 {len(questions)} 个问题，可编辑后重新生成")
            self.run_button.configure(text=f"开始 {len(questions)} 个问题监测", state="normal")
            self._write_log(f"已建立核对任务：品牌 {brand}，{len(article_urls)} 篇文章，{len(questions)} 个问题。")
            self._save_inputs()
            return True
        except ValueError as exc:
            messagebox.showwarning("核对任务不完整", str(exc))
            return False

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "ENGINE_LIST": ",".join(engine for engine, _ in ENGINES),
                "REGION": "cn",
                "BROWSER_SESSION_DIR": str(SESSIONS),
                "SNAPSHOT_DIR": str(DATA_DIR / "snapshots"),
                "PYTHONPATH": str(SERVICE_DIR),
                "PYTHONUNBUFFERED": "1",
            }
        )
        if os.name == "nt":
            env["DOUBAO_BACKEND"] = "patchright"
        # Login processes must stay visible even when the parent environment
        # was inherited from a background worker.
        env.pop("GEO_BROWSER_BACKGROUND", None)
        env.pop("GEO_BROWSER_PRIVATE_DESKTOP", None)
        return env

    def _monitor_env(self) -> dict[str, str]:
        env = self._env()
        env.update({
            "GEO_AI_BASE_URL": self.active_ai_settings["base_url"],
            "GEO_AI_MODEL": self.active_ai_settings["model"],
            "GEO_AI_API_KEY": self.active_ai_settings["api_key"],
            "GEO_AI_WIRE_API": self.active_ai_settings["wire_api"],
            "GEO_AI_PREFLIGHT_OK": "1",
            # Detection browser pages stay in the background; login windows
            # use the normal environment and remain visible.
            "GEO_BROWSER_BACKGROUND": "1",
        })
        return env

    def _model_source_changed(self) -> None:
        automatic = self.follow_codex_var.get()
        for entry in self.model_entries:
            entry.configure(state="readonly" if automatic else "normal")
        self.model_protocol_box.configure(state="disabled" if automatic else "readonly")
        if automatic:
            self.reload_codex_settings()
        else:
            self.model_status_var.set("手动配置：请使用服务商支持的接口协议")

    def use_codex_settings(self) -> None:
        self.follow_codex_var.set(True)
        self._model_source_changed()

    def reload_codex_settings(self) -> bool:
        try:
            settings = load_codex_settings()
        except ValueError as exc:
            # Never keep using a stale key or provider after a failed refresh.
            self.model_base_var.set("")
            self.model_name_var.set("")
            self.model_key_var.set("")
            self.model_status_var.set(str(exc))
            self._write_log(str(exc))
            return False
        changed = (self.model_base_var.get(), self.model_name_var.get(), self.model_key_var.get(), self.model_wire_var.get()) != (
            settings.base_url, settings.model, settings.api_key, settings.wire_api,
        )
        self.model_wire_var.set(settings.wire_api)
        self.model_base_var.set(settings.base_url)
        self.model_name_var.set(settings.model)
        self.model_key_var.set(settings.api_key)
        self.model_status_var.set(f"已读取 {settings.source}；Key 已载入，点击“测试模型”检查连接")
        if changed:
            self._write_log(f"已读取全局模型：{settings.model}，协议：{settings.wire_api}。")
        return True

    def _show_model_endpoint(self, *_args: object) -> None:
        try:
            value = model_endpoint(self.model_base_var.get(), self.model_wire_var.get())
        except ValueError as exc:
            self.model_endpoint_var.set(f"实际请求地址：{exc}")
        else:
            self.model_endpoint_var.set(f"实际请求地址：{value}")

    def test_model_action(self) -> None:
        if self.model_check_pending:
            return
        if self.follow_codex_var.get() and not self.reload_codex_settings():
            return
        base_url = self.model_base_var.get().strip()
        model = self.model_name_var.get().strip()
        api_key = self.model_key_var.get().strip()
        if not (base_url and model and api_key):
            messagebox.showwarning("模型配置不完整", "请填写接口地址、模型名称和 API Key。")
            return
        try:
            model_endpoint(base_url, self.model_wire_var.get())
        except ValueError as exc:
            messagebox.showwarning("模型地址有误", str(exc))
            return
        self.model_check_pending = True
        self.model_status_var.set("正在测试模型连接……")
        threading.Thread(target=self._model_preflight_worker,
                         args=(base_url, api_key, model, "manual", self.model_wire_var.get()), daemon=True).start()

    def _write_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _ensure_service(self) -> bool:
        with self.service_lock:
            if self.closing:
                return False
            return self._ensure_service_locked()

    def _ensure_service_locked(self) -> bool:
        try:
            with urlopen(f"{self.browser_url}/health", timeout=3) as response:
                if response.status == 200:
                    payload = json.loads(response.read().decode("utf-8"))
                    if background_service_ready(payload):
                        self.events.put(("service", "浏览器服务：后台模式已连接"))
                        return True
                    # A previous release may still own the default port. Use
                    # our own service rather than reusing its visible browsers.
                    with socket.socket() as port_probe:
                        port_probe.bind(("127.0.0.1", 0))
                        self.browser_port = port_probe.getsockname()[1]
                    self.browser_url = f"http://127.0.0.1:{self.browser_port}"
        except Exception:
            pass
        if not PYTHON.exists():
            self.events.put(("error", "运行环境缺失，请重新安装 GEO 监测中心。"))
            return False
        REPORTS.mkdir(parents=True, exist_ok=True)
        stdout = (REPORTS / "browser-service.stdout.log").open("a", encoding="utf-8")
        stderr = (REPORTS / "browser-service.stderr.log").open("a", encoding="utf-8")
        try:
            if self.browser_desktop is None:
                self.browser_desktop = BrowserDesktop()
            self.service_process = self.browser_desktop.launch(
                [str(PYTHON), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(self.browser_port)],
                cwd=SERVICE_DIR,
                env=service_environment(self._env(), isolated=self.browser_desktop.handle is not None),
                stdout=stdout,
                stderr=stderr,
            )
        except Exception as exc:
            if self.browser_desktop is not None:
                self.browser_desktop.close()
                self.browser_desktop = None
            self.events.put(("error", f"浏览器服务启动失败：{exc}"))
            return False
        finally:
            stdout.close()
            stderr.close()
        for _ in range(40):
            if self.closing or self.service_process.poll() is not None:
                break
            time.sleep(0.5)
            try:
                with urlopen(f"{self.browser_url}/health", timeout=3) as response:
                    if response.status == 200 and background_service_ready(json.loads(response.read().decode("utf-8"))):
                        self.events.put(("service", "浏览器服务：后台模式已连接"))
                        return True
            except Exception:
                continue
        stop_service(self.service_process)
        if self.browser_desktop is not None:
            self.browser_desktop.close()
            self.browser_desktop = None
        self.events.put(("error", "浏览器服务启动超时，请查看 reports/browser-service.stderr.log"))
        return False

    def _session_exists(self, engine: str) -> bool:
        return self._session_fingerprint(engine) is not None

    def _session_fingerprint(self, engine: str) -> tuple[int, int] | None:
        # Resolve the default service directory at call time so an embedding
        # app or test can redirect SERVICE_DIR after module import.
        session_root = (DATA_DIR / "browser_sessions" if os.environ.get("GEO_DATA_DIR")
                        else SERVICE_DIR / "data" / "browser_sessions")
        try:
            sessions = [session_root / f"{engine}.json"] + sorted(session_root.glob(f"{engine}__*.json"))
            stats = [path.stat() for path in sessions if path.is_file() and path.stat().st_size > 0]
            if not stats:
                return None
            return (max(stat.st_mtime_ns for stat in stats), sum(stat.st_size for stat in stats))
        except OSError:
            return None

    def _saved_session_label(self, engine: str) -> str:
        fingerprint = self._session_fingerprint(engine)
        checked = self.session_verified_at.get(engine)
        if checked and (time.monotonic() - checked[0] >= 120 or checked[1] != fingerprint):
            self.session_verified.pop(engine, None)
            self.session_verified_at.pop(engine, None)
        count = 0
        session_root = (DATA_DIR / "browser_sessions" if os.environ.get("GEO_DATA_DIR")
                        else SERVICE_DIR / "data" / "browser_sessions")
        count += int((session_root / f"{engine}.json").is_file())
        count += sum(1 for path in session_root.glob(f"{engine}__*.json") if path.is_file())
        if not fingerprint:
            return "未保存登录态"
        checked_label = self.session_verified.get(engine)
        if checked_label:
            return checked_label
        return "已保存·待检查" if count == 1 else f"已保存 {count} 个账号·待检查"

    def _refresh_status(self) -> None:
        for engine, _ in ENGINES:
            active = any(key[0] == engine and process.poll() is None
                         for key, process in self.login_processes.items())
            if active:
                self.status_vars[engine].set("浏览器已打开")
            elif self.session_check_pending:
                self.status_vars[engine].set("正在检查登录状态")
            else:
                self.status_vars[engine].set(self._saved_session_label(engine))
        if not self.model_check_pending and not self.session_check_pending and (self.monitor_process is None or self.monitor_process.poll() is not None):
            self.run_button.configure(state="normal" if self.config_path is not None else "disabled")
        self.root.after(1000, self._refresh_status)

    def refresh_now(self) -> None:
        threading.Thread(target=self._ensure_service, daemon=True).start()
        self._write_log("正在刷新浏览器服务状态……")

    def login_one(self, engine: str, account_id: str = "default", label: str = "默认账号") -> None:
        key = (engine, account_id)
        existing = self.login_processes.get(key)
        if existing is not None and existing.poll() is None:
            self._write_log(f"{dict(ENGINES)[engine]} {label} 登录窗口已经打开。")
            return
        if not PYTHON.exists():
            messagebox.showerror("无法启动", f"找不到 Python 环境：{PYTHON}")
            return
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            process = subprocess.Popen(
                [str(PYTHON), str(SERVICE_SCRIPT), engine, "--account", account_id],
                cwd=SERVICE_DIR,
                env=self._env(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=flags,
            )
        except Exception as exc:
            messagebox.showerror("无法启动登录窗口", str(exc))
            return
        self.login_processes[key] = process
        self.status_vars[engine].set("浏览器启动中")
        self._write_log(f"{dict(ENGINES)[engine]} {label} 浏览器已启动，请完成登录。")
        threading.Thread(target=self._read_process, args=(engine, account_id, label, process), daemon=True).start()

    def _read_process(self, engine: str, account_id: str, label: str, process: subprocess.Popen) -> None:
        if process.stdout is not None:
            for line in process.stdout:
                line = line.strip()
                if line:
                    self.events.put(("log", f"[{dict(ENGINES)[engine]}] {line}"))
        code = process.wait()
        self.events.put(("login_done", engine, account_id, label, code))

    def login_all(self) -> None:
        for engine, _ in ENGINES:
            self.login_one(engine)

    def save_login(self, engine: str, account_id: str = "default") -> None:
        process = self.login_processes.get((engine, account_id))
        if process is None or process.poll() is not None:
            return
        try:
            if process.stdin is not None:
                process.stdin.write("\n")
                process.stdin.flush()
            self.status_vars[engine].set("正在保存")
            self.session_verified.pop(engine, None)
            self.session_verified_at.pop(engine, None)
            self._write_log(f"正在保存 {dict(ENGINES)[engine]} 登录态……")
        except OSError as exc:
            self._write_log(f"保存 {engine} 失败：{exc}")

    def manage_accounts(self, engine: str) -> None:
        window = tk.Toplevel(self.root)
        window.title(f"{dict(ENGINES)[engine]}账号管理")
        window.geometry("620x360")
        window.transient(self.root)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)
        columns = ("label", "account_id", "status", "uses")
        tree = ttk.Treeview(window, columns=columns, show="headings", selectmode="browse")
        for column, title, width in (
            ("label", "账号", 180), ("account_id", "编号", 130),
            ("status", "状态", 140), ("uses", "使用次数", 90),
        ):
            tree.heading(column, text=title)
            tree.column(column, width=width, anchor="w")
        tree.grid(row=0, column=0, columnspan=5, sticky="nsew", padx=12, pady=12)

        def refresh() -> None:
            tree.delete(*tree.get_children())
            try:
                with urlopen(f"{self.browser_url}/sessions/{engine}/accounts", timeout=8) as response:
                    accounts = json.loads(response.read().decode("utf-8"))
                labels = {
                    "active": "可用", "cooldown": "冷却中", "needs_login": "需重新登录",
                    "invalid_file": "文件无效", "pending": "等待登录", "missing": "文件缺失",
                    "disabled": "已停用",
                }
                for account in accounts:
                    if account.get("exists") or account.get("status") == "pending":
                        tree.insert("", "end", iid=account["account_id"], values=(
                            account.get("label") or account["account_id"], account["account_id"],
                            labels.get(account.get("status"), account.get("status", "未知")),
                            account.get("use_count", 0),
                        ))
            except Exception as exc:
                self._write_log(f"读取 {dict(ENGINES)[engine]}账号失败：{exc}")

        def add() -> None:
            label = simpledialog.askstring("新增平台账号", f"{dict(ENGINES)[engine]}账号名称：", parent=window)
            if not label or not label.strip():
                return
            try:
                body = json.dumps({"label": label.strip()}, ensure_ascii=False).encode("utf-8")
                request = Request(f"{self.browser_url}/sessions/{engine}/accounts", data=body,
                                  headers={"Content-Type": "application/json"}, method="POST")
                with urlopen(request, timeout=8) as response:
                    account = json.loads(response.read().decode("utf-8"))
                refresh()
                self.login_one(engine, account["account_id"], label.strip())
            except Exception as exc:
                messagebox.showerror("新增账号失败", str(exc), parent=window)

        def remove() -> None:
            selected = tree.selection()
            if not selected:
                return
            account_id = selected[0]
            if not messagebox.askyesno("删除账号", f"删除 {tree.set(account_id, 'label')} 的本地登录态？", parent=window):
                return
            try:
                request = Request(f"{self.browser_url}/sessions/{engine}/accounts/{account_id}", method="DELETE")
                with urlopen(request, timeout=8):
                    pass
                refresh()
                self._write_log(f"已删除 {dict(ENGINES)[engine]}账号 {account_id}。")
            except Exception as exc:
                messagebox.showerror("删除账号失败", str(exc), parent=window)

        def selected_account() -> tuple[str, str] | None:
            selected = tree.selection()
            if not selected:
                messagebox.showinfo("账号管理", "请先选择一个账号。", parent=window)
                return None
            account_id = selected[0]
            return account_id, tree.set(account_id, "label")

        def relogin() -> None:
            selected = selected_account()
            if selected:
                self.login_one(engine, selected[0], selected[1])

        def save_selected() -> None:
            selected = selected_account()
            if selected:
                self.save_login(engine, selected[0])

        ttk.Button(window, text="新增账号", command=add).grid(row=1, column=0, sticky="w", padx=12, pady=(0, 12))
        ttk.Button(window, text="重新登录", command=relogin).grid(row=1, column=1, sticky="w", padx=4, pady=(0, 12))
        ttk.Button(window, text="保存登录态", command=save_selected).grid(row=1, column=2, sticky="w", padx=4, pady=(0, 12))
        ttk.Button(window, text="删除账号", command=remove).grid(row=1, column=3, sticky="w", padx=4, pady=(0, 12))
        ttk.Button(window, text="刷新", command=refresh).grid(row=1, column=4, sticky="e", padx=12, pady=(0, 12))
        refresh()

    def check_sessions_action(self, auto_start: bool = False) -> None:
        if self.session_check_pending or (self.monitor_process is not None and self.monitor_process.poll() is None):
            return
        self.session_check_pending = True
        self.session_check_auto_start = auto_start
        self.session_check_button.configure(state="disabled")
        self.run_button.configure(state="disabled")
        self._write_log("正在实际检查五个平台登录态，检查通过后才会发送问题……")
        threading.Thread(target=self._session_check_worker, daemon=True).start()

    def _session_check_worker(self) -> None:
        fingerprints = {engine: self._session_fingerprint(engine) for engine, _ in ENGINES}
        try:
            if not self._ensure_service():
                raise RuntimeError("后台浏览器服务尚未就绪，请查看运行信息。")
            with urlopen(f"{self.browser_url}/sessions/verify", timeout=55) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, list):
                raise ValueError("登录态检查返回格式不正确")
            self.events.put(("session_check_done", payload, None, fingerprints))
        except Exception as exc:
            self.events.put(("session_check_done", [], str(exc), fingerprints))

    def _start_monitor_process(self) -> None:
        """Launch the monitor after the active login preflight passes."""
        if self.monitor_process is not None and self.monitor_process.poll() is None:
            return
        REPORTS.mkdir(parents=True, exist_ok=True)
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.monitor_process = subprocess.Popen(
            [
                str(PYTHON), str(RECORD_TOOL), "run",
                "--config", str(self.config_path), "--output-dir", str(REPORTS),
                "--browser-url", self.browser_url, "--sessions-verified",
            ],
            cwd=ROOT,
            env=self._monitor_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=flags,
        )
        self.run_button.configure(state="disabled")
        self.active_report_dir = None
        question_count = self.question_count_var.get()
        self._write_log(f"登录态已通过，开始检查 {question_count} 个问题，共 {int(question_count) * len(ENGINES)} 条平台回答。")
        threading.Thread(target=self._read_monitor, args=(self.monitor_process,), daemon=True).start()

    def run_monitor(self) -> None:
        if self.model_check_pending or self.session_check_pending:
            return
        # Rebuild the private task file so edits to the generated question list are used.
        if not self.prepare_task():
            return
        if self.monitor_process is not None and self.monitor_process.poll() is None:
            return
        if self.follow_codex_var.get() and not self.reload_codex_settings():
            return
        base_url = self.model_base_var.get().strip()
        model = self.model_name_var.get().strip()
        api_key = self.model_key_var.get().strip()
        if not (base_url and model and api_key):
            messagebox.showwarning("需要配置 AI 判定模型", "引用核对现在由 AI 完成。请填写接口地址、模型名称和 API Key 后再开始监测。")
            return
        try:
            model_endpoint(base_url, self.model_wire_var.get())
        except ValueError as exc:
            messagebox.showwarning("模型地址有误", str(exc))
            return
        self.active_ai_settings = {"base_url": base_url, "model": model, "api_key": api_key, "wire_api": self.model_wire_var.get()}
        self.model_check_pending = True
        self.run_button.configure(state="disabled")
        self._write_log("正在验证 AI 引用判定模型，验证成功后检查平台登录态……")
        threading.Thread(target=self._model_preflight_worker,
                         args=(base_url, api_key, model, "monitor", self.model_wire_var.get()), daemon=True).start()

    def _model_preflight_worker(self, base_url: str, api_key: str, model: str, purpose: str, wire_api: str) -> None:
        try:
            check_model(base_url=base_url, api_key=api_key, model=model, wire_api=wire_api)
            self.events.put(("model_preflight_done", None, purpose, model_endpoint(base_url, wire_api)))
        except Exception as exc:
            self.events.put(("model_preflight_done", str(exc), purpose, model_endpoint(base_url, wire_api)))

    def _read_monitor(self, process: subprocess.Popen) -> None:
        if process.stdout is not None:
            for line in process.stdout:
                line = line.strip()
                if line:
                    self.events.put(("log", line))
        code = process.wait()
        self.events.put(("monitor_done", code))

    def open_latest(self) -> None:
        entries = self._report_entries()
        if not entries:
            messagebox.showinfo("暂无报告", "完成一次监测后，这里会打开最新报告。")
            return
        report = entries[0]["html"]
        if report.exists():
            os.startfile(str(report))
        else:
            messagebox.showwarning("报告不完整", f"找不到：{report}")

    @staticmethod
    def _report_time(folder: Path, data: dict) -> str:
        """Return a readable Beijing time, falling back to the folder mtime."""
        value = data.get("generated_at")
        if isinstance(value, str) and value.strip():
            try:
                from datetime import datetime, timedelta, timezone

                moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return moment.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass
        match = re.match(r"geo-record-(\d{8})-(\d{6})(?:-|$)", folder.name)
        if match:
            from datetime import datetime

            moment = datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S")
            return moment.strftime("%Y-%m-%d %H:%M:%S")
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(folder.stat().st_mtime))

    def _report_entries(self) -> list[dict[str, object]]:
        """Collect every saved report without requiring results.json to exist."""
        entries: list[dict[str, object]] = []
        for folder in REPORTS.glob("geo-record-*"):
            if not folder.is_dir():
                continue
            html_path = folder / "record.html"
            md_path = folder / "record.md"
            json_path = folder / "results.json"
            data: dict = {}
            if json_path.is_file():
                try:
                    loaded = json.loads(json_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        data = loaded
                except (OSError, UnicodeError, json.JSONDecodeError):
                    data = {}
            brand = data.get("brand")
            if not isinstance(brand, str) or not brand.strip():
                brand = "未记录"
                if md_path.is_file():
                    try:
                        with md_path.open(encoding="utf-8") as report_file:
                            heading = report_file.readline().strip()
                        match = re.fullmatch(r"# (.+?) GEO 引用监测记录", heading)
                        if match:
                            brand = match.group(1)
                    except (OSError, UnicodeError):
                        pass
            total = data.get("total_questions")
            completed = data.get("completed_questions")
            if isinstance(total, int) and isinstance(completed, int):
                progress = f"{completed}/{total} 个问题"
                status = "已完成" if completed >= total and not data.get("run_error") else "阶段性报告"
                if data.get("run_error"):
                    status = "中断"
            elif json_path.is_file():
                progress, status = "数据格式待检查", "可打开"
            else:
                progress, status = "无结果数据", "旧报告"
            if not html_path.is_file():
                status = "仅 Markdown" if md_path.is_file() else "文件缺失"
            entries.append({
                "folder": folder,
                "html": html_path,
                "md": md_path,
                "brand": brand,
                "time": self._report_time(folder, data),
                "progress": progress,
                "status": status,
                "sort_time": self._report_time(folder, data),
            })
        entries.sort(key=lambda item: str(item["sort_time"]), reverse=True)
        return entries

    def open_history(self) -> None:
        """Show all saved reports and open one without running a new check."""
        if self.history_window is not None and self.history_window.winfo_exists():
            self.history_window.lift()
            self._refresh_history()
            return
        window = tk.Toplevel(self.root)
        self.history_window = window
        window.title("历史报告")
        if self.logo_image is not None:
            window.iconphoto(True, self.logo_image)
        window.geometry("820x430")
        window.minsize(680, 300)
        window.transient(self.root)
        ttk.Label(window, text="历史报告（按时间倒序）").pack(anchor="w", padx=12, pady=(12, 4))
        ttk.Label(window, text="双击一行即可阅读历史报告；关闭软件后报告仍会保留。", foreground="#555555").pack(anchor="w", padx=12, pady=(0, 8))
        frame = ttk.Frame(window, padding=(12, 0, 12, 8))
        frame.pack(fill="both", expand=True)
        columns = ("time", "brand", "progress", "status", "folder")
        tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
        self.history_tree = tree
        tree.heading("time", text="检查时间")
        tree.heading("brand", text="品牌")
        tree.heading("progress", text="进度")
        tree.heading("status", text="状态")
        tree.heading("folder", text="报告目录")
        tree.column("time", width=155, anchor="w")
        tree.column("brand", width=100, anchor="w")
        tree.column("progress", width=105, anchor="center")
        tree.column("status", width=105, anchor="center")
        tree.column("folder", width=250, anchor="w")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        tree.bind("<Double-1>", lambda _event: self.open_selected_history())
        buttons = ttk.Frame(window, padding=(12, 0, 12, 12))
        buttons.pack(fill="x")
        ttk.Button(buttons, text="打开选中报告", command=self.open_selected_history).pack(side="left")
        ttk.Button(buttons, text="刷新列表", command=self._refresh_history).pack(side="left", padx=8)
        ttk.Button(buttons, text="趋势分析", command=self.open_trend_analysis).pack(side="left")
        ttk.Button(buttons, text="关闭", command=window.destroy).pack(side="right")
        window.protocol("WM_DELETE_WINDOW", window.destroy)
        self._refresh_history()

    def _refresh_history(self) -> None:
        tree = self.history_tree
        if tree is None or not tree.winfo_exists():
            return
        for item in tree.get_children():
            tree.delete(item)
        entries = self._report_entries()
        for entry in entries:
            tree.insert(
                "", "end", iid=entry["folder"].name,
                values=(entry["time"], entry["brand"], entry["progress"], entry["status"], entry["folder"].name),
            )
        if not entries:
            tree.insert("", "end", iid="empty", values=("暂无报告", "", "", "", "完成一次监测后会出现在这里"))

    def open_selected_history(self) -> None:
        tree = self.history_tree
        if tree is None or not tree.winfo_exists():
            return
        selected = tree.selection()
        if not selected or selected[0] == "empty":
            return
        entry = next((item for item in self._report_entries() if item["folder"].name == selected[0]), None)
        if entry is None:
            messagebox.showwarning("报告已移动", "这份报告已不在列表中，请刷新历史报告。")
            return
        report = entry["html"]
        if isinstance(report, Path) and report.exists():
            os.startfile(str(report))
        elif isinstance(entry["md"], Path) and entry["md"].exists():
            os.startfile(str(entry["md"]))
        else:
            messagebox.showwarning("报告不完整", f"找不到 HTML 或 Markdown 报告：{entry['folder']}")

    def open_trend_analysis(self) -> None:
        """Show local history filters and create a readable trend report."""
        if self.trend_window is not None and self.trend_window.winfo_exists():
            self.trend_window.lift()
            return
        from tools.history_trends import available_brands

        brands = available_brands(REPORTS)
        if not brands:
            messagebox.showinfo("暂无可分析记录", "历史报告中还没有可用于趋势分析的原始检测数据。")
            return
        window = tk.Toplevel(self.root)
        self.trend_window = window
        window.title("历史趋势分析")
        if self.logo_image is not None:
            window.iconphoto(True, self.logo_image)
        window.geometry("480x240")
        window.minsize(420, 220)
        window.transient(self.history_window or self.root)
        window.columnconfigure(1, weight=1)

        ttk.Label(window, text="历史检测趋势").grid(row=0, column=0, columnspan=2,
                                                      sticky="w", padx=16, pady=(16, 4))
        ttk.Label(window, text="只分析本机保存的结果，不会重新查询平台。", foreground="#555555").grid(
            row=1, column=0, columnspan=2, sticky="w", padx=16, pady=(0, 12)
        )

        ttk.Label(window, text="品牌").grid(row=2, column=0, sticky="w", padx=(16, 10), pady=6)
        brand_values = ["全部品牌", *brands]
        if self.trend_brand_var.get() not in brand_values:
            self.trend_brand_var.set(brands[0])
        ttk.Combobox(window, textvariable=self.trend_brand_var, values=brand_values,
                     state="readonly").grid(row=2, column=1, sticky="ew", padx=(0, 16), pady=6)

        ttk.Label(window, text="时间范围").grid(row=3, column=0, sticky="w", padx=(16, 10), pady=6)
        ttk.Combobox(window, textvariable=self.trend_period_var,
                     values=("全部时间", "近 7 天", "近 30 天", "近 90 天"),
                     state="readonly").grid(row=3, column=1, sticky="ew", padx=(0, 16), pady=6)

        ttk.Label(window, text="关键词筛选").grid(row=4, column=0, sticky="w", padx=(16, 10), pady=6)
        ttk.Entry(window, textvariable=self.trend_keyword_var).grid(
            row=4, column=1, sticky="ew", padx=(0, 16), pady=6
        )
        actions = ttk.Frame(window, padding=(16, 10, 16, 14))
        actions.grid(row=5, column=0, columnspan=2, sticky="ew")
        ttk.Button(actions, text="生成趋势报告", command=self.generate_trend_report).pack(side="left")
        ttk.Button(actions, text="关闭", command=window.destroy).pack(side="right")
        window.protocol("WM_DELETE_WINDOW", window.destroy)

    def generate_trend_report(self) -> None:
        from datetime import datetime
        from uuid import uuid4

        from tools.history_trends import build_trend_html

        selected_brand = self.trend_brand_var.get()
        brand = None if selected_brand == "全部品牌" else selected_brand
        days = {"近 7 天": 7, "近 30 天": 30, "近 90 天": 90}.get(self.trend_period_var.get())
        try:
            report = build_trend_html(
                REPORTS, brand=brand, days=days,
                keyword=self.trend_keyword_var.get().strip() or None,
            )
            destination = REPORTS
            destination.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            path = destination / f"trend-{stamp}-{uuid4().hex[:6]}.html"
            path.write_text(report, encoding="utf-8")
            os.startfile(str(path))
        except (OSError, ValueError, RuntimeError) as exc:
            messagebox.showerror("趋势报告生成失败", str(exc))

    def _drain_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "service":
                    self.service_var.set(event[1])
                    self._write_log(event[1])
                elif kind == "log":
                    self._write_log(event[1])
                    if event[1].startswith("进度 ") and "报告已保存：" in event[1]:
                        report_path = Path(event[1].split("报告已保存：", 1)[1].strip())
                        self.active_report_dir = report_path.parent
                elif kind == "session_check_done":
                    payload, error = event[1], event[2]
                    self.session_check_pending = False
                    self.session_check_button.configure(state="normal")
                    self.session_verified.clear()
                    self.session_verified_at.clear()
                    if error:
                        self._write_log(f"登录态检查失败：{error}")
                        if self.session_check_auto_start:
                            self.run_button.configure(state="normal")
                            messagebox.showerror("登录态检查失败", str(error))
                        else:
                            messagebox.showerror("登录态检查失败", str(error))
                        self.session_check_auto_start = False
                        continue
                    failed = []
                    fingerprints = event[3]
                    checked_at = time.monotonic()
                    for engine, item in complete_session_results(payload, dict(ENGINES)).items():
                        name = dict(ENGINES)[engine]
                        if fingerprints.get(engine) != self._session_fingerprint(engine):
                            item = {"status": "unknown", "logged_in": None,
                                    "detail": "检查期间登录态已变更，请重新检查"}
                        self.session_verified[engine] = session_label(item)
                        self.session_verified_at[engine] = (checked_at, self._session_fingerprint(engine))
                        self._write_log(f"{name}：{session_label(item)}；{item.get('detail', '')}")
                        if not session_ready(item):
                            detail = item.get("detail") or item.get("status") or "检查未通过"
                            failed.append(f"{name}：{detail}")
                    if failed:
                        self._write_log("登录态检查未通过：" + "；".join(failed))
                        if self.session_check_auto_start:
                            self.run_button.configure(state="normal")
                        messagebox.showwarning(
                            "登录检查未通过",
                            "以下平台未通过实际登录检查：\n" + "\n".join(failed)
                            + "\n\n未登录的平台：打开登录窗口，登录后点击“保存登录态”。"
                            + "\n检测失败或超时：重试“检查登录态”；需要安全验证：打开平台完成验证后保存。",
                        )
                    else:
                        self._write_log("五个平台登录态检查通过。")
                        if self.session_check_auto_start:
                            self._start_monitor_process()
                    self.session_check_auto_start = False
                elif kind == "model_preflight_done":
                    self.model_check_pending = False
                    purpose = event[2]
                    if event[1]:
                        self.model_status_var.set("模型连接失败；请核对下方请求地址")
                        if purpose == "monitor":
                            self.run_button.configure(state="normal")
                        self._write_log(f"AI 引用判定模型不可用：{event[1]}")
                        messagebox.showerror("模型请求失败", f"请求地址：{event[3]}\n\n{event[1]}")
                    else:
                        self.model_status_var.set("模型连接成功")
                        self._write_log("AI 引用判定模型已连接。")
                        if purpose == "monitor":
                            self.check_sessions_action(auto_start=True)
                elif kind == "model_done":
                    questions, error, model = event[1], event[2], event[3]
                    self.generate_button.configure(state="normal")
                    if error:
                        self.model_status_var.set("模型接口失败，已生成本地问题")
                        self._write_log(f"模型 {model} 生成问题失败：{error}；已使用本地问题模板。")
                        messagebox.showwarning("模型接口失败", f"{error}\n\n已使用本地模板生成问题，可以继续监测。")
                        self.question_input.delete("1.0", "end")
                        self.question_input.insert("1.0", "\n".join(questions))
                        self.prepare_task()
                    else:
                        self.question_input.delete("1.0", "end")
                        self.question_input.insert("1.0", "\n".join(questions))
                        self.model_status_var.set(f"已使用 {model} 生成 {len(questions)} 个问题")
                        self.prepare_task()
                elif kind == "error":
                    self.service_var.set("浏览器服务：启动失败")
                    self._write_log(event[1])
                    messagebox.showerror("GEO 监测中心", event[1])
                elif kind == "login_done":
                    engine, account_id, label, code = event[1], event[2], event[3], event[4]
                    self.session_verified.pop(engine, None)
                    self.session_verified_at.pop(engine, None)
                    self._write_log(f"{dict(ENGINES)[engine]} {label} 登录窗口已结束（退出码 {code}）。")
                elif kind == "monitor_done":
                    code = event[1]
                    self.run_button.configure(state="normal" if self.config_path is not None else "disabled")
                    if code == 0:
                        report = self.active_report_dir / "record.html" if self.active_report_dir else None
                        if report is not None and report.exists():
                            self._write_log(f"监测完成。报告：{report}")
                            os.startfile(str(report))
                        else:
                            self._write_log("监测进程结束，但未找到报告文件。")
                            messagebox.showerror("报告缺失", "监测结束但未找到报告，请查看运行信息。")
                    else:
                        self._write_log(f"监测结束，退出码 {code}。")
                        if self.active_report_dir and (self.active_report_dir / "record.html").exists():
                            self._write_log(f"已保存阶段性报告：{self.active_report_dir / 'record.html'}")
                            os.startfile(str(self.active_report_dir / "record.html"))
                        messagebox.showerror("监测未完成", "请查看运行信息；已完成部分的报告会自动打开。")
        except queue.Empty:
            pass
        self.root.after(100, self._drain_events)

    def close(self) -> None:
        self.closing = True
        if self.autosave_timer:
            self.root.after_cancel(self.autosave_timer)
        self._save_inputs()
        for process in self.login_processes.values():
            if process.poll() is None:
                process.terminate()
        if self.monitor_process is not None and self.monitor_process.poll() is None:
            self.monitor_process.terminate()
        with self.service_lock:
            stop_service(self.service_process)
            if self.browser_desktop is not None:
                self.browser_desktop.close()
        self.root.destroy()


def main() -> None:
    app_root = tk.Tk()
    GeoMonitorApp(app_root)
    app_root.mainloop()


if __name__ == "__main__":
    main()
