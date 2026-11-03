# GEO 品牌监测服务器

面向客户、可嵌入现有订阅网站的 GEO 监测服务源码。部署到 Linux 服务器后，客户通过网页提交品牌、文章链接和问题，服务器采集 DeepSeek、豆包、元宝、文心一言、通义千问的网页回答，再由配置的 AI 模型判断品牌提及、文章引用、评价与证据，生成报告。

运行入口是 FastAPI 服务和浏览器采集容器。用户无需安装 Windows 程序；注册、订阅与收费由接入网站负责。

## 服务器部署

需要 Linux、Docker Engine 和 Docker Compose v2。在仓库根目录执行：

```bash
cp .env.monitor.example .env.monitor
# Edit .env.monitor: set JWT secret, admin token, model endpoint, model name and API key.
docker compose --env-file .env.monitor -f compose.monitor.yml up -d --build
docker compose --env-file .env.monitor -f compose.monitor.yml ps
curl http://127.0.0.1:8080/healthz
```

通过 HTTPS 反向代理转发到 `127.0.0.1:8080`。工作台地址为 `/app/`，API 文档为 `/docs`。主站必须签发有效用户 JWT，工作台获得身份后才可提交任务。

部署配置：[compose.monitor.yml](compose.monitor.yml)；环境变量模板：[.env.monitor.example](.env.monitor.example)。此编排只启动 `monitor` 和 `browser` 两个服务，不依赖旧 Web 后端。

## 运行结构

```text
订阅网站 → 用户 JWT → 监测工作台 / 用户 API
                         ↓
                  任务队列与租户数据
                         ↓
               五平台浏览器采集服务
                         ↓
                  AI 判定与证据校验
                         ↓
                    增量报告
```

- `services/monitor-service/`：用户接口、任务队列、租户隔离、报告访问和网页工作台。
- `services/browser-service/`：服务器上的五平台浏览器与登录态管理。
- `tools/`：服务调用的采集编排、AI 判定与问题生成逻辑。
- `services/telemetry-service/app/`：报告渲染所需的共享模块；无需额外启动 telemetry 服务。

订阅网站对接、JWT 签发和配额接口见 [模块接入说明](services/monitor-service/README.md)。HS256 共享密钥是当前实现的接入协议，实际主站需按此协议对接或适配。

## 数据与登录态

Compose 使用持久卷保存任务数据库、报告与平台登录态。默认单实例、单工作队列，SQLite 保存任务；增加副本前需要共享数据库和跨进程任务协调。

平台登录态由运营人员在服务器配置。容器启动、健康检查通过只说明进程可用；五平台会话校验通过后才能真实采集。浏览器服务不公开端口，管理与授权应通过受控运维通道操作。

## 验证状态

- 已完成：模拟浏览器与模拟模型的端到端验证，覆盖身份识别、提交任务、AI 判定字段、逐字证据与报告生成。
- 待验证：Linux Docker 镜像实际构建、五平台真实登录及采集、主站身份联调。本次修改环境未安装 Docker，尚未执行镜像构建。
- 当前源码仍包含历史工具和旧平台目录；上述服务器编排只使用所列服务和共享模块。完整的生产验收尚未完成。

## 许可

仓库保留部分上游 [Vigilath](https://github.com/sr007-cxy/Vigilath) 代码及其 MIT 声明，见 [LICENSE](LICENSE)。
