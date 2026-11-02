# 舆情系统架构 (Sentinel)

> **Status: historical.** This describes the pre-PostgreSQL implementation.
> Current behavior is documented in
> [docs/integrations/sentinel.md](../../../docs/integrations/sentinel.md) and
> [the service README](../README.md).

> 状态:活跃,最后更新 2026-05-08
> 范围:`services/sentinel-service/` + `backend/geo/services/sentiment_*` + `frontend/src/pages/Dashboard/sentiment/`
> 当前能力边界见
> [`docs/integrations/sentinel.md`](../../../docs/integrations/sentinel.md)。

---

## 1. 一句话定位

**Sentinel = 单租户配置 / 多账号隔离的"发现 → 分析 → 简报 → 回应"舆情管线**,LLM 原生(plan + analyze + brief + draft 四个 LLM 步骤),数据源 = 3 通用搜索引擎 + 14 个垂直爬虫,共 15 个候选平台。

---

## 2. 物理拓扑

```
┌────────────────────────────┐    HTTPS     ┌────────────────────────────────┐
│  Frontend (React/Vite)     │  ─────────▶  │  GEO backend (FastAPI, port 8000)│
│  Dashboard/sentiment/      │              │  geo/api/sentiment.py           │
│   ├─ TodayTab              │              │  geo/services/                  │
│   ├─ ArticlesTab           │              │   ├─ sentiment_scheduler.py     │
│   └─ BriefsTab             │              │   ├─ sentiment_pipeline.py      │
│  + OnboardingWizard        │              │   └─ sentinel_client.py ────┐   │
│  + SettingsPage            │              │  Postgres/SQLite (主库):    │   │
└────────────────────────────┘              │   sentiment_accounts/        │   │
                                            │   sentiment_knowledge/        │   │
                                            │   sentiment_run_logs          │   │
                                            └──────────────────────────────┼───┘
                                                                            │
                                          HTTP (X-OpenAI-Key header)        │
                                                                            ▼
                                          ┌─────────────────────────────────────┐
                                          │  sentinel-service (FastAPI, 8090)   │
                                          │  service.py + 6 子模块               │
                                          │   ├─ search/  (plan + 3 engines)    │
                                          │   ├─ crawler/ (14 垂直爬虫)          │
                                          │   ├─ analyzer/ (LLM 13+ 维)          │
                                          │   ├─ brief/    (map-reduce)          │
                                          │   ├─ response/ (3 档草稿 + HITL)     │
                                          │   └─ storage/  (per-account SQLite) │
                                          │  data/account_{id}/yuqing.db        │
                                          └─────────────────────────────────────┘
                                                          │
                                                          ▼
                                          上游:DDG/Bing/Baidu + 14 站点 + LLM
```

**职责切分**:
- **Frontend**:展示 + 配置 UI;不直连 sentinel,只调 GEO backend。
- **GEO backend**:身份/会员/账号配置;拥有 *主库* `sentiment_accounts`(状态机的真身);定时调度;邮件推送;封装 sentinel HTTP RPC。
- **sentinel-service**:无身份概念,只认 `account_id` + `ticker`;每个 account 一个独立 SQLite;不知会员、不发邮件、不做调度。

> 多租户隔离 = backend 主库一张账号表 + sentinel 每账号一个 SQLite。两边 PK/FK 不耦合,只靠 `account_id` 这个数字传递。

---

## 3. 端到端数据流

定时(每小时 :05)或手动触发后,**单账号 pipeline** 顺序如下:

```
[backend] sentiment_scheduler.run_hourly_job()
       │  遍历 active accounts
       ▼
[backend] sentiment_pipeline.run_pipeline_for_account(account_id, trigger)
       │  ① _mark_running()  → 主库状态机 = running
       │
       ├─▶ sentinel_client.run_monitor    →  POST /run-monitor   (LLM plan + 3 engine SERP)
       │
       ├─▶ 14 个 crawler 并行(ThreadPoolExecutor max_workers=8)
       │     eastmoney / xueqiu / sina_finance / sina_stock_news / cls /
       │     gelonghui / wallstreetcn / kr36 / yicai / baidu_tieba /
       │     eastmoney_news / eastmoney_announcement / eastmoney_research /
       │     eastmoney_industry
       │     → 每个独立 try/except,单点失败不影响其它
       │
       ├─▶ sentinel_client.run_analyze    →  POST /run-analyze   (LLM 逐条打分)
       │
       ├─▶ sentinel_client.run_brief      →  POST /run-brief     (LLM map-reduce 简报)
       │
       ├─▶ _push_brief_email()  (notify_emails 非空时,Resend 通道)
       │
       └─▶ _mark_success() / _mark_failed()  → 主库状态机 + run_log 落盘
```

