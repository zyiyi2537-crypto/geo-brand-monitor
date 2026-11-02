# AI 引用追踪 · v2 增量:LLM 诊断与优化建议

> **Status: historical phase plan.** Current maintained behavior and KPI
> contracts are documented in
> [docs/product/ai-telemetry.md](../../../docs/product/ai-telemetry.md).

> 状态:**Draft / 待评审**
> 创建日期:2026-05-13
> 上一版:[`mention-tracking-prd.md`](./mention-tracking-prd.md)(v1,**保持不变**,作为命中追踪基线)
> 本文档关系:**叠加在 v1 之上**;v1 是"看见命中",v2 是"理解命中 + 行动"

---

## 0. 为什么要做这一层

v1 解决的是「**看见**」—— 我的检索词在哪几个引擎、哪几个 query 下被提到了。

但客户最终会问的 3 个问题,v1 都答不了:

| 客户的真问题 | v1 给的 | 客户需要的 |
|---|---|---|
| "为什么文心一言一直没收到?" | ⌛ 待做 / done 灰✓ | **诊断**:引擎答复里推了谁?citations 是谁家域名?我们的内容是不是没进它的索引? |
| "下一步我该写什么内容?" | (无) | **建议**:这 5 个 query 里,Q3 命中率最低,因为答复总在推 X 律所的"反垄断专项报告" → 你也写一篇 |
| "我的投放预算该花在哪?" | (无) | **优先级**:Q1 已稳定命中,Q2/Q4 是临门一脚(同行答复里出现过我们的名字但没进推荐位)→ Q2/Q4 优先投放 |

**v1 是看板,v2 是顾问。** 这层做出来,客户不再是"看我们的报表",而是"听我们的建议下决策" —— 这是 GEO 服务从工具变咨询的核心节点,直接影响续费率和单价。

---

## 1. v2 三个核心能力

### 1.1 Cell 级诊断(Why)

每个 (query × engine) cell 都生成一段 LLM 分析,解释**这次答复为什么命中 / 不命中**。

**未命中 cell**:
- 答复推荐了哪些品牌 / 律所 / 产品(竞品识别)
- citations 引用了哪些域名,我们的官网 / PR 是否在里面
- 该引擎当前对此 query 的"答题套路"是什么(列表式 / 报告式 / 案例式)
- **3 个具体优化方向**(不是空话,是带主题 + 落地页 + 渠道的建议)

**已命中 cell**:
- 命中位置(主推荐位 / 顺带提及 / 末尾列表)
- 命中语气(supportive / 中性 / 负面)
- 命中稳定性(本周 5 次跑批,命中 2 次 — 还需要再投强化)

### 1.2 Topic 级周报(How)

每周一早上,系统自动给客户生成一份**战略级周报**:

- 本周首次命中 / 流失了哪些 cell(动态)
- 跨 cell 横向看:**3 个最值得追加投放的 query** + **3 个内容主题建议**
- 引擎间画像差异:文心爱推官方文件 vs 豆包爱推用户评测 → 内容策略差异化
- 竞品占位变化:本周 X 律所在 Q3 出现频次 +50%,要不要写一篇对标文

### 1.3 跨 Topic 行业洞察(Phase 2.5)

匿名横向聚合(opt-in):**你所在的行业,平均 TTFM 是 12 天,你是 5 天,跑赢 80%**。

> v2 本期只做 1.1 + 1.2,1.3 留到 v2.5。

---

## 2. 数据模型变更(叠加在 v1 之上)

### 2.1 Response 表加字段

| 字段 | 类型 | 用途 |
|---|---|---|
| **`competitors_json`** | json `[{name, mention_position, snippet}]` | LLM 从 answer 抽出的"被推荐的竞品 / 同行实体"列表;按出现位置(头部/中部/末尾)分级 |
| **`citation_domains_json`** | json `["site.com", ...]` | 从 citations 提出的顶级域名,做集合分析(谁家域名被引用最多) |
| **`answer_format`** | str enum | `listicle` / `single_recommendation` / `report` / `case_study` / `qa` —— 引擎的"答题套路"分类,辅助内容投放策略 |

> 这三个字段在 Response 落库**之后**异步算(LLM 调用 1 次,见 §4 触发策略),不阻塞跑批。

### 2.2 新表 `ai_telemetry_cell_insights`(cell 级诊断)

