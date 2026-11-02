# AI 引用追踪(Mention Tracking)产品文档 · v1

> **Status: historical phase plan.** Current maintained behavior and KPI
> contracts are documented in
> [docs/product/ai-telemetry.md](../../../docs/product/ai-telemetry.md).

> 状态:**Draft / 待评审**
> 创建日期:2026-05-13
> 模块:`ai-telemetry`(GEO 第二支产品线)
> 关联代码:`services/telemetry-service/` · `backend/geo/api/ai_telemetry.py` · `frontend/src/pages/Dashboard/AiTelemetry.tsx`
> 前置:已存在「话题配置 / 概览 / 跑批结果」三 Tab(commits `b133a3c` → `f28ab2b`)

---

## 0. TL;DR

> **一句话:让客户一眼看到「我配的检索词在哪几个 AI 引擎、哪几个 query 下被提到了,第一次命中是哪天」。**

这是 GEO 投放的**结果证明**——而不是 SEO 时代的"我的关键词排第几"。在生成式引擎里,客户的核心问题是:**"我投放了三天,文心一言收到了吗?"** 现有 Overview Tab 给的是聚合数字(visibility 60% / citations 142),但**回答不了那个具体问题**。

本期(v1)就解一件事:

**做出一张 (query × engine) 命中矩阵 + 时间线**,把"已命中 / 进行中 / 待做"和"首次命中日期 + 原文链接"清楚展示出来。

---

## 1. 背景与问题

### 1.1 客户在问的问题

客户(品牌方 / 律所 / B2B 服务商)买我们 GEO 优化的核心诉求:

> *"我投放了三天内容,文心一言 / 豆包 / DeepSeek 是不是开始把我的品牌当推荐答案了?"*

他们要**结果证据**,不要平均数。

### 1.2 现有产品答不上来

| 现有 Tab | 给什么 | 答不答这个问题 |
|---|---|---|
| **概览** | KPI(visibility %、citations 总数)、趋势、引擎 × 平台 heatmap | ✗ 看不到**哪个 query 在哪个引擎**命中 |
| **跑批结果** | 单次 run 的 answer 全文 + citation 列表 | ✗ 单 run 视角;跨日**首次命中**信息没有 |
| **话题配置** | name / queries[] / engines[] CRUD | ✗ 没有"检索词"字段 |

**核心 gap**:现有数据模型把"被检测的实体词(brand)"借用户的舆情账户字段,不是 Topic 自己的属性;同时**命中判定结果**(hit / first_hit_at / hit_excerpt / source_url)只在聚合 KPI 里算了一次,**没落盘 → 没法做跨 run 时间序列**。

### 1.3 一个真实工作流(目标态)

> 检索词:**"北京律师"**(客户:某律所)
>
> Queries(客户设置 5 条提问角度):
> 1. 适合企业跨境 / TMT 投资、海外并购的北京律师
> 2. 适合私募股权的北京律师
> 3. 适合资本市场(港股 / 美股 / A 股)的北京律师
> 4. 适合反垄断申报与合规的北京律师
> 5. 适合外商直接投资(FDI)的北京律师
>
> Engines:文心一言 / 豆包 / 元宝 / Kimi / DeepSeek
>
> **每天 02:05 跑批,5 query × 5 engine = 25 个调用**。
>
> 客户上线投放第 3 天,文心一言在 query #1 的答复里第一次提到这家律所 →
> **该客户当天打开页面,我们必须能立刻把这条"喜讯"喂给他**——而不是埋在某个聚合 trend 的小幅波动里。

---

## 2. 用户故事

