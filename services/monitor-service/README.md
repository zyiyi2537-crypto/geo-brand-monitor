# monitor-service — 可嵌入的 GEO 品牌监测模块

把桌面端 GEO 监测核心（五平台真实浏览器采集 + AI 判定 + 报告）包装成可部署到服务器、
可嵌入订阅网站的多租户服务。**监测口径与桌面端完全一致**：是否提及、是否引用、
品牌评价全部由配置的 AI 模型判定，脚本只做证据校验（逐字摘录、URL 真实性）。

## 架构

```
订阅网站（账号 / 订阅 / 收费，由你现有的站点负责）
   │  用户身份：站点签发 HS256 JWT，?token= 或 postMessage 传入
   ▼
monitor-service (本服务, 端口 8080)
   ├─ /app/            可 iframe 嵌入的监测工作台（纯静态单页）
   ├─ /api/*           用户 API：任务 / 进度 / 报告，按 tenant_id 隔离
   ├─ /api/admin/*     运营 API：登录态 / 判定模型 / 全局队列（管理令牌）
   └─ runner           复用 tools/geo_record + tools/ai_verifier（不改动）
         ▼
   browser-service:8091（五平台登录态，运营资产）
```

## 与桌面端的对应关系

| 桌面端 | 服务端 |
|---|---|
| `tools/geo_record.collect_results` 采集编排 | 原样调用 |
| `tools/ai_verifier.verify_question` AI 判定 | 原样调用（合并判定→失败逐平台兜底） |
| `tools/geo_record.save_run_progress` 增量报告 | 原样调用（中途失败保留阶段性报告） |
| `tools/agent_planner.generate_questions` 出题 | `/api/questions/generate` |
| `geo_monitor_gui.pyw` Tkinter 界面 | `/app/` 静态页 + 订阅网站身份桥 |

Vigilath 的 `backend/geo/api/unified.py`（脚本正则判定、API 引擎）**不在本服务链路内**。

## 环境变量

| 变量 | 必填 | 说明 |
|---|---|---|
| `MONITOR_JWT_SECRET` | 是 | 与订阅网站共享的 HS256 密钥（≥16 字符） |
| `MONITOR_ADMIN_TOKEN` | 是 | 运营端点的管理令牌 |
| `MONITOR_BROWSER_URL` | 否 | browser-service 地址，默认 `http://127.0.0.1:8091` |
| `MONITOR_REPORTS_DIR` | 否 | 报告根目录，默认 `reports/monitor/` |
| `MONITOR_DATA_DIR` / `MONITOR_DB` | 否 | SQLite 任务库位置 |
| `MONITOR_WORKERS` | 否 | 并行任务数，默认 1（共享 browser-service 时保持公平） |
| `MONITOR_JOB_TIMEOUT` | 否 | 单问题采集超时秒，默认 330 |
| `MONITOR_MAX_QUESTIONS` | 否 | 单任务问题数上限，默认 50 |
| `MONITOR_QUOTA_URL` | 否 | 订阅站点配额钩子；不设=不检查 |
| `MONITOR_QUOTA_TOKEN` | 否 | 配额钩子的 Bearer token |
| `MONITOR_QUOTA_FAIL_MODE` | 否 | 钩子不可达时 `deny`（默认）或 `allow` |
| `GEO_AI_BASE_URL` / `GEO_AI_MODEL` / `GEO_AI_API_KEY` / `GEO_AI_WIRE_API` | 是 | 判定模型（运营资产，与桌面 CLI 同名变量；`wire_api` 为 `chat` 或 `responses`） |

## 订阅网站接入

### 1. 签发用户 token

用共享密钥签一个标准 HS256 JWT，payload：

```json
{ "sub": "user-123", "tenant_id": "tenant-456", "name": "张三", "exp": 1767225600 }
```

- `sub`：用户 ID（必填）
- `tenant_id`：租户 ID（可选，缺省用 `sub`）；任务、报告、配额都按它隔离
- `exp`：过期时间（必填，unix 秒）。建议短时效（1~24 小时），iframe 加载时重新签发

Python 签发示例：

```python
import base64, hashlib, hmac, json, time

def sign_user_token(secret: str, user_id: str, tenant_id: str = "", name: str = "", ttl: int = 86400) -> str:
    def b64(data: dict) -> str:
        raw = json.dumps(data, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    header = b64({"alg": "HS256", "typ": "JWT"})
    payload = b64({"sub": user_id, "tenant_id": tenant_id or user_id,
                   "name": name, "exp": int(time.time()) + ttl})
    signing = f"{header}.{payload}".encode()
    sig = hmac.new(secret.encode(), signing, hashlib.sha256).digest()
    return f"{header}.{payload}." + base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
```