**响应草稿**(`/run-respond`)是**用户在前端点"生成回应"时单独按需触发**,不在 hourly pipeline 里。

---

## 4. sentinel-service 模块清单

| 模块 | 关键文件 | 入口 | 产物 |
|---|---|---|---|
| HTTP 入口 | `service.py` | 14 个 POST + 5 个 GET | `{status, data, error}` |
| 计划生成 | `search/plan.py` | `generate_monitoring_plan()` | JSON plan(platforms + queries) |
| SERP 收集 | `search/pipeline.py` | `run_plan()` | 写入 `posts` |
| 搜索引擎 | `search/{cnbing,baidu,ddg}.py` | `*_search()` | `[{title,href,body}]` |
| 垂直爬虫 | `crawler/*.py` × 14 | 各 Client 类 | 写入 `posts` |
| 分析 | `analyzer/pipeline.py` + `prompts.py` | `analyze_symbol()` | 写入 `analyses` |
| 简报 | `brief/generate.py` | `generate_brief()` | 写入 `briefs` |
| 回应 | `response/draft.py` | `generate_drafts()` | 写入 `drafts` |
| 存储 | `storage/db.py` | `connect()` + `upsert_*` | per-account SQLite |
| LLM 抽象 | `llm_client.py` | `chat_create()` | OpenAI/GLM/Qwen/DeepSeek |
| 知识库 | `knowledge/*.md` × 3 | draft 时按需加载 | brand_voice / legal_redlines / response_playbook |

### 4.1 search/plan.py — 平台 Catalog

`PLATFORM_CATALOG` 是**整个系统的平台真值表**(15 项,雪球/东财/微博/知乎/36氪/财新/B站/头条/微信/小红书/快手/贴吧/知道/百度新闻/Reddit)。

三处必须保持对齐:
1. `search/plan.py:PLATFORM_CATALOG`  ← LLM 选平台时的可选项
2. `backend/geo/services/sentinel_client.py:_PLATFORM_CODE_TO_DOMAIN`  ← FE 传 code,backend 翻译成域名
3. `frontend/src/pages/Dashboard/sentiment/tabs/ArticlesTab.tsx:FIXED_SOURCES` + `i18n/{en,zh}.ts:sourceLabels`  ← UI 上的固定筛选列

### 4.2 search/pipeline.py — 引擎顺序

默认 `engines = ["cnbing", "baidu", "ddg"]`(最近一次实测调整,见 `service.py:200`):
- **cnbing**:国内直连最稳,放第一
- **baidu**:带 cookie 索引最全,次之;无 cookie 几次后被验证页拦截
- **ddg**:国内机房经常返空,兜底

并行执行,URL 维度去重,按 `domain_to_source()` 映射成 `posts.source`。

### 4.3 analyzer — 13+ 维抽取

`ANALYZER_SYSTEM` prompt 稳定不变(吃 OpenAI 的 prompt cache),输出 17 字段 JSON:
`is_relevant / filter_reason / summary / sentiment_label / sentiment_score / emotions[] / topics[] / entities[] / stance / intent / factuality / risk_level / risk_signals[] / influence_potential / hidden_meaning / citations[] / reasoning`

并发由 `LLM_ANALYZE_CONCURRENCY`(默认 5)控制;免费档(GLM)限速重试时整体跑 20–30 分钟很常见 → 这就是 backend `TIMEOUT_ANALYZE = 1800` 的来源。

### 4.4 brief — Map-Reduce

- **Map**:按 `batch_size=20` 分块,每块 LLM 输出 `{topic_notes, risks, top_picks}`
- **Reduce**:全局聚合 + 统计数据 → 中文 Markdown 简报(600–1000 字,五段式)
- 输入用 `analyses_for_day(symbol, date)`,**按 `ingested_at` 过滤,不是 `publish_time`**(避免历史帖错过今日简报,提交 `c3ffbfa`)
- KPI 统计仅计入 `is_relevant=1`(提交 `f5888b7`)

### 4.5 response/draft — HITL 三档

每次产出三个变体(conservative / standard / proactive)+ `recommendation` + `hitl_required=true` + `hitl_notes`。系统提示拼了 `knowledge/` 三份文档(brand_voice / legal_redlines / response_playbook)。

---

## 5. backend 编排层

### 5.1 sentiment_scheduler.py — APScheduler

- `BackgroundScheduler` + `SQLAlchemyJobStore`(jobs 落主库,容器重启不丢)
- **leader 选举**:`GEO_SCHEDULER_LEADER=1` 才启动,避免多 worker 重复触发
- `sentinel_hourly`:cron 每小时 :05,`max_instances=1`(防重叠) + `coalesce` + `misfire_grace_time=1800`
- `sentinel_cleanup`:每 10 分钟扫一次,把超 60 分钟无更新的 `running` 强制改 `failed`(僵尸回收)