| ID | 角色 | 故事 | 验收 |
|---|---|---|---|
| US-1 | 品牌方运营 | 我要配置一个**检索词** + 多个 query + 多个引擎,系统每日帮我去问 | 提交后入库,出现在跑批列表 |
| US-2 | 品牌方运营 | 我打开看板,**一屏**就能看到"我的检索词在哪些 query × 哪些引擎已命中" | 看到 5×5 矩阵 + 状态点 |
| US-3 | 品牌方运营 | 一个 cell 命中后,我能**点进去看原文**(AI 答复的截图 / 链接 / 答复文本片段) | 点击 cell 弹出抽屉,显示 hit_excerpt + source_url |
| US-4 | 销售 / CSM | 我要拿一份「客户上线后第 N 天首次命中」的数据汇报给客户 | 矩阵能导出 / 截图 |
| US-5 | 品牌方运营 | 我新加一个 query,从昨天起的所有历史结果**不要回填**(避免误以为命中,实际是历史无数据) | 新 query 默认 "待做" 状态,只看上线后的数据 |

---

## 3. 核心概念 & 数据模型

### 3.1 概念三件套

```
       Topic (检索任务)                          每日 02:05
   ┌──────────────────────────────┐             跑批
   │ target       检索词(被检测的实体)  │  ───────────► Run
   │ queries[]    提问角度(N 条)        │             │
   │ engines[]    引擎(M 个)           │             ▼
   └──────────────────────────────┘     Response (N×M 条/run)
                                                     │
                                            mention 判定
                                                     │
                                                     ▼
                                            QueryHit  (跨 run 聚合)
                                            (query × engine 维度)
```

### 3.2 数据模型变更(对照当前)

#### Topic — 加一个字段:`target`

| 字段 | 类型 | 现状 | 变更 |
|---|---|---|---|
| `name` | text | ✓ 显示名 | 保留 |
| **`target`** | text | ✗ 没有 | **新增**:被检测的检索词 / 品牌词 / 实体(如 "金诚同达律所") |
| **`target_aliases`** | json | ✗ 没有 | **新增**:别名列表(如 ["金诚同达", "King & Wood", "KWM"]),命中判定时任一即算 |
| `queries_json` | json | ✓ | 保留;每条 query 加 `created_at` 用于 US-5 "不回填" |
| `engines_json` | json | ✓ | 保留 |
| `enabled` | bool | ✓ | 保留 |

**为什么不复用舆情账户的 target**:
- 舆情和 AI 遥测**业务路径不同**:有客户只买 GEO 不买舆情;
- 一个 Topic 一个检索词是最干净的 1:1;
- 复用造成的耦合在 `backend/geo/api/ai_telemetry.py:237-248` 已经显形(取舆情第一个 active account 当数据源,语义不明确)。
- **迁移**:已有 Topic 在数据迁移时,`target` 默认取该用户舆情 account 的 target(保持现有行为),后续用户可在 UI 改。

#### Response — 加 3 个字段记录命中判定

| 字段 | 类型 | 现状 | 变更 |
|---|---|---|---|
| `engine`, `query`, `answer`, `citations_json` | text/json | ✓ | 保留 |
| **`hit`** | bool | ✗ | **新增**:本次答复是否提到 target / target_aliases |
| **`hit_excerpt`** | text(~200 字) | ✗ | **新增**:命中位置的上下文片段(答复中检索词前后各 100 字),给 UI 直接展示用 |
| **`source_url`** | text | ✗ | **新增**:answer 对应的 AI 引擎 chat 公开 URL(已有 `video_url`,但语义不够通用) |

> `source_url` 用例:
> - 文心一言:`https://yiyan.baidu.com/chat/{chat_id}` ← 客户给的例子
> - 豆包:`https://www.doubao.com/thread/{thread_id}` ← 客户给的例子
> - 没有公开 URL 的引擎(如 OpenAI API 直调):`null`,UI 展示 answer 全文

#### QueryHit(新表)— (query × engine) 维度的当前状态 + 首次命中

主键 `(topic_id, query, engine)`。每次 Response 落库后维护,**O(N) 更新即可**。

| 字段 | 类型 | 说明 |
|---|---|---|
| `topic_id` | int | FK |
| `query` | text | 提问 |
| `engine` | str | 引擎 code |
| `status` | enum | `done` / `running` / `pending`(状态机见 §4) |
| `first_hit_at` | datetime nullable | **首次命中时间**(US-4 核心字段) |
| `first_hit_response_id` | int nullable | FK 到 Response,定位证据 |
| `last_checked_at` | datetime | 最近一次有响应(成功 or 失败)时间 |
| `total_runs` | int | 该 cell 累计跑过几次 |
| `total_hits` | int | 累计命中几次(命中率 = total_hits/total_runs) |