主键 `(topic_id, query, engine, window_end)` —— `window_end` 是分析窗口的结束日期(如 `2026-05-13`),意味着这条诊断针对"截至该日的最近 N 次跑批"。

| 字段 | 类型 | 说明 |
|---|---|---|
| `topic_id, query, engine` | (FK, text, text) | 三联主键前段 |
| `window_start, window_end` | date | 分析窗口(默认近 7 天) |
| `verdict` | enum | `hit_stable` / `hit_unstable` / `near_miss` / `no_signal` / `negative_mention`(诊断结论的一句话标签) |
| `summary` | text | 1-2 句话总结诊断 |
| `competitors_top3_json` | json | 该 cell 答复里出现最多的 3 个竞品名 + 出现次数 |
| `recommendations_json` | json `[{title, action, priority}]` | 3 条优化建议,带优先级(P0/P1/P2) |
| `evidence_response_ids_json` | json `[int]` | 这条诊断基于哪些 Response 算出来的(可追溯) |
| `llm_model, prompt_version` | str | 用什么模型、什么 prompt 版本(可回溯重算) |
| `generated_at` | datetime | 生成时间 |
| `feedback` | enum nullable | `helpful` / `not_helpful` / `wrong` —— 用户在 drawer 里点反馈(产品改进信号) |

**生命周期**:LLM 调用昂贵,加 cache —— 同一 cell 在同一 window 内**不重复生成**,除非:
- 新跑批了一次(`evidence_response_ids` 集合变了),或
- 用户在 drawer 里点 "重新分析"(force_regenerate=true)

### 2.3 新表 `ai_telemetry_topic_briefings`(topic 级周报)

| 字段 | 类型 | 说明 |
|---|---|---|
| `topic_id` | int FK | |
| `period_start, period_end` | date | 默认上周一 ~ 上周日 |
| `body_md` | text | Markdown 正文,客户邮件直接渲染 |
| `kpi_snapshot_json` | json | 当周 KPI 截照(命中率、TTFM、新命中数、流失数) |
| `top_actions_json` | json `[{title, why, how}]` | 3-5 条本周优先行动 |
| `delivered_email_at` | datetime nullable | 已邮件投递时间 |
| `llm_model, prompt_version, generated_at` | | 同上 |
| `feedback_score` | int nullable | 客户邮件里点 1-5 星反馈 |

**生成节奏**:每周一早 09:00 北京时间(scheduler 加一个 cron job)。

---

## 3. UI 变更

### 3.1 v1 drawer 升级(加诊断 & 建议区)

```
┌──────────────────────────────────────────────────┐
│  ✕ 文心一言 · Q1 跨境TMT投资律师                  │
├──────────────────────────────────────────────────┤
│  首次命中:2026-05-12 · 累计命中 2/3 跑批 (67%)  │
│  📎 原文:yiyan.baidu.com/chat/Nj... ↗            │
│                                                   │
│  ─ 答复片段 ────────────────────────────────     │
│  "...推荐关注 [金诚同达律所],在 TMT 行业..."     │
│                                                   │
├──────────────────────────────────────────────────┤
│  🔍 诊断 · 「命中不稳定 hit_unstable」 ⓘ           │
│                                                   │
│  • 3 次跑批命中 2 次,5/13 那次答复未提及         │
│  • 同 query 答复里高频出现的竞品:                 │
│      ▸ 君合律师事务所(3/3 次)                   │
│      ▸ 中伦律师事务所(2/3 次)                   │
│      ▸ 通商律师事务所(1/3 次)                   │
│  • 引擎答题套路:listicle(列出 3-5 家)          │
│  • 答复 citations 主要域名:gov.cn, lawinfochina  │
│    (我们的官网 jincheng.com **未出现**)         │
│                                                   │
│  ─ 优化建议 ──────────────────────────────       │
│  P0  在 jincheng.com 加一篇 "TMT 海外并购十大     │
│      案例" 长文 — 文心 listicle 答题套路对深度    │
│      报告类内容权重高                              │
│  P0  优化 PR:把 "金诚同达 TMT 团队" 投到          │
│      lawinfochina.com(已被高频引用的法律垂域)    │
│  P1  追加投放 「金诚同达 跨境投资」语义关键词     │
│                                                   │
│  [ 👍 有帮助 ] [ 👎 不准 ] [ ↻ 重新分析 ]         │
└──────────────────────────────────────────────────┘
```