### 2. 嵌入工作台

```html
<iframe src="https://geo.your-domain.com/app/?token={{ signed_jwt }}"
        style="width:100%;height:900px;border:0"></iframe>
```

也支持不带 token 加载后用 `postMessage` 注入：

```js
iframe.contentWindow.postMessage({type: 'geo-token', token: signed_jwt}, 'https://geo.your-domain.com');
```

### 3. 配额钩子（可选）

设 `MONITOR_QUOTA_URL` 后，**提交任务时**服务会 POST：

```json
{ "tenant_id": "tenant-456", "questions": 12,
  "cost": { "platform_queries": 60, "ai_verdicts": 12 } }
```

响应 `{"allowed": true}` 放行，`{"allowed": false, "reason": "本月额度已用完"}` 返回 402。
钩子超时/不可达按 `MONITOR_QUOTA_FAIL_MODE` 处理。计费单位建议：
**1 问题 = 5 次平台采集 + 1 次 AI 判定**。

## 用户 API

全部需要 `Authorization: Bearer <jwt>`（报告链接也接受 `?token=` 便于新开窗口）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/me` | 当前身份 |
| POST | `/api/jobs` | 建任务 `{brand, articles:[{title,url}], questions:[...]}` → 202 |
| POST | `/api/questions/generate` | `{brand, article_urls, keywords}` → 生成核对问题 |
| GET | `/api/jobs` | 本租户任务列表 |
| GET | `/api/jobs/{id}` | 任务状态（轮询进度） |
| GET | `/api/jobs/{id}/report` | record.html 报告 |
| GET | `/api/jobs/{id}/results` | results.json 原始证据 |
| GET | `/api/platform-status` | 五平台就绪状态（客户视图） |

## 运营 API

`Authorization: Bearer <MONITOR_ADMIN_TOKEN>`：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/admin/jobs` | 全租户任务队列 |
| GET | `/api/admin/browser-sessions` | 五平台登录态详情与检测结果 |
| GET | `/api/admin/model` | 判定模型配置（Key 只回显是否已设） |
| POST | `/api/admin/model/test` | 判定模型连接测试 |

## 登录态管理（两条路）

1. **桌面迁移**：桌面版登录后把 `%LOCALAPPDATA%\GEO-Monitor\browser_sessions` 下的
   会话文件复制到服务器 browser-service 的 `data/browser_sessions/`（可参考
   `scripts/harvest_sessions.py` 的收割逻辑）。
2. **服务器直登**：browser-service 自带 `qr_authorize.py` + `setup_vnc.sh`（noVNC），
   在服务器上打开扫码授权页面登录；`session_verifier` 定时校验，`/api/admin/browser-sessions`
   可随时看状态。

登录态是运营资产：客户永远看不到也管理不了，监测失败会明确标注"登录预检未通过"，
不会把失败记成"未提及"。

## 本地运行

```powershell
cd services/monitor-service
python -m venv venv
venv\Scripts\pip install -r requirements.txt
$env:MONITOR_JWT_SECRET = "dev-secret-at-least-16-chars"
$env:MONITOR_ADMIN_TOKEN = "dev-admin-token"
$env:GEO_AI_BASE_URL = "https://api.example.com/v1"
$env:GEO_AI_MODEL = "your-model"
$env:GEO_AI_API_KEY = "sk-..."
venv\Scripts\uvicorn monitor_service.main:app --port 8080
```

## Docker

```bash
docker build -f services/monitor-service/Dockerfile.server -t geo-monitor .
docker run -d -p 8080:8080 --env-file .env.monitor \
  -v geo-reports:/srv/reports -v geo-data:/srv/data geo-monitor
```

browser-service 单独部署（`services/browser-service/Dockerfile.server`），
`MONITOR_BROWSER_URL` 指向它。生产环境请置于 HTTPS 反向代理之后。

## 边界与口径

- **只有 AI 判定口径**：`brand_mentioned` / `citation_status` 由判定模型给出，
  脚本校验证据（摘录必须逐字、URL 必须真实存在、来源未收全不得判"未引用"）。
  与旧 `unified.py` 的正则口径不同，历史数据不可直接比较。
- 五平台的真实 API 回答与 App/网页回答可能不同；本模块走浏览器登录态采集，
  与消费端 App 的回答口径一致。
- 多副本部署前需先把 SQLite 换成共享数据库（`store.py` 是单点，接口已隔离好）。
