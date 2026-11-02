// 博客文章数据源 —— 双语(zh/en)。
// 文章正文为 Markdown,详情页用 react-markdown 渲染。
// 新增文章只需往 blogPosts 里追加一条;slug 用作 /blog/:slug 路由与唯一键。

export type BlogLocaleContent = {
  title: string;
  excerpt: string;
  content: string;
};

export type BlogPost = {
  slug: string;
  /** ISO 日期,如 2026-05-20 */
  date: string;
  /** 封面图(可选),本地图片:/image/blog/<slug>.jpg,由 scripts/gen_blog_covers.py 生成 */
  cover?: string;
  /** 阅读时长(分钟) */
  readingMinutes: number;
  zh: BlogLocaleContent;
  en: BlogLocaleContent;
};

export const blogPosts: BlogPost[] = [
  {
    slug: 'what-is-geo',
    date: '2026-05-28',
    readingMinutes: 6,
    cover: '/image/blog/what-is-geo.jpg',
    zh: {
      title: '什么是 GEO?生成式引擎优化的底层逻辑',
      excerpt:
        '当用户不再翻十条蓝色链接、而是直接读 AI 给出的一段答案时,品牌该如何被「看见」?这篇文章拆解 GEO 的定义、与 SEO 的区别,以及它为什么正在成为出海与国内品牌的必修课。',
      content: `## 从「十条蓝链」到「一段答案」

过去二十年,搜索的核心是排名:谁排在第一页,谁就拿到流量。但当用户向 ChatGPT、Perplexity、Google AI Overviews 或 DeepSeek 提问时,他们看到的不再是一列链接,而是 AI 综合多个来源后生成的**一段答案**。

在这段答案里,你的品牌要么被引用、被推荐,要么干脆不存在。**GEO(生成式引擎优化)** 解决的就是后一个问题:如何让 AI 在回答用户问题时,主动提到你、引用你、推荐你。

## GEO 与传统 SEO 的区别

| 维度 | 传统 SEO | GEO |
| --- | --- | --- |
| 目标 | 网页在结果页排名靠前 | 品牌在 AI 答案中被引用推荐 |
| 载体 | 蓝色链接 | 生成式答案中的句子 |
| 评价 | 点击率、排名位次 | 被引频次、推荐语气、信息准确度 |

两者不是替代关系。SEO 让你的内容能被抓取、被索引;GEO 决定这些内容能否真正进入 AI 的「最终答案」。

## 为什么现在必须重视

- **流量入口在迁移**:越来越多的搜索发生在对话框里,而不是结果页。
- **答案具有唯一性**:一个问题往往只有一段答案,被引用与否是「赢家通吃」。
- **错误信息会固化**:如果 AI 对你的品牌描述有误,这种错误会被反复复述,纠正成本极高。

## GEO 该怎么做

落地路径通常包括四步:

1. **检测**:看清各大 AI 引擎当前如何描述、是否引用你的品牌。
2. **审计**:定位内容、权威信号、结构化数据上的短板。
3. **优化**:针对性补内容、建权威、修结构。
4. **监控**:持续追踪可见性变化,及时应对错误信息。

这正是 Vigilath 作为独立第三方 AI 可见性检测平台所覆盖的全链路。下一篇我们会展开讲「AI 凭什么引用一个来源」。`,
    },
    en: {
      title: 'What Is GEO? The Logic Behind Generative Engine Optimization',
      excerpt:
        'When users read one AI-generated answer instead of scanning ten blue links, how does a brand stay visible? This post breaks down what GEO is, how it differs from SEO, and why it matters now.',
      content: `## From "Ten Blue Links" to "One Answer"

For two decades, search was about ranking: whoever sat on page one captured the traffic. But when users ask ChatGPT, Perplexity, Google AI Overviews, or DeepSeek a question, they no longer see a list of links — they see **one synthesized answer** drawn from multiple sources.

In that answer, your brand is either cited and recommended, or simply absent. **GEO (Generative Engine Optimization)** solves the second problem: how to get AI to mention, cite, and recommend you when it answers a user's question.

## GEO vs. Traditional SEO

| Dimension | Traditional SEO | GEO |
| --- | --- | --- |
| Goal | Rank high on the results page | Get cited in the AI's answer |
| Surface | Blue links | Sentences inside a generated answer |
| Metrics | CTR, rank position | Citation frequency, framing, factual accuracy |

They are not mutually exclusive. SEO makes your content crawlable and indexable; GEO decides whether that content actually makes it into the AI's final answer.

## Why It Matters Now

- **The entry point is moving** — more searches happen inside a chat box than on a results page.
- **Answers are singular** — one question usually yields one answer, so being cited is winner-take-all.
- **Misinformation hardens** — if an AI describes your brand wrong, the error gets repeated and is costly to correct.

## How to Do GEO

The path usually involves four steps:

1. **Detect** — see how each AI engine currently describes and cites your brand.
2. **Audit** — pinpoint gaps in content, authority signals, and structured data.
3. **Optimize** — fill content, build authority, fix structure.
4. **Monitor** — track visibility over time and respond to misinformation fast.

That full chain is exactly what Vigilath, an independent third-party AI visibility platform, covers. Next up: why an AI chooses to cite one source over another.`,
    },
  },
  {
    slug: 'how-ai-picks-sources',
    date: '2026-05-20',
    readingMinutes: 7,
    cover: '/image/blog/how-ai-picks-sources.jpg',
    zh: {
      title: 'AI 凭什么引用一个来源?五个可优化的信号',
      excerpt:
        '生成式引擎并不是随机挑来源。从权威度、内容结构到信息新鲜度,这五类信号决定了你的内容能否进入 AI 的「最终答案」。',
      content: `## 引用不是随机的

很多人以为 AI 引用来源是黑箱,其实它高度依赖一组可观测、可优化的信号。理解这些信号,就能反推出该补什么内容。

## 五个关键信号

### 1. 权威度(Authority)
AI 倾向引用被广泛认可的来源 —— 行业媒体报道、维基百科 / 百度百科词条、高质量外链、权威平台收录。**权威是慢变量,但回报最持久。**

### 2. 内容结构(Structure)
清晰的标题层级、问答式段落、可直接摘取的定义句,会让内容更容易被「切片」进答案。一段能独立成立、不依赖上下文的话,被引用概率更高。

### 3. 信息新鲜度(Freshness)
对时效性话题,AI 偏好近期内容。一个标注了更新日期、持续维护的页面,胜过一篇三年前的「权威长文」。

### 4. 事实一致性(Consistency)
当多个来源对同一事实表述一致时,AI 更有信心采用。品牌应确保官网、社媒、第三方资料里的核心事实(成立时间、定位、产品名)**一字不差**。

### 5. 结构化数据(Structured Data)
Schema 标记、清晰的实体信息,帮助引擎准确理解「你是谁、做什么」,降低被混淆或张冠李戴的风险。

## 如何落地

- 先**检测**:看 AI 当前引用了谁、漏了你哪一块。
- 再**补齐**:针对最薄弱的信号优先投入 —— 通常是权威与结构。
- 持续**监控**:信号会衰减,引用会变化,需要长期追踪。

Vigilath 把这五类信号拆成可量化的检测维度,让「为什么没被引用」变成一份可执行的清单,而不是一个玄学问题。`,
    },
    en: {
      title: 'Why Does AI Cite One Source? Five Signals You Can Optimize',
      excerpt:
        "Generative engines don't pick sources at random. Authority, structure, freshness, consistency, and structured data decide whether your content makes it into the AI's final answer.",
      content: `## Citation Isn't Random

Many assume AI source selection is a black box. In reality it leans heavily on a set of observable, optimizable signals. Understand them, and you can reverse-engineer what to fix.

## Five Key Signals

### 1. Authority
AI favors widely recognized sources — industry press, Wikipedia / Baidu Baike entries, quality backlinks, inclusion on authoritative platforms. **Authority moves slowly, but the payoff lasts longest.**

### 2. Structure
Clear heading hierarchy, Q&A-style passages, and self-contained definition sentences make content easier to "slice" into an answer. A statement that stands on its own, free of surrounding context, is more likely to be quoted.

### 3. Freshness
For time-sensitive topics, AI prefers recent content. A page with a visible update date that's actively maintained beats a three-year-old "definitive" essay.

### 4. Consistency
When multiple sources state the same fact identically, AI is more confident using it. Keep core facts — founding date, positioning, product names — **identical** across your site, social, and third-party material.

### 5. Structured Data
Schema markup and clean entity information help engines understand exactly who you are and what you do, reducing the risk of confusion or misattribution.

## Putting It to Work

- **Detect** first: see who AI cites today and where you're missing.
- **Fill the gaps**: invest in the weakest signal first — usually authority and structure.
- **Monitor** continuously: signals decay and citations shift, so track over time.

Vigilath breaks these five signals into quantifiable detection dimensions, turning "why wasn't I cited" from guesswork into an actionable checklist.`,
    },
  },
  {
    slug: 'geo-for-global-brands',
    date: '2026-05-12',
    readingMinutes: 5,
    cover: '/image/blog/geo-for-global-brands.jpg',
    zh: {
      title: '出海品牌的 AI 可见性:别只盯着一个引擎',
      excerpt:
        '海外用 ChatGPT、Perplexity,国内用 DeepSeek、文心、豆包、元宝 —— 同一个品牌在不同引擎里的形象可能天差地别。多引擎覆盖,是出海与国内品牌都绕不开的功课。',
      content: `## 同一个品牌,多种「人设」

一个常见的误区:以为在某一个 AI 引擎里表现好,就等于「AI 可见性」做到位了。事实是,**不同引擎的训练数据、信源偏好、地域覆盖差异巨大**。

- 海外用户更多用 ChatGPT、Perplexity、Google AI Overviews、Claude;
- 国内用户更多用 DeepSeek、文心一言、豆包、腾讯元宝。

同一个问题,这些引擎给出的品牌描述、引用来源、推荐语气可能完全不同。只测一个引擎,就像只看一个地区的口碑。

## 为什么必须多引擎覆盖

1. **信源不同**:有的引擎重维基百科,有的重国内平台;权威建设要分别下手。
2. **语言不同**:中英文内容的覆盖度往往不对称,出海品牌中文强、英文弱,本土品牌反之。
3. **错误不同**:某个引擎里的事实错误,未必出现在另一个引擎,需要逐一排查。

## 给出海与本土品牌的建议

- **先做横向检测**:把主流海外 + 国内引擎一次性扫一遍,看清差距在哪。
- **按引擎补信源**:中文侧重百度百科、国内权威平台;英文侧重维基百科、行业媒体。
- **统一核心话术**:无论哪个引擎、哪种语言,品牌定位与核心事实必须一致,避免 AI 拼出矛盾的描述。

Vigilath 同时覆盖海外与国内主流引擎,把「同一个品牌在不同引擎里的样子」放进一张对比视图,让差距一眼可见。`,
    },
    en: {
      title: 'AI Visibility for Global Brands: Never Bet on One Engine',
      excerpt:
        'Overseas users reach for ChatGPT and Perplexity; domestic users reach for DeepSeek, Ernie, Doubao, and Yuanbao. The same brand can look completely different across engines — multi-engine coverage is non-negotiable.',
      content: `## One Brand, Many "Personas"

A common mistake: assuming that doing well in one AI engine means your "AI visibility" is handled. In reality, **engines differ enormously in training data, source preferences, and regional coverage.**

- Overseas users lean on ChatGPT, Perplexity, Google AI Overviews, Claude;
- Domestic (China) users lean on DeepSeek, Ernie, Doubao, Tencent Yuanbao.

For the same question, these engines may produce entirely different brand descriptions, cited sources, and framing. Testing one engine is like reading reviews from a single region.

## Why Multi-Engine Coverage Is Essential

1. **Different sources** — some engines weight Wikipedia, others weight domestic platforms; authority has to be built separately.
2. **Different languages** — Chinese and English coverage is often asymmetric: outbound brands are strong in Chinese and weak in English, and vice versa.
3. **Different errors** — a factual error in one engine may not appear in another, so each must be checked.

## Advice for Global and Domestic Brands

- **Run a cross-engine scan first** — sweep major overseas and domestic engines at once to see the gaps.
- **Build sources per engine** — Baidu Baike and domestic platforms for Chinese; Wikipedia and industry press for English.
- **Unify core messaging** — keep positioning and core facts identical across every engine and language so AI never stitches together a contradictory description.

Vigilath covers both overseas and domestic engines at once, placing "how your brand looks in each engine" into a single comparison view so gaps are obvious at a glance.`,
    },
  },
  {
    slug: 'geo-vs-aeo',
    date: '2026-05-04',
    readingMinutes: 5,
    cover: '/image/blog/geo-vs-aeo.jpg',
    zh: {
      title: 'GEO 与 AEO:一字之差,两件事',
      excerpt:
        'GEO 让 AI 在生成答案时推荐你,AEO 让你的内容被 AI 引擎收录抓取。两者一前一后,缺一不可。',
      content: `## 容易混淆的两个词

GEO 和 AEO 经常被混用,但它们解决的是问题的两端:

- **AEO(答案引擎优化 / 收录侧)**:确保你的内容能被 AI 引擎**抓取、理解、收录**。这是「进得去」的问题。
- **GEO(生成式引擎优化 / 推荐侧)**:确保 AI 在生成答案时**主动引用、推荐**你。这是「被选中」的问题。

打个比方:AEO 是让你的简历进入招聘系统的数据库,GEO 是让你在面试中被选中。进不去,谈不上被选;进去了,也未必被选。

## 为什么要一起做

只做 AEO:内容被收录了,却从不被引用 —— 你在库里,但没人提你。

只做 GEO:拼命建权威、改话术,但页面对 AI 爬虫不友好、抓不全 —— 努力进不了「答案」。

**两者是流水线的上下游**:先确保可被收录(AEO),再争取被推荐(GEO)。

## 落地顺序

1. **AEO 打底**:检查 AI 爬虫可达性、结构化数据、内容可抓取性。
2. **GEO 进阶**:建权威信号、统一核心事实、优化可被摘取的内容结构。
3. **持续监控**:收录与推荐都会随时间变化,需要长期追踪。

Vigilath 把 AEO 的收录侧检测与 GEO 的推荐侧审计放在同一个平台,从「能不能被抓到」一路覆盖到「会不会被推荐」。`,
    },
    en: {
      title: 'GEO vs. AEO: One Letter Apart, Two Different Jobs',
      excerpt:
        'GEO gets AI to recommend you when it generates an answer; AEO gets your content crawled and indexed by AI engines. One feeds the other — you need both.',
      content: `## Two Terms That Get Confused

GEO and AEO are often used interchangeably, but they solve opposite ends of the same problem:

- **AEO (Answer Engine Optimization / the ingestion side)** — making sure your content can be **crawled, understood, and indexed** by AI engines. This is the "getting in" problem.
- **GEO (Generative Engine Optimization / the recommendation side)** — making sure AI **actively cites and recommends** you when it generates an answer. This is the "getting picked" problem.

An analogy: AEO gets your résumé into the recruiting database; GEO gets you picked in the interview. You can't be picked if you're not in — and being in doesn't guarantee being picked.

## Why Do Both

AEO alone: your content is indexed but never cited — you're in the library, but nobody mentions you.

GEO alone: you build authority and refine messaging, but your pages are crawler-unfriendly and incompletely captured — your effort never reaches the "answer."

**They are upstream and downstream of one pipeline**: first ensure ingestion (AEO), then earn recommendation (GEO).

## Order of Operations

1. **AEO foundation** — check AI crawler reachability, structured data, content crawlability.
2. **GEO layer** — build authority signals, unify core facts, optimize extractable content structure.
3. **Continuous monitoring** — both ingestion and recommendation shift over time; track them long-term.

Vigilath places AEO ingestion-side detection and GEO recommendation-side auditing on one platform — covering everything from "can it be crawled" to "will it be recommended."`,
    },
  },
  {
    slug: 'monitor-brand-in-ai-answers',
    date: '2026-04-26',
    readingMinutes: 6,
    cover: '/image/blog/monitor-brand-in-ai-answers.jpg',
    zh: {
      title: '为什么 AI 可见性必须「持续监控」,而不是测一次',
      excerpt:
        'AI 模型在更新,信源在变化,竞品在发力 —— 你上个月的可见性结论,这个月可能已经失效。监控不是锦上添花,而是 GEO 的闭环。',
      content: `## 一次性检测的盲区

很多品牌做 GEO 的方式是:测一次,拿到一份报告,改一轮内容,然后就结束了。问题在于,**AI 可见性是一个动态变量**:

- 模型在迭代 —— 同一个引擎换了版本,引用偏好可能整体变了。
- 信源在更新 —— 新的报道、新的词条、竞品的新内容,都会挤占你的位置。
- 竞品在发力 —— 你不动,别人在补权威、补内容,相对排名就会下滑。

测一次的结论,保质期可能只有几周。

## 监控该看什么

持续监控不是反复跑同一个分数,而是盯住**变化**:

1. **引用频次变化**:你被多少引擎、在多少问题下提及,趋势是涨还是跌。
2. **语气变化**:AI 对你的描述是正面、中性还是负面,有没有突然转向。
3. **事实漂移**:核心事实(定位、产品、数据)有没有被 AI 说错或说旧。
4. **竞品相对位置**:同一个问题里,你和竞品谁被先提、被多提。

## 监控驱动行动

监控的价值在于把「被动发现」变成「主动应对」:

- 发现某引擎突然不再引用你 → 排查是不是信源被顶掉,及时补内容。
- 发现 AI 开始复述一条错误事实 → 在权威来源上纠正,阻止错误固化。
- 发现竞品在某类问题上反超 → 针对性补该话题的内容与权威。

Vigilath 把检测做成可重复、可对比的监控视图,让 AI 可见性从「一张快照」变成「一条曲线」—— 这才是 GEO 闭环里最容易被忽视、却最关键的一环。`,
    },
    en: {
      title: 'Why AI Visibility Demands Continuous Monitoring, Not a One-Off Test',
      excerpt:
        "Models update, sources shift, competitors push — last month's visibility conclusion may already be stale. Monitoring isn't a nice-to-have; it's what closes the GEO loop.",
      content: `## The Blind Spot of One-Off Testing

Many brands approach GEO like this: run one test, get a report, do one round of content edits, and stop. The problem is that **AI visibility is a moving variable**:

- Models iterate — a new version of the same engine can shift citation preferences wholesale.
- Sources update — new press, new entries, and competitors' new content all crowd out your spot.
- Competitors push — if you stand still while others build authority and content, your relative standing slips.

A single test's conclusion may stay valid for only a few weeks.

## What to Monitor

Continuous monitoring isn't re-running the same score; it's watching the **change**:

1. **Citation frequency** — how many engines and questions mention you, trending up or down.
2. **Framing** — whether AI describes you positively, neutrally, or negatively, and any sudden swing.
3. **Fact drift** — whether core facts (positioning, products, numbers) get stated wrong or stale.
4. **Competitor standing** — for the same question, who gets mentioned first and more often.

## Monitoring Drives Action

The value of monitoring is turning passive discovery into proactive response:

- An engine suddenly stops citing you → check whether your source got displaced and refill content.
- AI starts repeating a wrong fact → correct it at the authoritative source before it hardens.
- A competitor overtakes you on a topic → target that topic's content and authority.

Vigilath turns detection into a repeatable, comparable monitoring view — taking AI visibility from a single snapshot to a curve over time. That's the most overlooked, yet most critical, part of closing the GEO loop.`,
    },
  },
  {
    slug: 'wikipedia-and-ai-visibility',
    date: '2026-04-18',
    readingMinutes: 6,
    cover: '/image/blog/wikipedia-and-ai-visibility.jpg',
    zh: {
      title: '百科词条:被低估的 AI 可见性地基',
      excerpt:
        '维基百科、百度百科这类结构化知识库,是大量 AI 引擎的核心信源。一个准确、完整的词条,往往比十篇软文更能影响 AI 怎么描述你。',
      content: `## AI 的「事实底座」

当 AI 被问到「某某公司是做什么的」,它的回答很大程度上来自结构化、被广泛信任的知识库 —— 海外的维基百科,国内的百度百科、维基数据等。这些来源有三个特点让 AI 格外偏爱:

- **结构清晰**:实体、属性、关系都标得明明白白,容易被准确解析。
- **被反复引用**:其他网页大量引用,形成可信度的正反馈。
- **持续维护**:有编辑机制,信息相对新且可追溯。

结果是:**一个准确的百科词条,常常直接决定了 AI 对你的「第一印象」。**

## 词条缺失或错误的代价

- **没有词条**:AI 缺少权威底座,只能拼凑零散信息,容易答得含糊甚至张冠李戴。
- **词条过时**:旧的定位、旧的产品名会被 AI 反复复述,纠正成本极高。
- **词条有误**:错误事实一旦进入这层底座,会沿着引用链扩散到无数答案里。

## 怎么打好这块地基

1. **先检测**:看 AI 当前对你的描述,是否就来自某条过时或错误的百科信息。
2. **建 / 修词条**:确保核心事实(成立时间、定位、产品、关键数据)准确、有可靠引用来源支撑。
3. **保持一致**:词条里的事实必须和官网、社媒、第三方资料**一字不差**,避免 AI 拼出矛盾描述。
4. **持续维护**:产品、定位变化时同步更新,别让旧信息成为 AI 的默认答案。

百科词条是慢功夫,但它是 AI 可见性里回报最持久的一层。Vigilath 把百科 / 百科数据这类免费权威信源纳入实体检测,帮你看清地基稳不稳。`,
    },
    en: {
      title: 'Encyclopedia Entries: The Underrated Foundation of AI Visibility',
      excerpt:
        'Structured knowledge bases like Wikipedia and Baidu Baike are core sources for many AI engines. One accurate, complete entry often shapes how AI describes you more than ten promo articles.',
      content: `## AI's "Factual Bedrock"

When AI is asked "what does company X do," its answer draws heavily on structured, widely trusted knowledge bases — Wikipedia overseas, Baidu Baike and Wikidata domestically. Three traits make AI especially fond of these sources:

- **Clear structure** — entities, attributes, and relationships are explicitly marked and easy to parse accurately.
- **Heavily cited** — other pages reference them extensively, creating a positive feedback loop of credibility.
- **Actively maintained** — editing mechanisms keep information relatively fresh and traceable.

The result: **an accurate encyclopedia entry often directly decides AI's "first impression" of you.**

## The Cost of a Missing or Wrong Entry

- **No entry** — AI lacks an authoritative base and stitches together scattered info, answering vaguely or misattributing.
- **Stale entry** — outdated positioning or product names get repeated by AI, and are costly to correct.
- **Wrong entry** — once a false fact enters this layer, it spreads down the citation chain into countless answers.

## How to Lay This Foundation

1. **Detect first** — check whether AI's current description traces back to a stale or wrong encyclopedia fact.
2. **Build / fix the entry** — ensure core facts (founding date, positioning, products, key numbers) are accurate and backed by reliable citations.
3. **Stay consistent** — facts in the entry must match your site, social, and third-party material **verbatim**, so AI never assembles a contradiction.
4. **Maintain over time** — sync updates when products or positioning change; don't let old info become AI's default answer.

Encyclopedia entries are slow work, but they're the longest-lasting layer of AI visibility. Vigilath folds free authoritative sources like encyclopedias and structured-knowledge data into its entity checks, helping you see whether the foundation is solid.`,
    },
  },
  {
    slug: 'make-content-ai-crawlable',
    date: '2026-04-10',
    readingMinutes: 5,
    cover: '/image/blog/make-content-ai-crawlable.jpg',
    zh: {
      title: '让 AI 爬虫读得懂你:收录侧的四个基本功',
      excerpt:
        '内容再好,AI 爬虫抓不到、读不懂,也进不了答案。这篇讲收录侧(AEO)最该先做的四件事:可达性、结构、结构化数据、新鲜度信号。',
      content: `## 进不去,就谈不上被推荐

GEO 关注「被不被推荐」,但前提是 AI 引擎能**抓到、读懂**你的内容。这一层属于 AEO(答案引擎优化 / 收录侧),也是最容易被忽略、却最该先做的基本功。

## 四个基本功

### 1. 可达性:别把 AI 爬虫挡在门外
检查 robots 规则、防火墙、登录墙有没有误伤 AI 爬虫。很多品牌不知不觉把生成式引擎的抓取也一并屏蔽了 —— 内容再好,门是关的。

### 2. 结构:让机器一眼看懂层级
清晰的标题层级、语义化标签、问答式段落,能让爬虫准确理解「哪段是定义、哪段是步骤、哪段是结论」。一锅粥式的长段落,机器只能囫囵吞枣。

### 3. 结构化数据:把「你是谁」说清楚
用 Schema 标记组织、产品、文章等实体信息,帮引擎准确建立「你是谁、做什么」的认知,降低被混淆、被张冠李戴的风险。

### 4. 新鲜度信号:让引擎知道内容是活的
明确的更新日期、持续维护的痕迹,会让引擎更愿意把你当作可靠、时效的来源,尤其在时效性话题上。

## 落地顺序

先用一次收录侧检测看清:**哪些页面 AI 爬虫够不到、哪些结构机器读不顺、哪些实体没标清楚。** 把这层补齐,GEO 的优化才有地基。

Vigilath 的收录侧检测覆盖 AI 爬虫可达性、内容结构与结构化数据,从「能不能被抓到」一路接到「会不会被推荐」,让 AEO 与 GEO 在一个平台里闭环。`,
    },
    en: {
      title: 'Make Your Content AI-Crawlable: Four Fundamentals of the Ingestion Side',
      excerpt:
        "Great content that AI crawlers can't reach or parse never makes it into an answer. Here are the four ingestion-side (AEO) basics to do first: reachability, structure, structured data, freshness signals.",
      content: `## No Entry, No Recommendation

GEO is about whether you get recommended — but only if AI engines can **reach and parse** your content first. This layer is AEO (Answer Engine Optimization / the ingestion side): the most overlooked, yet the fundamentals you should tackle first.

## Four Fundamentals

### 1. Reachability: Don't Lock AI Crawlers Out
Check whether robots rules, firewalls, or login walls accidentally block AI crawlers. Many brands unknowingly shut out generative engines too — the content is great, but the door is closed.

### 2. Structure: Let Machines See the Hierarchy at a Glance
Clear heading hierarchy, semantic tags, and Q&A-style passages let crawlers accurately tell "this is the definition, this is the steps, this is the conclusion." A wall of undifferentiated text forces machines to guess.

### 3. Structured Data: Spell Out "Who You Are"
Use Schema markup for organizations, products, and articles so engines build an accurate picture of who you are and what you do, reducing confusion and misattribution.

### 4. Freshness Signals: Show the Content Is Alive
Explicit update dates and signs of active maintenance make engines more willing to treat you as a reliable, timely source — especially on time-sensitive topics.

## Order of Operations

Run an ingestion-side check first to see: **which pages AI crawlers can't reach, which structures machines struggle to parse, which entities aren't clearly marked.** Fix this layer, and GEO optimization finally has a foundation.

Vigilath's ingestion-side checks cover AI crawler reachability, content structure, and structured data — connecting "can it be crawled" all the way to "will it be recommended," closing the AEO–GEO loop on one platform.`,
    },
  },
  {
    slug: 'ai-hallucination-brand-risk',
    date: '2026-04-02',
    readingMinutes: 5,
    cover: '/image/blog/ai-hallucination-brand-risk.jpg',
    zh: {
      title: '当 AI 说错你的品牌:幻觉是新的舆情风险',
      excerpt:
        'AI 会一本正经地编造不存在的事实 —— 错的成立时间、不存在的产品、张冠李戴的负面。对品牌来说,这是一种必须被监控和纠正的新型舆情风险。',
      content: `## 一种新型的「说错」

传统舆情风险来自人 —— 差评、报道、传言。AI 时代多了一种:**模型自己编**。生成式引擎会以非常自信的语气,给出根本不存在的事实:

- 把你的成立时间、总部、规模说错;
- 凭空「发明」一个你没有的产品或功能;
- 把别家的负面、纠纷张冠李戴到你头上。

可怕之处在于:它听起来很可信,用户难以分辨,而且会被反复复述。

## 为什么必须当舆情来管

- **传播快**:一个错误一旦进入 AI 的常用信源,会沿引用链扩散到大量答案。
- **难发现**:它不像差评有平台、有时间戳,你不主动去问,根本不知道 AI 在背后怎么说你。
- **会固化**:纠正不及时,错误就会成为 AI 对你的「默认认知」。

## 怎么应对

1. **持续监测**:定期、多引擎地问 AI 关于你的核心事实,看有没有偏差或捏造。
2. **定位源头**:错误往往来自某条过时词条、某篇被误读的内容 —— 找到它。
3. **在权威层纠正**:更新百科词条、官网、第三方资料里的准确事实,从信源切断错误。
4. **复测确认**:纠正后再问一遍,确认 AI 的说法跟上了。

把 AI 幻觉当作一类需要长期监控的舆情风险,而不是偶发意外。Vigilath 同时覆盖 AI 可见性检测与舆情监控,帮你第一时间发现「AI 把你说错了」,并把它纳入可追踪、可纠正的闭环。`,
    },
    en: {
      title: 'When AI Gets Your Brand Wrong: Hallucination Is the New Reputation Risk',
      excerpt:
        'AI will confidently invent facts that never existed — wrong founding dates, nonexistent products, misattributed negatives. For brands, this is a new kind of reputation risk that must be monitored and corrected.',
      content: `## A New Way to Get It Wrong

Traditional reputation risk comes from people — bad reviews, press, rumors. The AI era adds another: **the model makes things up itself.** Generative engines state, in a very confident tone, facts that simply don't exist:

- getting your founding date, headquarters, or size wrong;
- "inventing" a product or feature you don't have;
- misattributing someone else's negatives or disputes to you.

What makes it dangerous: it sounds credible, users can't easily tell, and it gets repeated.

## Why It Must Be Managed Like Reputation

- **Spreads fast** — once an error enters AI's common sources, it propagates down the citation chain into many answers.
- **Hard to spot** — unlike a bad review with a platform and timestamp, you won't know what AI says about you behind the scenes unless you actively ask.
- **Hardens** — if not corrected promptly, the error becomes AI's "default understanding" of you.

## How to Respond

1. **Monitor continuously** — regularly ask multiple AI engines about your core facts and watch for drift or fabrication.
2. **Trace the source** — errors usually stem from a stale entry or a misread piece of content; find it.
3. **Correct at the authority layer** — update accurate facts in encyclopedia entries, your site, and third-party material to cut the error off at the source.
4. **Re-test to confirm** — ask again after correcting to verify AI has caught up.

Treat AI hallucination as a reputation risk to monitor long-term, not a one-off accident. Vigilath covers both AI visibility detection and sentiment monitoring, helping you catch "AI got you wrong" early and fold it into a trackable, correctable loop.`,
    },
  },
];

export function getPostBySlug(slug: string): BlogPost | undefined {
  return blogPosts.find((p) => p.slug === slug);
}