**关键交互**:
- 诊断 / 建议块**按需触发**:用户首次打开 drawer 时若 cache 没命中 → 显示"🤔 正在分析..."骨架屏 3-5s
- "重新分析"按钮:刷新 cache,适用于客户调整内容后想立刻看新结论
- 反馈按钮:3 选 1,数据回流到我们改 prompt

### 3.2 新 Tab:「优化建议」

放在引用追踪 Tab 右边:

```
旧 (v1):  [概览] [引用追踪] [话题配置] [跑批结果]
新 (v2):  [概览] [引用追踪] [优化建议 ★ NEW] [话题配置] [跑批结果]
```

主视图 = 当前 Topic 的**最新周报** + **历史周报列表**:

```
┌────────────────────────────────────────────────────────────────┐
│  检索词:金诚同达律所   周报:[ 2026-W19 ▾ ]   [📧 重新发邮件]    │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ## 本周亮点                                                    │
│  ✨ 文心一言 Q1 完成首次命中(投放后第 3 天)                  │
│  ⚠️  豆包 Q2 出现一次负面提及,需关注                          │
│                                                                 │
│  ## 本周 KPI                                                    │
│  ┌──────┬──────┬──────┬──────┐                                 │
│  │ 命中率│ TTFM │新命中│ 流失 │                                 │
│  │  16% │ 3 天 │  +2  │  -1  │                                 │
│  └──────┴──────┴──────┴──────┘                                 │
│                                                                 │
│  ## 下周优先行动                                                │
│  🎯 P0  把 jincheng.com 的 TMT 案例库扩到 10+ 篇                │
│  🎯 P0  对豆包 Q2 负面提及做正面背景资料投放                    │
│  🎯 P1  Q4 反垄断方向新建内容专题(竞品空白)                  │
│                                                                 │
│  ## 引擎画像差异                                                │
│  - 文心爱推 .gov.cn / 行业白皮书 → 投权威背书内容               │
│  - 豆包爱推用户长评 / 案例 → 投故事化内容                       │
│  - 元宝爱推榜单 → 争取进 lawyer ranking 类列表                  │
└────────────────────────────────────────────────────────────────┘
```

---

## 4. LLM 触发策略(成本 / UX 平衡)

| 场景 | 触发时机 | 模型 | 缓存 | 成本估算(per Topic) |
|---|---|---|---|---|
| Response → 抽 competitors/citations/format | **跑批完成后异步**(批量) | Haiku 4.5(便宜快) | Response 行级,永不重算 | 25 calls/天 × 500 tok = 12.5K tok/天 |
| Cell 诊断 | **drawer 首次打开**(用户驱动) | Sonnet 4.6 | window=7d,新 Response 来才重算 | 平均 5 cells/Topic × 4 次/月 = 20 calls/月 |
| Topic 周报 | **每周一 09:00 北京**(scheduler) | Opus 4.7(质量优先) | 一周一份,不重算 | 4 calls/月 × 5K tok = 20K tok/月 |

**为什么不在跑批时就预算 cell 诊断**:大部分 cell 用户不会点开。按需触发把成本压在用户真在意的地方。代价是首次点击 3-5s 等待,可接受(对标 ChatGPT 网页加载)。

**为什么 Response 级抽取要主动做**:competitors / citations / format 是**周报的输入**,周报跑批时如果还要现抽,延迟难控。批量异步在跑批后 5 分钟内完成,周报来取时已就绪。

**月度成本天花板**(100 个 Topic 估算):
- Response 抽取:100 × 25 × 30 = 75K calls/月,Haiku ~$3-5
- Cell 诊断:100 × 20 = 2K calls/月,Sonnet ~$15-25
- Topic 周报:100 × 4 = 400 calls/月,Opus ~$10-15
- **合计 ~$30-50/月**,远低于客户单价(几千~几万 RMB/月)

---

## 5. 新增 KPI

| 指标 | 定义 | 目标 |
|---|---|---|
| **诊断打开率** | drawer 打开次数 / 已命中 cell 数 | ≥ 1(每个命中至少被翻看,与 v1 KPI 重叠) |
| **建议反馈率** | 点 👍 / 👎 数 / 诊断显示数 | ≥ 10%(说明用户认真在看) |
| **建议有用率** | 👍 / (👍 + 👎) | ≥ 70% |
| **周报打开率** | 邮件 open / 邮件发送 | ≥ 50%(对标 SaaS 高质量 weekly digest) |
| **周报转化率** | 周报建议被采纳率(7 天内客户内容更新对应主题) | ≥ 20%(关键续费信号) |

