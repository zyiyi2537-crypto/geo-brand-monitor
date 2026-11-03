# GEO 品牌监测中心

GEO 品牌监测中心（`geo-brand-monitor`）：监测目标品牌与已发布文章在 **DeepSeek、豆包、元宝、文心一言、通义千问** 回答中的提及、排名、引用来源与品牌评价，生成带问题明细、引用证据和饼图的报告。

**判定口径**：品牌是否提及、文章是否引用、品牌评价全部由配置的 AI 模型判定（判定结果必须附逐字证据，脚本校验证据真实性），不是脚本关键词匹配。

## 产品形态

### 桌面版（Windows）

入口 `GEO-Monitor.pyw`。浏览器登录五个平台，用同一批问题真实采集回答与引用来源，再由配置的模型逐题判定。品牌、文章链接、问题、登录态和历史报告保存在本机，报告为 `record.html` / `record.md` / `results.json`。

使用说明见 [QUICKSTART.md](QUICKSTART.md)。

### 服务端嵌入模块（monitor-service）

[`services/monitor-service/`](services/monitor-service/)：把桌面端监测核心（五平台浏览器采集 + AI 判定 + 报告）包装为可部署到服务器、可 iframe 嵌入订阅网站的**多租户服务**。

- 账号与收费由订阅网站负责：主站签发 HS256 JWT，模块按 `tenant_id` 隔离任务与报告
- 可选配额钩子：提交任务时回调主站校验额度（计费单位：1 问题 = 5 次平台采集 + 1 次 AI 判定）
- 五平台登录态与判定模型 Key 是运营资产，只存在于服务端
- 判定与报告口径与桌面版完全一致

接入方法（token 签发、iframe、配额协议、环境变量、Docker）见 [services/monitor-service/README.md](services/monitor-service/README.md)。

## 仓库结构

| 路径 | 说明 |
| --- | --- |
| `geo_monitor_gui.pyw` / `GEO-Monitor.pyw` | 桌面版界面与入口 |
| `tools/` | 监测核心：采集编排（`geo_record`）、AI 判定（`ai_verifier`）、出题（`agent_planner`）、报告趋势 |
| `services/browser-service/` | 五平台 Playwright 采集服务（含登录态管理、扫码授权、服务器镜像） |
| `services/monitor-service/` | 服务端嵌入模块（FastAPI，多租户） |
| `services/telemetry-service/` | 报告渲染（`qualified_report`）与品牌提及聚合 |
| `reports/` | 本地监测报告（`geo-record-*`） |
| `frontend/` / `backend/` | 上游 Vigilath 平台（GEO 审计引擎、历史 Web 工作台），非当前监测链路 |
| `docs/` | 架构、部署、运维文档 |

注意：`backend/geo/api/unified.py` 的旧 Web 工作台使用平台 API + 脚本正则判定，与桌面版 AI 判定口径不同，数据不可直接比较；新的服务端方案以 `monitor-service` 为准。

## 快速开始

桌面版依赖与运行见 [QUICKSTART.md](QUICKSTART.md)。服务端模块本地运行：

```powershell
cd services/monitor-service
python -m venv venv
venv\Scripts\pip install -r requirements.txt
$env:MONITOR_JWT_SECRET = "<与主站共享的密钥>"
$env:MONITOR_ADMIN_TOKEN = "<运营令牌>"
$env:GEO_AI_BASE_URL = "https://api.example.com/v1"
$env:GEO_AI_MODEL = "<模型名>"
$env:GEO_AI_API_KEY = "<判定模型 Key>"
venv\Scripts\uvicorn monitor_service.main:app --port 8080
```

上游 Vigilath 的 CLI 审计（`geo-checker`）与 Web 应用仍可独立运行，见 [docs/README.md](docs/README.md)。

## 安全与部署

- 判定模型 Key、平台登录态、数据库口令等只放被忽略的本地环境文件或密钥管理器，不进仓库
- 服务端部署置于 HTTPS 反向代理之后；对外服务必须开启鉴权与配额
- 上游历史凭据已在改写 Git 历史时移除；分发副本前请删除旧克隆、备份与缓存
- 漏洞报告见 [SECURITY.md](SECURITY.md)

## 开发

```bash
python -m pytest
cd frontend && npm run lint && npm run build
```

贡献规范见 [CONTRIBUTING.md](CONTRIBUTING.md)。审计引擎的可修改副本为 `backend/geo_checker/`，规则见 [CLAUDE.md](CLAUDE.md)。

## 上游致谢与许可证

本项目的审计引擎与部分基础设施代码派生自 [Vigilath](https://github.com/sr007-cxy/Vigilath)（Zen7 Labs，MIT License）。依 MIT 条款保留其版权声明与许可证全文，见 [LICENSE](LICENSE)；相关上游文档一并保留在 `docs/`。

```bibtex
@software{vigilath,
  author    = {Zen7 Labs},
  title     = {Vigilath: GEO and AI Visibility Platform},
  publisher = {GitHub},
  url       = {https://github.com/sr007-cxy/Vigilath}
}
```
