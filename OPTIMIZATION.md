# 优化分析报告

> 生成日期 2026-06-17 · 范围：整仓静态分析 + 重点模块抽样核实
> 行号均已对当前 `develop` 分支核实（除非另行标注）。

## 1. 项目拓扑速览

| 组件 | 路径 | 端口 | 角色 |
|---|---|---|---|
| 主 API | `backend/geo/main.py` (FastAPI+SQLAlchemy) | 8070 | 业务主干，21 个 router |
| GEO 检测 package（**活跃**） | `backend/geo_checker/` | — | 25 类 check，uvicorn 与 CLI 都走这里 |
| 根单体 / archive（**冻结**） | `geo_checker.py` / `archive/…` | — | 上游对照基准 + 历史归档，**不改** |
| browser-service | `services/browser-service/app/main.py` | 8091-8093 | 12 个 Playwright 引擎 adapter |
| sentinel-service | `services/sentinel-service/service.py` | 8090 | 舆情，多租户 PG schema 隔离 |
| telemetry-service | `services/telemetry-service/` | 8092+ | 查询建议（sentence-transformers） |
| ddg-proxy / openrouter-proxy | `services/ddg-proxy` / `…openrouter-proxy` | 8095 / 8096 | 国内出口绕行代理 |
| frontend | `frontend/` (React+Vite) | 3000/5173 | SPA |

---

## 2. 快赢清单（低风险，限于 `backend/geo_checker/`）

| # | 位置 | 问题 | 风险 | 预估收益 |
|---|---|---|---|---|
| Q1 | `orchestrate.py:241-265` `run_silent()` | 25 个 check 全串行手写，而同文件 `_run_checks()`（`:87-183`）已用 `ThreadPoolExecutor(max_workers=10)` 并行。`run_silent` 被 `compare_urls` 多 URL 调用 | 低 | **比对模式 15-25% 提速**；多 URL 时成倍 |
| Q2 | `checks.py:845-876` `flesch_kincaid_grade` | **死代码 + 陷阱**：`checks.py:27` 已 `from .io import … flesch_kincaid_grade`，本地第 845 行又重定义覆盖了导入。两份实现需同步维护 | 极低 | 删本地定义，统一走 `io.py:80`，少 ~30 行 |
| Q3 | `ai.py:43 / 78 / 125` | 函数体内重复 `import re`，而模块顶部 `:13` 已 import | 极低 | 清理，热路径少做无用 import |
| Q4 | `ai.py:32-33 / 65-66 / 112-113 / 146-147 / 176-177 / 207-208` | 429 限流处理为单次 `time.sleep(5)` 后只重试一次，无指数退避、无 jitter、无最大重试上限；二次仍 429 即静默失败 | 低 | 提取统一退避 helper，稳定性提升 |
| Q5 | `checks.py` 3 处 / `services/sentinel-service/service.py` 2 处 `except Exception:` | 裸吞异常，无日志，网络失败与逻辑错误无法区分 | 低 | 至少加日志 / 收窄异常类型，可观测性 |

> **关于 agent 报的 "bio 页双 fetch"（`checks.py:1272` vs `:1317`）**：因为 `fetch()` 走 `_page_cache` 进程内缓存，第二次同 URL 实为缓存命中，**实际开销可忽略**，不列入快赢。仅在重构该函数时顺手复用已有 soup 即可。

---

## 3. 结构性技术债（大改，需排期 + 回归验证）

| 项 | 现状 | 建议 | 风险 |
|---|---|---|---|
| `checks.py` 2977 行 | 单文件聚合 25 类 check | 按类别拆 `checks/{https,robots,sitemap,structured,content,authority,crawl}.py`，`CHECK_REGISTRY` 不变 | 中：需对照根单体回归（CLAUDE.md 已有 moltspay.com 基线） |
| `geo/api/ai_telemetry.py` 3792 行 + ORM 1633 行 | 遥测 API 与模型各自巨型 | 拆事件/查询/聚合子模块 | 中 |
| 12 个浏览器 adapter 高度重复 | 各自实现 导航/等待/引用解析 | 抽公共 mixin 进 `api_engine/base.py`，逐引擎迁移 | 中高：各引擎 DOM 不同构，需逐个验证 |
| FastAPI 0.104 锁死 | 与 pydantic-ai 冲突，agent 被迫独立 venv | 评估升级 0.115+ 合并依赖树 | 高：全后端回归 |

---

## 4. 建议执行顺序

1. **先做 Q2/Q3**（纯清理，零行为变化）→ 单独 commit。
2. **Q1**（并行化 `run_silent`）→ 用 `_run_checks` 替换手写串行，对一个站点跑前后分数一致性校验后提交。
3. **Q4/Q5**（退避 + 异常可观测性）→ 提取 helper，单独 commit。
4. 结构性重构按需单独立项，每项配回归基线。

> 所有改动仅进 `backend/geo_checker/` 与 `services/`，**不碰根 `geo_checker.py` 与 `archive/`**（CLAUDE.md 冻结约定）。