---

## 6. MVP 切片(更新 v1 §7)

### v1.0(基线 · 已确认 2 周)
v1 全部 — 命中矩阵 + 时间线 + drawer(无诊断)。

### **v1.1(本 v2 增量 · 3 周)**

✅ 必做:
- Response 加 `competitors_json` / `citation_domains_json` / `answer_format` + 异步抽取 worker
- 新表 `ai_telemetry_cell_insights` + LLM 诊断按需触发
- drawer 加诊断 & 建议块 + 反馈按钮
- prompt 版本管理(`prompt_version` 字段,prompt 改了要能并行 A/B)

❌ 不做:
- 周报(留 v1.2)
- 跨 Topic 行业基准(留 v2.5)

### **v1.2(周报 · 再 2 周)**

✅ 必做:
- 新表 `ai_telemetry_topic_briefings` + scheduler 周一 09:00 跑
- 「优化建议」Tab + 历史周报列表
- 邮件投递(对接现有 notify_emails 通路)

### v2.5(行业基准 · 后期)
- 跨 Topic 匿名聚合,行业级 TTFM / 命中率分布
- opt-in:用户授权才参与;授权用户能看自己的"行业百分位"
- 这是销售线索池 + 行业报告的底层数据

---

## 7. 风险 / 边界(更新 v1 §8)

| 风险 | 应对 |
|---|---|
| **LLM 幻觉 — 编造竞品名** | (a) 强制 LLM 引用原文片段证明 (b) competitors 字段附 `snippet` 供 UI 显示出处 (c) 抽取用低温度 + 结构化输出(JSON schema 约束) |
| **建议太空泛("多发布优质内容")** | prompt 里强制要求"主题 + 落地页 / 渠道 + 量化目标";建议必须含 P0/P1/P2 优先级才入库 |
| **客户对建议不买账** | 建议反馈 👎 触发**人工 CSM review**,CSM 可在后台覆盖该 cell 建议(human-in-the-loop) |
| **prompt 版本漂移导致回归差** | `prompt_version` 字段 + A/B 对照表;改 prompt 必须保留前一版以防回滚 |
| **成本失控** | (a) Sonnet/Opus 设月度 budget,撞顶降级到 Haiku (b) cell 诊断按需 + cache (c) 监控告警:LLM token 用量超 1.5× 预算即报警 |
| **负面提及被当成命中算 KPI** | competitors 抽取同时算 `mention_quality`(supportive / neutral / negative);weighted_visibility = hit × quality;**v1.1 内置但不暴露**,v1.2 周报里用 |
| **第三方引擎 API 变动 / 限速** | 现有 telemetry-service 的 retry / fallback 不变;LLM 诊断完全独立,引擎 fail 不影响诊断历史 |
| **答复语言混合**(中英) | LLM prompt 用"输出中文"显式约束;用户语言切英文时由前端 i18n 切换显示而非重算 |
| **隐私 / 客户数据外发 LLM** | (a) 仅发送 answer + 检索词,不发用户身份 (b) 用 Anthropic / OpenAI 企业级 API(数据不训练)(c) 客户合同里 disclose |

---

## 8. 决策点(本 v2 增量)

请你确认以下 5 点(v1 三个决策点照旧):

1. **诊断按需触发 vs 跑批预算** — 我倾向**按需 + cache**(成本低、UX 可接受)。✅ / ✗
2. **周报每周自动 + 邮件投递** — 我倾向**每周一 09:00 自动**(对标 weekly digest 行业惯例)。✅ / ✗
3. **LLM 模型选型** — Haiku(抽取)+ Sonnet(诊断)+ Opus(周报)三级火箭。✅ / ✗ / 其它
4. **建议反馈 → 人工介入** — CSM 在后台覆盖单 cell 建议(human-in-the-loop)。是否本期就做后台?(我倾向 v1.2 才做,v1.1 先收集反馈数据)
5. **行业基准(v2.5)** — opt-in 授权 + 匿名聚合 + 销售线索池。这条**战略级**:做 = 把工具升级成网络效应产品,不做 = 保持工具定位。先开个口子还是不开?

---

## 9. 与 sentinel(舆情) 模块的协同

