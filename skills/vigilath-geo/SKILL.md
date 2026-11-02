---
name: vigilath-geo
description: 查询与优化品牌在 AI 搜索引擎(ChatGPT / Perplexity / DeepSeek / 豆包 / 通义 / 文心 / 元宝)中的可见性与被引用率(GEO/AEO)。当用户问到「在 AI 里被搜到几个 / AI 搜索可见性 / GEO / AEO / 竞品在 AI 里怎么对比 / 怎么提升被 AI 引用 / 投放效果」这类问题时使用。
---

# Vigilath GEO 优化

把本宿主 agent 链接到 Vigilath 的 GEO 优化 agent——一只绑定某账号的"小龙虾",负责检测·审计·优化·监控品牌在 AI 搜索引擎中的可见性。

## 何时用

用户(或上游任务)涉及以下任一,就调用本 skill:

- 「我的品牌/产品在 AI 搜索里**被搜到几个**问题?」「AI 可见性怎么样?」
- 「帮我**诊断** GEO/AEO 现状」「为什么 AI 不引用我?」
- 「**竞品**在 AI 引擎里的表现对比」
- 「今天/累计**投放效果**、命中率」
- 「怎么**优化/产稿**提升被 AI 引用率」

不涉及 AI 搜索可见性的普通问题,不要调用。

## 怎么用

脚本在 `scripts/geo_client.py`,纯标准库、零依赖。

- **对话式**(让 GEO agent 自己跑工具、给结论 + 结构化卡片):
  ```bash
  python scripts/geo_client.py chat "今天投放效果怎么样?累计被搜到几个问题?"
  ```
  输出 = 一段自然语言回答 + 一段「结构化卡片」JSON(命中数字、竞品等)。**把卡片里的数字念给用户**,别只复述自然语言。

- **只取数**(不走大模型,更快、更省;只要数字时用):
  ```bash
  python scripts/geo_client.py data today      # 今日新增 + 累计命中
  python scripts/geo_client.py data coverage   # 累计 query / 种子词命中
  python scripts/geo_client.py data report      # 最近诊断报告状态
  ```

- **看权限**(当前 token 能做什么,决定要不要提"产稿/发布"):
  ```bash
  python scripts/geo_client.py capabilities
  ```

## 鉴权

脚本从环境变量读凭证,**绝不硬编码、绝不打印 token**:

- `VIGILATH_AGENT_TOKEN`(必填)—— 1 年期账号 token,由 Vigilath 领号发放。
- `VIGILATH_BASE`(选填)—— 默认 `https://geo.vigilath.com/api/agent/v1`。

## 边界(照实告诉用户)

- 引擎选择、查询调度、频率由 Vigilath 平台固定,**你和用户都不能指定**,只看结果。
- **真实对外发布**不在本 skill 能力内(受平台内部护栏控制);本 skill 只做查询 / 诊断 / 归因 / 优化建议。
- 一个 token = 一个账号,只能看该账号自己的数据。
- 出现 `401` 报错 = token 无效/过期,提示用户联系 Vigilath 重发,别重试刷接口。
