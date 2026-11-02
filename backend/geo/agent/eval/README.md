# Agent 评测骨架

衡量 agent 能力提升,**分两层**(各回答不同问题):

| 层 | 文件 | 测什么 | 何时跑 |
|---|---|---|---|
| 组件级 | `test_routing.py` | route_line 判线 + 业务线工具隔离机制(无 LLM、确定性、毫秒级) | 每次部署 / CI 闸门 |
| 端到端 | `run_eval.py` | 真模型跑一遍:工具轨迹是否正确 + LLM 判官打"任务是否完成" | 换模型 / 改 prompt / 按版本 |

标注集统一在 `dataset.py`,每条 `Case` 覆盖一个真实失效模式:
**路由错 / 选错工具 / 幻觉(该查没查) / 越线催促**。新增问句挑覆盖新失效模式的,别堆同质样本。

## 跑组件级(CI 闸门,不花钱)
```bash
# 需要装了 pydantic-ai 的 venv(import 链会拉到它)
<agent-venv>/bin/python -m pytest backend/geo/agent/eval/test_routing.py -q
```
改 `route_line` 关键词或 `_line_tools` 分组导致退步,这里立刻红。

## 跑端到端(北极星,要 API key + 连库)
```bash
export DEEPSEEK_API_KEY=sk-...          # 或 OPENROUTER_API_KEY
export EVAL_ACCOUNT_ID=1                 # 用哪个账号的真实数据跑
<agent-venv>/bin/python -m geo.agent.eval.run_eval
# 只跑某些失效模式: --tags hallucination,write-guard
# 只跑某些 case:     --ids s_history,g_publish_view
# 省钱只看轨迹:      --no-judge
```
输出两个数:**轨迹通过 N/M**(组件级,确定性)和 **任务成功 N/M**(判官,端到端)。
换 flash↔pro、改 prompt 时跑一遍对比这两个数拍板要不要上。

## forbid_tools 的两种语义(易混)
- **跨线隔离**(机制):舆情线工具集里**不含任何 GEO 工具** → `test_routing.py` 确定性保证。
- **行为级**(端到端):工具在本线合法存在,但模型**不该调用**(如"今天发了哪些文章"是查看,
  不能去 `draft_articles`)→ 只能 `run_eval.py` 跑真模型才测得到。