---

## 4. 状态机(每个 query × engine cell)

```
   query 配置那天                  最近一次 run 成功            历史曾命中
       │                              │                            │
       ▼                              ▼                            ▼

  ┌─────────┐   有 run 在跑     ┌───────────┐  run 跑完  ┌──────────────┐
  │ pending │ ───────────────► │  running  │ ─────────► │     done     │
  │  待做   │                  │  进行中    │            │   已有结果    │
  └─────────┘                  └───────────┘            └──────────────┘
                                                                │
                                                       命中过 ≥ 1 次
                                                                │
                                                                ▼
                                                       ┌──────────────────┐
                                                       │ done · hit       │
                                                       │ 已命中 + 时间 + 链接│
                                                       └──────────────────┘
```

**规则**:
- `pending`:该 (query, engine) 自 Topic 配置以来,**还没有过任何完成的 Response**(包括 error)
- `running`:有 RunORM `status='running'` 且包含此 (query, engine)
- `done` 但 `total_hits = 0`:跑过,**没命中过**(UI 用浅灰 ✓)
- `done` 且 `total_hits ≥ 1`:**已命中**,UI 用绿色 ✓ + `first_hit_at` 日期 + 跳转抽屉

**重要**:**新加 query 默认 pending**,**不回填**历史 — 否则当晚 02:05 跑批前,新 query 会显示"没命中",造成误读。

---

## 5. 信息架构 / 新页面

### 5.1 新 Tab:**「引用追踪」**(insertion 顺序)

```
旧:  [概览] [话题配置] [跑批结果]
新:  [概览] [引用追踪 ★ NEW] [话题配置] [跑批结果]
```

放在概览右边,因为它**就是概览的 zoom-in 视角**;话题配置 / 跑批结果保持后置(配置 + debug 用)。

### 5.2 引用追踪 Tab 主视图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  检索词:[ 金诚同达律所 ▾ ]   时间窗口:[ 近 30 天 ▾ ]   [⏵ 立即跑一次]   │
│  上线日期:2026-05-10  · 累计跑批 3 次 · 已命中 1/25 cells (4%)                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌── 首次命中时间线 ──────────────────────────────────────────────────┐    │
│  │  文心一言    ●━━━━━━━━━━━━ 5/12 首次命中(投放后第 3 天) ⓘ        │    │
│  │  豆包        ●━━━━━━━━━━━━ 5/12 首次命中                          │    │
│  │  元宝        ○ 暂未命中                                            │    │
│  │  Kimi        ○ 暂未命中                                            │    │
│  │  DeepSeek    ○ 暂未命中                                            │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌── 命中矩阵 ───────────────────────────────────────────────────────────┐ │
│  │                       │ 文心 │ 豆包 │ 元宝 │ Kimi │ DeepSeek │       │ │
│  │  Q1 跨境TMT投资律师   │ ✓ 5/12│ ✓ 5/12│ ⌛ │ ⌛  │   ⌛    │ ◐ 2/5 │ │
│  │  Q2 私募股权律师      │ ⏳    │ ⏳    │ ⏳ │ ⏳  │   ⏳    │ 0/5  │ │
│  │  Q3 资本市场律师      │ ⌛    │ ⌛    │ ⌛ │ ⌛  │   ⌛    │ 0/5  │ │
│  │  Q4 反垄断合规律师     │ ⌛    │ ⌛    │ ⌛ │ ⌛  │   ⌛    │ 0/5  │ │
│  │  Q5 FDI 律师          │ ⌛    │ ⌛    │ ⌛ │ ⌛  │   ⌛    │ 0/5  │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│   图例:✓ = 已命中(点击看原文) · ⏳ = 进行中 · ⌛ = 待做 · 灰✓ = 跑过未命中  │
└─────────────────────────────────────────────────────────────────────────────┘
```

**点击 ✓ cell** → 右侧 drawer 展开,展示:

```
┌──────────────────────────────────────┐
│  ✕ 文心一言 · Q1 跨境TMT投资律师       │
├──────────────────────────────────────┤
│  首次命中:2026-05-12 02:14            │
│  累计命中:2/3 次跑批(67%)           │
│                                       │
│  ─ 答复片段 ──────────────────────    │
│  "...在跨境投资和海外并购领域,推荐    │
│  关注 [金诚同达律所],该所在 TMT       │
│  行业积累..."                          │
│                                       │
│  ─ 证据链接 ──────────────────────    │
│  📎 原文:yiyan.baidu.com/chat/Nj... ↗ │
│  📎 历次答复:[5/13] [5/12 ✓] [5/11]   │
└──────────────────────────────────────┘
```

### 5.3 配置页变更

`TopicModal` 加一个字段:

```
   检索词 *  [ 金诚同达律所                                 ]
   别名      [ KWM, King & Wood, 金诚                       ]
              (任一别名出现都算命中,逗号分隔,最多 10 个)