### 5.2 sentiment_pipeline.py — 单账号编排

状态机 = 主库 `sentiment_accounts.last_run_status`(`pending|running|success|failed`)+ `sentiment_run_logs` 历史表。
关键守卫:
- `active=False` → skipped
- `last_run_status='running'` → skipped(防重入,与 scheduler 的 max_instances=1 双保险)
- 14 爬虫的失败被吞进 `crawlers_stats[name].error`,**不算 pipeline 失败**;只有 monitor/analyze/brief 任一异常才标 failed

### 5.3 sentinel_client.py — 5 + N RPC

| 操作 | 超时 | 备注 |
|---|---|---|
| `run_monitor` | 1200s | LLM plan + N 引擎 query |
| `run_analyze` | 1800s | 免费 LLM 限速重试 |
| `run_brief` | 1200s | map-reduce |
| `run_respond` | 120s | 单次 LLM |
| `crawl_*`(14 个) | 30–60s | 走 `_crawl_generic()` 复用 |
| `list_*` / `get_*` / `health` | 15s | 读 sentinel SQLite |

`_unwrap()` 把 sentinel 的 `{status:"failed", error, category}` 翻译成 `SentinelError`,带 category 让上游分清"业务失败"还是"系统异常"。

---

## 6. 数据模型

### 6.1 主库(GEO,Postgres/SQLite,被 backend 拥有)

- `sentiment_accounts`:用户 ↔ 监测账号 1:N;持有 `target/ticker/aliases/intent/keywords(_groups)/excludes/media_allowlist/notify_emails/active` + 状态机字段。`(user_id, ticker)` 唯一约束。
- `sentiment_knowledge`:每账号 3 条(brand_voice / legal_redlines / response_playbook);UI 编辑后由 pipeline 透传给 sentinel `/run-respond` 的 `knowledge` 参数。
- `sentiment_run_logs`:每次触发一行,带 trigger / started_at / ended_at / status / error / stats_json / duration_s。

### 6.2 Sentinel 库(per-account SQLite,被 sentinel-service 拥有)

路径 `data/account_{id}/yuqing.db`,5 张表:

| 表 | 主键 | 用途 | 关键字段 |
|---|---|---|---|
| `posts` | (source, post_id) | 原始帖 / SERP 结果 | `ingested_at`(今日筛选键),WAL 模式 |
| `analyses` | (source, post_id) | LLM 分析结果 | `is_relevant`(KPI 入选门槛),`risk_level`,`sentiment_*` |
| `briefs` | id | Markdown 简报 | `(symbol, date)` 联合索引 |
| `drafts` | id | 三档回应草稿 | `variant`,可挂 post 或 topic |
| `query_runs` | (symbol, query) | adaptive timelimit | DDG `d/w/m/y` 时间桶按 gap 自适应 |

### 6.3 多租户隔离机制(关键)

sentinel-service 是从单租户 `yuqin` 包改造而来,`storage.connect()` 路径在 import 时被多个子模块捕获。`service.py:35-127` 的做法:

1. `_current_account: ContextVar` 持当前请求的 account_id
2. **Import yuqin 之前**就 monkey-patch `storage.db.connect` 和 `storage.connect`
3. Import 之后,再显式回写 `search.pipeline / analyzer.pipeline / brief.generate / response.draft` 这四个模块里已绑定的 `connect` 引用
4. 启动时打印 patch 状态,出问题肉眼可查

> 这块 fragile,有任何子模块新增对 `connect()` 的早期捕获,就要在 service.py 里加一行 patch。

---

## 7. 前端切片

`frontend/src/pages/Dashboard/sentiment/`:

| 入口 | 数据源(GEO 后端) | 展示 |
|---|---|---|
| `Sentiment.tsx`(三 tab 容器 + StatusBanner) | `sentiment_accounts` | 当前账号 + 任务状态 |
| `tabs/TodayTab.tsx` | `/api/sentiment/{id}/today?ticker=` | KPI 卡 + 趋势 + 风险饼 + 最新 brief + Top posts |
| `tabs/ArticlesTab.tsx` | `/api/sentiment/{id}/posts?ticker=` | 5 维筛选(情感/风险/平台/关键词/仅相关)+ 排序 + 详情 + 生成草稿 |
| `tabs/BriefsTab.tsx` | `/api/sentiment/{id}/briefs` + `/briefs/{bid}` | 列表 + Markdown 渲染 + PDF 导出(html2canvas + jsPDF) |
| `OnboardingWizard.tsx` | `POST /api/sentiment` | 首次创建账号 + run_now |
| `SettingsPage.tsx` | `PUT /api/sentiment/{id}` + `KnowledgeEditor` | 编辑配置 / 知识库三文档 |

