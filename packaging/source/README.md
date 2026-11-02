# GEO 监测中心源码包

这是 GEO 监测中心桌面版 1.0.11 的干净源码包，面向 Windows 10/11 64 位开发和测试。

源码包包含：桌面 GUI、五个平台浏览器适配器、引用来源采集、AI 引用判定、品牌评价分析、目标文章和来源网站排名、历史趋势分析、报告渲染、安装器脚本、单元测试和图标资源。源码包不包含 Python 虚拟环境、浏览器缓存、账号登录态、模型密钥、个人任务、报告、构建产物或个人配置。

## 源码运行

建议使用 Python 3.12：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e services\browser-service
.venv\Scripts\python.exe -m playwright install chromium
.venv\Scripts\python.exe GEO-Monitor.pyw
```

重现安装版使用的依赖版本时，在安装浏览器服务之前先运行：

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
```

运行离线单元测试（测试模块分别启动，避免两个服务的同名 `app` 包互相影响）：

```powershell
Get-ChildItem tests\test_*.py | ForEach-Object { .venv\Scripts\python.exe -m unittest discover -s tests -p $_.Name }
```

首次运行时，在界面中填写自己的品牌、已发布文章公开网址、问题和模型配置，并在五个平台分别登录。源码运行的数据默认写入本地 `reports` 和 `services/browser-service/data` 目录；这些目录不会随源码包提供。

## 重新构建 Windows 安装包

需要 Windows、Inno Setup 6、Python 3.12 和已安装的浏览器依赖：

```powershell
.venv\Scripts\python.exe packaging\windows\build_installer.py --iscc "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
```

构建脚本使用显式文件清单，并在打包前检查个人数据和疑似 API Key。

## 目录说明

- `GEO-Monitor.pyw`、`geo_monitor_gui.pyw`：桌面入口和界面
- `tools/`：任务规划、模型调用、引用判定、报告记录和本地状态
- `services/browser-service/`：五个平台浏览器服务和登录态管理
- `services/telemetry-service/app/qualified_report.py`：可读报告渲染
- `packaging/windows/`：Windows 安装器构建文件
- `tests/`：不依赖真实账号的单元测试

本代码基于开源项目 Vigilath（https://github.com/sr007-cxy/Vigilath）修改，保留原项目 MIT 许可证。此包只交付当前桌面监测程序所需的源码，不包含原项目独立的 Web 管理后台。

完整操作流程见根目录的 `QUICKSTART.md`。