```

放在 `name` 字段下,visually 强调它是核心(加红 *)。

---

## 6. 核心 KPI(产品自身度量)

| 指标 | 定义 | 目标 |
|---|---|---|
| **TTFM**(Time to First Mention) | 客户配 Topic 起,到 first_hit_at 的天数中位数 | < 7 天(否则 GEO 投放的"快"卖点站不住) |
| **覆盖率** | 已命中 cells / 总 cells | 用户上线 30 天后期望 ≥ 30% |
| **页面点击率** | 进入「引用追踪」Tab 的 DAU / 该模块 DAU | > 60%(否则说明做的不是用户最常看的) |
| **drawer 展开率** | 点开 cell 看证据的次数 / 已命中 cells 数 | ≥ 1(每个命中至少被翻看一次) |

---

## 7. MVP 范围切片

### v1.0(本期,2 周)

✅ **必做**:
- Topic 加 `target` / `target_aliases` 字段 + 数据迁移(从舆情账户回填)
- Response 加 `hit` / `hit_excerpt` / `source_url`(runner 写入)
- 新表 `ai_telemetry_query_hits`,跑批完成后维护
- 新 Tab「引用追踪」:**矩阵 + 首次命中时间线 + drawer**
- 配置页加检索词输入框
- i18n(zh + en)

❌ **本期不做**:
- 多检索词 1 Topic(本期 Topic.target 是单值)
- 自定义命中规则(正则 / 模糊匹配 / 否定词)
- 邮件 / 微信告警("首次命中"推送)
- 矩阵导出 PDF / 截图

### v1.1(Phase 2)

- **首次命中告警**:命中那天自动发邮件 / Slack,这是销售要的"喜讯素材"
- **竞品对比**矩阵:同样的 query 看「我的检索词」vs「竞品检索词」的命中差异
- **命中质量分级**:推荐(supportive) / 中性提及 / 负面提及(复用舆情 stance 模型)
- 矩阵导出 PDF 给客户做汇报

### v2(更远)

- 多检索词 / 集合检索词(品牌 + 子品牌 + 产品线树状)
- 命中率回归分析:哪些 query 是"高产命中 query",反向指导客户怎么写内容
- 内容投放-引用 timeline 关联(对接 GEO 内容投放产品线)

---

## 8. 边界 / 风险

| 风险 | 说明 | 应对 |
|---|---|---|
| 命中误判 | 检索词是常见词("北京")会被任意答复命中 | (a) `target_aliases` 用更长字符串("北京律师事务所 XX")(b) Phase 2 加 stance 判定 |
| 引擎答复无 URL | OpenAI / Anthropic API 直调没有公开 chat URL | `source_url=null` 时 UI 展示 answer 全文 + 跑批 run_id,可在跑批结果 Tab 反查 |
| 新加 query 误显示"未命中" | US-5 已述 | `queries_json` 升级为 `[{text, created_at}]`;`QueryHit` 创建时 `status=pending`,**只看 created_at 之后的 Response** |
| 矩阵 cell 过多 | 极端用户:20 query × 10 engine = 200 cells | UI 把矩阵改成纵向滚动,engine 列固定 |
| 检索词大小写 / 简繁 | 答复可能写 "King & Wood" 而别名只配了 "KWM" | 命中判定**统一 lowercase + NFC 归一化**;v1.1 再做简繁互转 |
| 跑批失败 cell | 某次 engine 调用失败 → status 应该是什么? | `running` 期间是 running,完成时若**整 cell 历史 0 成功** → `pending` 保持;若**有过成功且这次 fail** → `done`,total_runs+1 但 hit 看上次记录 |

---

## 9. 与现有 Overview Tab 的关系

| 维度 | Overview(现有) | 引用追踪(新) |
|---|---|---|
| 视角 | 跨 Topic / 跨引擎**聚合** | 单 Topic / (query×engine) **二维矩阵** |
| 问题 | "整体表现怎么样?" | "我具体哪个 query 在哪个引擎被提到了?" |
| 数据源 | Response + 实时聚合 | QueryHit 表 + Response drawer |

**两者互补,Overview 不被替代。** Overview 的 visibility KPI 公式不变,但**底层从"每次聚合算"改成"读 QueryHit 表 sum"**,性能也更好。

---

## 10. 下一步

1. **本文档评审**(0.5 天)— 与你 sync 确认:
   - Topic 加 `target` 字段(而非复用舆情) — **OK 吗?**
   - 「引用追踪」放在概览右侧的 Tab — **位置 OK 吗?**
   - 首次命中时间线 + 矩阵 + drawer 三件套作为 MVP 主视图 — **够吗?**
2. 评审通过后出**工程实施 plan**(数据迁移 / runner 改动 / 前端组件拆分 / 测试切片)
3. **2 周交付 v1.0**;第 3 周灰度,第 4 周正式上线

---

## 附录 A:命中判定算法(简化版)

```python
def detect_hit(answer: str, target: str, aliases: list[str]) -> tuple[bool, str | None]:
    """返回 (hit, hit_excerpt)。
    
    excerpt = 命中位置 ±100 字符上下文,前后 ... 省略。
    多个别名命中只取第一个(避免重复存储)。
    """
    if not answer:
        return False, None
    needles = [target] + (aliases or [])
    needles = [n.strip().lower() for n in needles if n and n.strip()]
    hay = answer.lower()
    for n in needles:
        i = hay.find(n)
        if i >= 0:
            start = max(0, i - 100)
            end = min(len(answer), i + len(n) + 100)
            prefix = "…" if start > 0 else ""
            suffix = "…" if end < len(answer) else ""
            return True, f"{prefix}{answer[start:end]}{suffix}"
    return False, None
```

复杂度 O(answer_len × len(needles)),实际 answer < 4KB × needles ≤ 10,可忽略。

---

## 附录 B:数据迁移脚本概要

```
1. ALTER ai_telemetry_topics
     ADD target            TEXT NOT NULL DEFAULT ''
     ADD target_aliases_json TEXT NOT NULL DEFAULT '[]';
2. ALTER ai_telemetry_responses
     ADD hit               BOOLEAN DEFAULT 0
     ADD hit_excerpt       TEXT
     ADD source_url        TEXT;
3. CREATE TABLE ai_telemetry_query_hits (
     topic_id, query, engine PK,
     status, first_hit_at, first_hit_response_id,
     last_checked_at, total_runs, total_hits
   );
4. 回填(一次性脚本):
   - 对每个 Topic,从该 user 第一个 active 舆情 account 取 target/aliases
   - 对每条历史 Response,重算 hit + excerpt(用算法 A)
   - 用历史 Response 聚合出 QueryHit 行
```

> 迁移完成后,**当前 Overview Tab 的 visibility 数字应保持不变**(同算法、同输入),作为回归测试。