`StatusBanner` 在 `failed` 状态下**静默不渲染**(memory: `feedback_sentiment_failed_silent.md`)。

`sentiment_score` 显示百分比,`stance/intent/factuality` 三个 enum 走 i18n 字典(memory: `feedback_sentiment_display_format.md`)。

---

## 8. 几个不显然的设计决策

1. **"今日"语义 = ingested_at,不是 publish_time**。历史帖被新 query 拉回来时算"今日讨论",符合"我们今天看到了什么"的产品语义。
2. **KPI 仅入 `is_relevant=1`**。LLM 当过滤器,跨主体噪声(同名公司、谐音梗)被过滤后再统计。
3. **15 平台 catalog 是真值,FE 的固定列表必须跟上**。最近一次提交(`e422f89`)就是把 FE 的"抖音/Twitter"老列表换成对齐 catalog 的 15 项。
4. **引擎顺序按实测排**(cnbing > baidu > ddg)。当前能力边界见
   [Sentinel 集成说明](../../../docs/integrations/sentinel.md)。
5. **14 爬虫并行 + 单点失败容忍**。多数老爬虫(xueqiu/sina/yicai 等)因为 WAF/API 变更经常 502,但保留着,失败被吞,新加的 eastmoney 系 + sina_stock_news 是稳定主力。
6. **状态机有两层**:scheduler 的 `max_instances=1` 防同进程重叠,pipeline 内部的 `last_run_status='running'` 防跨进程/跨触发源(cron + 手动)重叠,僵尸清理兜底进程崩溃。
7. **LLM provider 默认 GLM**(`glm-4.5-flash`),便宜但 RPM 低 → analyze 可能 20–30 分钟。这就是 backend 给 1800s 超时的原因。

---

## 9. 我的理解(便于反馈)

- **核心切面:GEO backend 是"账号/会员/状态机"的真身,sentinel-service 是"无身份的纯加工厂"**。两边只靠 `account_id` 数字耦合,sentinel 不需要懂会员、不发邮件、不做调度。这种切法的好处是 sentinel 可以独立部署/独立替换;代价是 patch yuqin 的 `connect` 这件事很 fragile。
- **15 平台 catalog 是 single source of truth,但物理上散在 4 处**(plan.py / sentinel_client.py / FE i18n / FE FIXED_SOURCES)。这类"必须保持同步"的清单是回归热点。可以考虑把 catalog 单独出一个 JSON 文件,FE 通过 `/api/sentiment/platforms` 拿到,后端从同一份 JSON 读;但短期人工对齐成本不高,看是否值得。
- **数据源 = "3 通用搜索引擎广撒网" + "14 垂直爬虫深耕"**。垂直爬虫主力是 EastMoney 系(5 个端点,都吃 ticker)+ sina_stock_news,其他多数已经只是"先放着,失败容忍"的状态。
- **LLM 用法分四档**(plan / analyze / brief / draft),三个用中等模型(`gpt-4o-mini` / `glm-4.5-flash`),只有 draft 用更大的模型(`gpt-4.1`),因为对外发布,稳定性 > 成本。
- **任务状态机是工程上最多坑的地方**:scheduler.max_instances=1 + pipeline.防重入 + cleanup_zombies 三层守卫,加 frontend 静默 failed,避免给用户暴露中间错误态。
- **缺口**:见 gap 文档(对慧科)— 核心是覆盖深度(尤其负面/小红书)、实时性(分钟级 vs 小时级)、关系图谱(目前没有)。

---

## 10. 关键路径速查

| 想看 X | 去 Y |
|---|---|
| 改加 / 改 API | `services/sentinel-service/service.py` |
| 改 / 加爬虫 | `services/sentinel-service/crawler/<source>.py` + `sentinel_client.py` 加封装 + `sentiment_pipeline.py` 加进 crawler_tasks |
| 改 LLM prompt(分析) | `services/sentinel-service/analyzer/prompts.py` |
| 改简报模板 | `services/sentinel-service/brief/generate.py`(MAP_SYSTEM / REDUCE_SYSTEM) |
| 改回应模板 | `services/sentinel-service/response/draft.py`(DRAFT_SYSTEM_HEADER + `knowledge/*.md`) |
| 改调度 | `backend/geo/services/sentiment_scheduler.py` |
| 改 pipeline 串联 | `backend/geo/services/sentiment_pipeline.py` |
| 改账号配置/状态 | `backend/geo/models/sentiment.py` + `backend/geo/api/sentiment.py` |
| 改 FE 筛选列 | `frontend/src/pages/Dashboard/sentiment/tabs/ArticlesTab.tsx` + `i18n/{en,zh}.ts` |
| 加 / 改平台 | 4 处同步:plan.py / sentinel_client.py / ArticlesTab.tsx / i18n |