舆情模块已经有的资产可以**直接借**,避免重复造轮:

| 舆情已有的 | v2 怎么用 |
|---|---|
| `stance` 分类(supportive / neutral / skeptical / hostile) | Response.competitors_json 里的 `mention_quality` 直接复用同模型 / 同 prompt |
| `risk_signals` 抽取 | "负面提及"告警可复用 risk_level 阈值逻辑 |
| 简报(brief)生成模板 | Topic 周报的 Markdown 结构借鉴 sentinel `brief` 模块 |
| LLM 调用网关(`services/sentinel-service/llm_client.py`) | telemetry-service 直接 import 或复制(避免重复管理 API key / retry / rate limit) |

**架构建议**:`services/telemetry-service/insights/` 新建 LLM 诊断子模块,顶上 import sentinel 的 `llm_client`,prompt 各自独立(场景不一样,共享 client 不共享 prompt)。

---

## 10. 附录 A:Cell 诊断 Prompt 模板(v1)

```
你是 GEO(生成式引擎优化)分析师。客户希望优化品牌「{target}」在 AI 搜索引擎里的露出。

【上下文】
- 引擎:{engine}
- Query:{query}
- 检索词:{target}(别名:{aliases})
- 近 7 天该 cell 的 N 次答复 + citations(JSON):
{response_window}

【分析任务】
1. verdict 二选一:hit_stable / hit_unstable / near_miss / no_signal / negative_mention
2. competitors_top3:从答复中抽出 3 个最常出现的同类品牌 / 实体,带原文片段证据
3. answer_format:listicle / single_recommendation / report / case_study / qa
4. 3 条优化建议,每条带优先级(P0/P1/P2) + title(< 30 字) + action(具体动作 + 渠道) + why(基于哪条证据)

【输出格式 · 严格 JSON】
{
  "verdict": "...",
  "summary": "1-2 句话总结",
  "competitors_top3": [{"name": "...", "count": N, "snippet": "..."}],
  "answer_format": "...",
  "recommendations": [
    {"priority": "P0", "title": "...", "action": "...", "why": "..."},
    ...
  ]
}

【硬约束】
- 不要编造未出现在答复 / citations 里的事实
- 建议必须可执行,不接受 "提升内容质量" 这种空话
- 中文输出
```

参数:`prompt_version="cell_v1"`,温度 0.3。

---

## 11. 附录 B:Topic 周报 Prompt 模板(v1)

```
你是 GEO 战略顾问。为客户撰写本周(2026-W19)的 AI 引擎曝光周报。

【上下文】
- 检索词:{target}
- 本周 KPI:{kpi_snapshot}
- 本周新命中 cells:{new_hits}
- 本周流失 cells:{lost_hits}
- 各 cell 最新诊断(JSON):{cell_insights}
- 上周周报的优先行动:{prev_actions}(用于判断哪些已执行 / 未执行)

【输出格式 · Markdown】
## 本周亮点
(3-5 bullet,数字优先)

## 本周 KPI
(KPI 表格,4 列:命中率 / TTFM / 新命中 / 流失)

## 下周优先行动
(3-5 条,每条 P0/P1/P2 + title + why + how)

## 引擎画像差异
(对比 3-5 个引擎的答题套路差异 + 内容策略建议)

## 与上周对照
(对照 prev_actions,标注 ✓ 已落地 / ⌛ 进行中 / 未启动)

【硬约束】
- 全文 < 600 字(客户邮件场景)
- 优先行动**必须**含可量化目标(如"加 3 篇 TMT 案例文,30 天内")
- 不重复 cell drawer 已有的细节,聚焦"跨 cell 看到的模式"
- 中文输出
```

参数:`prompt_version="briefing_v1"`,温度 0.5。

---

## 12. 下一步

1. **本文档评审**(0.5 天)— 与你确认 §8 五个决策点
2. 评审通过 → 与 v1 PRD 合并出**统一 v2 PRD**
3. 工程实施 plan:
   - **Sprint 1 (v1.0,2 周)**:命中矩阵 + drawer(v1 全部)
   - **Sprint 2 (v1.1,3 周)**:LLM 诊断 + Response 异步抽取 + drawer 诊断块
   - **Sprint 3 (v1.2,2 周)**:周报 + 「优化建议」Tab + 邮件投递
4. 共 **7 周**到 v1.2 全功能上线
