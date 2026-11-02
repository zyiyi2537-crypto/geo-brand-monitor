// 舆情模块静态 mock 数据 — VITE_USE_MOCK_SENTIMENT=1 时使用,
// 否则 Sentiment.tsx + 各 Tab 走 sentimentApi(真实后端).
//
// 字段类型从 types/sentiment.ts 重导出,保持与后端契约一致.

import type { KeywordGroup, RiskLevel, RunStatus, SentimentPost } from '../types/sentiment';

export type {
  RunStatus, SentimentLabel, RiskLevel, RiskSignal, SentimentPost,
  KeywordGroup,
} from '../types/sentiment';

// Draft mock 形态 — 比真实 API 富一点(把 GenerateResult + DraftRow 揉一起方便 UI 测试).
export interface DraftMock {
  id: number;
  symbol: string;
  source: string | null;
  post_id: string | null;
  topic: string | null;
  title: string;
  summary: string;
  recommendation: 'conservative' | 'standard' | 'proactive';
  hitl_required: boolean;
  hitl_notes: string;
  drafts: {
    variant: 'conservative' | 'standard' | 'proactive';
    body: string;
    rationale: string;
    predicted_effect: string;
    cautions: string;
  }[];
  generated_at: string;
  model: string;
  status: 'pending_review' | 'approved' | 'archived';
}

// Mock 账号字段比 API 多一个 last_run_status 缩写,与真实 SentimentAccount 兼容
export interface SentimentAccountMock {
  id: number;
  user_id: number;
  target: string;
  ticker: string;
  aliases: string[];
  intent: string;
  keywords: string[];
  keyword_groups?: KeywordGroup[];
  excludes: string[];
  media_allowlist: string[];
  notify_emails: string[];
  weixin_album_urls: string[];
  newsnow_sources: string[];
  active: boolean;
  last_run_at: string | null;
  last_run_status: RunStatus;
  last_run_error: string | null;
  created_at: string;
}

export interface BriefMock {
  id: number;
  symbol: string;
  date: string;
  body: string;
  model: string;
  generated_at: string;
}

// ───── 账号 ─────
export const mockAccount: SentimentAccountMock = {
  id: 1,
  user_id: 1,
  target: 'Acme Cloud',
  ticker: 'ACME',
  aliases: ['ACMEAcme Cloud', '蓝云'],
  intent: '关注做空报告 / 业绩传闻 / 海外业务 / 数据中心需求',
  keywords: ['业绩', '做空', '管理层', '财报', '数据中心'],
  excludes: ['招聘', '实习'],
  media_allowlist: [],
  notify_emails: ['alerts@example.com', 'security@example.com'],
  weixin_album_urls: [],
  newsnow_sources: [],
  active: true,
  last_run_at: '2026-05-06T05:00:00+08:00',
  last_run_status: 'success',
  last_run_error: null,
  created_at: '2026-04-12T10:00:00+08:00',
};

// 切换 onboarding 演示用:URL 加 ?demo=onboarding 时主页用 null
export const mockEmptyAccount: SentimentAccountMock | null = null;

// ───── 真实客户配置规模演示(数据来自 20260408 版 ACME 关键词表)─────
// 6 大类、~85 个关键词条目,模拟客户实际复杂度.

export const mockKeywordGroups: KeywordGroup[] = [
  { name: "Brand", kind: "entity", items: [{ term: "Acme Cloud" }, { term: "Acme Infrastructure" }] },
  { name: "Products", kind: "project", items: [{ term: "Acme Edge" }, { term: "Acme Compute" }] },
  { name: "Risk", kind: "legal", items: [{ term: "Acme Cloud outage" }, { term: "Acme Cloud incident" }] },
];

// ───── Tab 1 KPI ─────
export const mockKpi = {
  total_today: 245,
  high_risk: 12,
  avg_sentiment: -0.18,
  active_sources: 8,
  trend_total_pct: 12,    // 比昨日 +12%
  trend_risk_pct: 8,
  trend_sentiment_pct: -5,
};

// ───── Tab 1 7-day sentiment trend(堆叠柱) ─────
export const mockSentimentTrend = [
  { date: '04-30', bullish: 18, neutral: 42, bearish: 15, mixed: 5 },
  { date: '05-01', bullish: 22, neutral: 38, bearish: 12, mixed: 6 },
  { date: '05-02', bullish: 15, neutral: 45, bearish: 20, mixed: 8 },
  { date: '05-03', bullish: 12, neutral: 50, bearish: 28, mixed: 10 },
  { date: '05-04', bullish: 14, neutral: 48, bearish: 32, mixed: 9 },
  { date: '05-05', bullish: 16, neutral: 44, bearish: 25, mixed: 7 },
  { date: '05-06', bullish: 20, neutral: 52, bearish: 35, mixed: 8 },
];

// ───── Tab 1 风险分布 ─────
export const mockRiskDist: Array<{ level: RiskLevel; count: number; color: string }> = [
  { level: 'none', count: 198, color: '#94a3b8' },
  { level: 'low', count: 35, color: '#fbbf24' },
  { level: 'medium', count: 8, color: '#fb923c' },
  { level: 'high', count: 4, color: '#ef4444' },
];

// ───── Tab 2 帖子(20 条覆盖各情感/风险/媒体)─────
export const mockPosts: SentimentPost[] = [
  {
    source: 'xueqiu', post_id: 'a1b2c3d4', symbol: 'ACME',
    title: '【独家】浑水做空报告深度解读:ACME 的债务结构有何隐忧',
    author: '@浑水中文',
    publish_time: '2026-05-06T03:14:00+08:00',
    url: 'https://xueqiu.com/post/a1b2c3d4',
    content: '今早浑水(Muddy Waters)发布了对Acme Cloud(ACME)的做空报告。报告指出,Q3 营收下滑 12%,而其披露的现金流与债务结构存在重大疑问。债务/EBITDA 比超 6,远高于行业均值。我们对该公司的财务披露持高度怀疑态度,建议投资者谨慎。',
    view_count: 12340, reply_count: 487,
    is_relevant: true, filter_reason: null,
    summary: '浑水发布做空报告,质疑 ACME 债务结构与现金流',
    sentiment_label: 'bearish', sentiment_score: -0.78,
    emotions: ['愤怒', '嘲讽'],
    topics: ['做空报告', '债务', '管理层'],
    entities: ['浑水', 'ACME 管理层', '审计师'],
    stance: 'hostile', intent: 'rumor', factuality: 'mixed',
    risk_level: 'high',
    risk_signals: [
      { type: '做空报告引用', reason: '直接引用浑水报告内容' },
      { type: '财务质疑', reason: '点名债务/现金流可疑' },
    ],
    influence_potential: 0.87,
    hidden_meaning: '通过引用做空报告制造抛售情绪,带节奏意图明显',
    citations: ['Q3 营收下滑 12%', '债务/EBITDA 比超 6'],
    reasoning: '高浏览量(12K+)+ 知名做空账户 + 时间集中(凌晨发布抢早盘)→ 影响力 0.87',
    model: 'gpt-4o-mini', analyzed_at: '2026-05-06T07:02:14+08:00',
  },
  {
    source: 'eastmoney', post_id: 'e5f6g7h8', symbol: 'ACME',
    title: 'ACME Q3 业绩说明会要点:数据中心需求强劲',
    author: '股民老王',
    publish_time: '2026-05-06T08:30:00+08:00',
    url: 'https://guba.eastmoney.com/post/e5f6g7h8',
    content: 'ACME 昨日业绩说明会披露 Q3 营收同比 +18%,数据中心订单饱满到 2027 年。管理层表示,海外扩张节奏稳健,新加坡数据中心已签订长期合同。',
    view_count: 8520, reply_count: 156,
    is_relevant: true, filter_reason: null,
    summary: '业绩会披露:Q3 营收同比 +18%,数据中心订单饱满',
    sentiment_label: 'bullish', sentiment_score: 0.65,
    emotions: ['乐观'],
    topics: ['业绩', '数据中心', '海外扩张'],
    entities: ['ACME', '管理层', '新加坡数据中心'],
    stance: 'supportive', intent: 'fact-share', factuality: 'factual_claim',
    risk_level: 'none',
    risk_signals: [],
    influence_potential: 0.42,
    hidden_meaning: null,
    citations: ['Q3 营收同比 +18%', '订单饱满到 2027'],
    reasoning: '官方业绩会内容传播 + 中等浏览量(8K)',
    model: 'gpt-4o-mini', analyzed_at: '2026-05-06T08:45:00+08:00',
  },
  {
    source: '36kr', post_id: 'i9j0k1l2', symbol: 'ACME',
    title: 'IDC 行业景气度延续,ACME 等头部厂商订单充裕',
    author: '36氪',
    publish_time: '2026-05-06T10:15:00+08:00',
    url: 'https://36kr.com/post/i9j0k1l2',
    content: '受 AI 算力需求驱动,IDC 行业 Q3 整体增速达 22%。头部厂商如 ACME、世纪华通等均披露订单饱满。但报告也指出,行业资本开支高企,毛利率承压。',
    view_count: 5230, reply_count: 38,
    is_relevant: true, filter_reason: null,
    summary: 'IDC 行业景气延续,但毛利率承压',
    sentiment_label: 'mixed', sentiment_score: 0.15,
    emotions: ['谨慎乐观'],
    topics: ['行业', '数据中心', '资本开支'],
    entities: ['ACME', '世纪华通', 'AI 算力'],
    stance: 'neutral', intent: 'analysis', factuality: 'factual_claim',
    risk_level: 'low',
    risk_signals: [{ type: '毛利率承压', reason: '行业资本开支高企' }],
    influence_potential: 0.38,
    hidden_meaning: null,
    citations: ['IDC 行业 Q3 增速 22%', '毛利率承压'],
    reasoning: '专业财经媒体 + 中等浏览,行业级影响力较稳定',
    model: 'gpt-4o-mini', analyzed_at: '2026-05-06T10:30:00+08:00',
  },
  {
    source: 'caixin', post_id: 'm3n4o5p6', symbol: 'ACME',
    title: '深度:ACME 海外扩张观察 — 机遇与不确定性并存',
    author: '财新记者',
    publish_time: '2026-05-05T16:00:00+08:00',
    url: 'https://caixin.com/article/m3n4o5p6',
    content: '财新记者实地走访 ACME 新加坡和马来西亚数据中心。客户来自欧美的 SaaS 厂商占比超 60%。地缘政治影响下,中资海外 IDC 业务面临审查压力。',
    view_count: 7140, reply_count: 22,
    is_relevant: true, filter_reason: null,
    summary: 'ACME 海外业务面临地缘审查不确定性',
    sentiment_label: 'mixed', sentiment_score: -0.22,
    emotions: ['谨慎'],
    topics: ['海外扩张', '地缘政治', '业务结构'],
    entities: ['ACME', '新加坡', '马来西亚'],
    stance: 'neutral', intent: 'analysis', factuality: 'factual_claim',
    risk_level: 'low',
    risk_signals: [{ type: '地缘风险', reason: '海外业务面临审查' }],
    influence_potential: 0.35,
    hidden_meaning: null,
    citations: ['欧美 SaaS 客户占比 >60%', '审查压力'],
    reasoning: '财新深度报道,影响力受众面广',
    model: 'gpt-4o-mini', analyzed_at: '2026-05-05T16:30:00+08:00',
  },
  {
    source: 'eastmoney', post_id: 'q7r8s9t0', symbol: 'ACME',
    title: '散户:ACME 还能拿吗?今天又跌了',
    author: '散户老李',
    publish_time: '2026-05-06T11:42:00+08:00',
    url: 'https://guba.eastmoney.com/post/q7r8s9t0',
    content: '今天又跌了 3%,这浑水报告杀伤力有点大。我手上还有 2 万股,要不要止损?求大神点拨。',
    view_count: 1820, reply_count: 64,
    is_relevant: true, filter_reason: null,
    summary: '散户求是否止损,情绪偏负面',
    sentiment_label: 'bearish', sentiment_score: -0.42,
    emotions: ['焦虑', '恐慌'],
    topics: ['做空报告', '止损'],
    entities: ['ACME', '浑水报告'],
    stance: 'skeptical', intent: 'question', factuality: 'opinion',
    risk_level: 'low',
    risk_signals: [],
    influence_potential: 0.28,
    hidden_meaning: '提问背后是情绪传染,可能引发更多散户跟风',
    citations: ['今天又跌了 3%'],
    reasoning: '散户提问类帖子,影响力中等',
    model: 'gpt-4o-mini', analyzed_at: '2026-05-06T11:55:00+08:00',
  },
  {
    source: 'weibo', post_id: 'u1v2w3x4', symbol: 'ACME',
    title: '#ACME# 浑水又来恶心人了,中概的命',
    author: '@老张投资',
    publish_time: '2026-05-06T09:20:00+08:00',
    url: 'https://weibo.com/post/u1v2w3x4',
    content: '又是浑水…中概股每隔几个月就要被"做空"一次。看看这报告里的数据,跟年报对得上吗?明显带节奏。',
    view_count: 4200, reply_count: 89,
    is_relevant: true, filter_reason: null,
    summary: '微博用户反驳浑水报告,质疑做空动机',
    sentiment_label: 'bullish', sentiment_score: 0.32,
    emotions: ['愤怒', '反驳'],
    topics: ['做空报告', '中概股'],
    entities: ['浑水', '中概股'],
    stance: 'supportive', intent: 'opinion', factuality: 'opinion',
    risk_level: 'none',
    risk_signals: [],
    influence_potential: 0.35,
    hidden_meaning: '为公司辩护,可能是机构号或忠实投资者',
    citations: ['跟年报对得上吗'],
    reasoning: '中等粉丝量博主,反驳做空报告,正面情绪',
    model: 'gpt-4o-mini', analyzed_at: '2026-05-06T09:45:00+08:00',
  },
  {
    source: 'zhihu', post_id: 'y5z6a7b8', symbol: 'ACME',
    title: '如何看待浑水做空 ACME 的报告?',
    author: '匿名用户',
    publish_time: '2026-05-06T07:55:00+08:00',
    url: 'https://zhihu.com/question/y5z6a7b8',
    content: '从报告内容看,有几处财务数据的解读存在硬伤。但 ACME 的债务结构确实需要关注,尤其是海外子公司的对外担保部分。建议看完原始公告再下结论。',
    view_count: 6890, reply_count: 142,
    is_relevant: true, filter_reason: null,
    summary: '知乎深度回答:做空报告有硬伤,但债务确需关注',
    sentiment_label: 'mixed', sentiment_score: 0.05,
    emotions: ['理性'],
    topics: ['做空报告', '债务', '财务分析'],
    entities: ['ACME', '浑水', '海外子公司'],
    stance: 'neutral', intent: 'analysis', factuality: 'factual_claim',
    risk_level: 'medium',
    risk_signals: [{ type: '海外子公司担保', reason: '债务结构关注点' }],
    influence_potential: 0.55,
    hidden_meaning: null,
    citations: ['财务数据硬伤', '海外子公司对外担保'],
    reasoning: '专业知乎回答,中高浏览,理性分析,影响力 0.55',
    model: 'gpt-4o-mini', analyzed_at: '2026-05-06T08:10:00+08:00',
  },
  {
    source: 'reddit', post_id: 'c9d0e1f2', symbol: 'ACME',
    title: 'Muddy Waters short report on $ACME — your thoughts?',
    author: 'u/dataops_pro',
    publish_time: '2026-05-06T01:30:00+08:00',
    url: 'https://reddit.com/r/investing/post/c9d0e1f2',
    content: 'Muddy Waters dropped a short report on ACME this morning. The data center thesis seems intact but the debt structure questions are real. What\'s the consensus from people who follow Asian data center plays?',
    view_count: 2100, reply_count: 47,
    is_relevant: true, filter_reason: null,
    summary: 'Reddit 用户讨论浑水报告,理性求证',
    sentiment_label: 'neutral', sentiment_score: -0.05,
    emotions: ['理性'],
    topics: ['做空报告', '债务'],
    entities: ['Muddy Waters', 'ACME'],
    stance: 'neutral', intent: 'question', factuality: 'opinion',
    risk_level: 'low',
    risk_signals: [],
    influence_potential: 0.32,
    hidden_meaning: null,
    citations: ['debt structure questions are real'],
    reasoning: '海外英文论坛理性讨论,中等影响力',
    model: 'gpt-4o-mini', analyzed_at: '2026-05-06T02:00:00+08:00',
  },
  {
    source: 'xueqiu', post_id: 'g3h4i5j6', symbol: 'ACME',
    title: 'ACME 现金流分析:浑水的指控站不住脚',
    author: '@雪球财报派',
    publish_time: '2026-05-06T13:20:00+08:00',
    url: 'https://xueqiu.com/post/g3h4i5j6',
    content: '我对照 ACME 最近 4 个季度的财报,做了详细的现金流拆分。浑水报告中所谓的"现金流可疑"其实是把自由现金流和经营现金流混淆了。详细 Excel 见下载链接。',
    view_count: 9870, reply_count: 215,
    is_relevant: true, filter_reason: null,
    summary: '雪球分析师驳斥浑水现金流指控',
    sentiment_label: 'bullish', sentiment_score: 0.58,
    emotions: ['专业', '坚定'],
    topics: ['做空报告', '现金流', '财报'],
    entities: ['浑水', 'ACME', '自由现金流'],
    stance: 'supportive', intent: 'analysis', factuality: 'factual_claim',
    risk_level: 'none',
    risk_signals: [],
    influence_potential: 0.62,
    hidden_meaning: null,
    citations: ['自由现金流 vs 经营现金流', '4 个季度财报'],
    reasoning: '专业财报派 + 详细数据 + 高浏览量,反向情绪扛旗者',
    model: 'gpt-4o-mini', analyzed_at: '2026-05-06T13:50:00+08:00',
  },
  {
    source: 'eastmoney', post_id: 'k7l8m9n0', symbol: 'ACME',
    title: '今天加仓 ACME,逆向投资就这一锤子',
    author: '价值投资者2020',
    publish_time: '2026-05-06T14:30:00+08:00',
    url: 'https://guba.eastmoney.com/post/k7l8m9n0',
    content: '今天 ACME 跌了 5%,我加了 30%。做空报告其实把基本面利空都释放出来了,反而是机会。',
    view_count: 3210, reply_count: 78,
    is_relevant: true, filter_reason: null,
    summary: '逆向投资者加仓 ACME',
    sentiment_label: 'bullish', sentiment_score: 0.45,
    emotions: ['坚定', '反向'],
    topics: ['加仓', '做空报告'],
    entities: ['ACME'],
    stance: 'supportive', intent: 'opinion', factuality: 'opinion',
    risk_level: 'none',
    risk_signals: [],
    influence_potential: 0.30,
    hidden_meaning: null,
    citations: ['加了 30%'],
    reasoning: '逆向操作,情绪正面,中等浏览',
    model: 'gpt-4o-mini', analyzed_at: '2026-05-06T14:55:00+08:00',
  },
  {
    source: 'weibo', post_id: 'o1p2q3r4', symbol: 'ACME',
    title: 'ACME 高管减持公告,这是要跑?',
    author: '@小道消息官博',
    publish_time: '2026-05-05T20:15:00+08:00',
    url: 'https://weibo.com/post/o1p2q3r4',
    content: '昨晚 ACME 公告高管减持 0.5%,虽然量不大,但是和浑水报告的时间点对得上,有点诡异。',
    view_count: 5680, reply_count: 134,
    is_relevant: true, filter_reason: null,
    summary: '微博质疑高管减持时间点',
    sentiment_label: 'bearish', sentiment_score: -0.55,
    emotions: ['怀疑'],
    topics: ['高管减持', '做空报告'],
    entities: ['ACME', '高管'],
    stance: 'skeptical', intent: 'rumor', factuality: 'mixed',
    risk_level: 'medium',
    risk_signals: [
      { type: '高管减持', reason: '时间点与做空报告重合' },
    ],
    influence_potential: 0.58,
    hidden_meaning: '阴谋论倾向,可能进一步发酵',
    citations: ['高管减持 0.5%', '时间点对得上'],
    reasoning: '小道消息号 + 高浏览,容易引发恐慌情绪',
    model: 'gpt-4o-mini', analyzed_at: '2026-05-05T20:40:00+08:00',
  },
  {
    source: 'caixin', post_id: 's5t6u7v8', symbol: 'ACME',
    title: '财新评论:中概股做空攻防进入新阶段',
    author: '财新评论员',
    publish_time: '2026-05-05T18:00:00+08:00',
    url: 'https://caixin.com/article/s5t6u7v8',
    content: '近年中概股频繁遭遇做空机构狙击,ACME 案例显示,海外做空机构与国内监管的博弈进入新阶段。建议监管层加强对做空报告的事实核查机制。',
    view_count: 4520, reply_count: 18,
    is_relevant: true, filter_reason: null,
    summary: '财新评论中概做空攻防',
    sentiment_label: 'neutral', sentiment_score: -0.10,
    emotions: ['理性'],
    topics: ['做空报告', '监管'],
    entities: ['中概股', 'ACME', '监管'],
    stance: 'neutral', intent: 'analysis', factuality: 'opinion',
    risk_level: 'low',
    risk_signals: [],
    influence_potential: 0.40,
    hidden_meaning: null,
    citations: ['监管层加强事实核查'],
    reasoning: '权威媒体评论,理性视角',
    model: 'gpt-4o-mini', analyzed_at: '2026-05-05T18:30:00+08:00',
  },
  {
    source: 'bilibili', post_id: 'w9x0y1z2', symbol: 'ACME',
    title: '【深度】3 分钟看懂浑水做空报告全文',
    author: 'B 站财经 UP',
    publish_time: '2026-05-06T15:00:00+08:00',
    url: 'https://bilibili.com/video/w9x0y1z2',
    content: '我把浑水做空 ACME 的报告全文翻译并图文解析,3 分钟告诉你真相。视频中演示了债务/EBITDA 的算法,以及为什么浑水的算法存在偏颇。',
    view_count: 18500, reply_count: 320,
    is_relevant: true, filter_reason: null,
    summary: 'B 站 UP 主深度解读做空报告',
    sentiment_label: 'mixed', sentiment_score: 0.10,
    emotions: ['专业'],
    topics: ['做空报告', '财务解析'],
    entities: ['浑水', 'ACME'],
    stance: 'neutral', intent: 'analysis', factuality: 'factual_claim',
    risk_level: 'low',
    risk_signals: [],
    influence_potential: 0.65,
    hidden_meaning: null,
    citations: ['债务/EBITDA 算法', '浑水算法偏颇'],
    reasoning: '高播放视频内容(18.5K)+ 中性立场,影响力较高',
    model: 'gpt-4o-mini', analyzed_at: '2026-05-06T15:30:00+08:00',
  },
  {
    source: 'xueqiu', post_id: 'a3b4c5d6', symbol: 'ACME',
    title: 'ACME 海外业务结构图(独家整理)',
    author: '@基本面研究',
    publish_time: '2026-05-04T11:00:00+08:00',
    url: 'https://xueqiu.com/post/a3b4c5d6',
    content: '整理了 ACME 截至 2026 Q1 的海外业务结构图,包括新加坡、马来、印尼三地子公司的持股比例和担保关系。',
    view_count: 6700, reply_count: 95,
    is_relevant: true, filter_reason: null,
    summary: '雪球用户整理 ACME 海外业务结构',
    sentiment_label: 'neutral', sentiment_score: 0.12,
    emotions: ['专业'],
    topics: ['海外业务', '子公司'],
    entities: ['ACME', '新加坡', '马来', '印尼'],
    stance: 'neutral', intent: 'fact-share', factuality: 'factual_claim',
    risk_level: 'none',
    risk_signals: [],
    influence_potential: 0.45,
    hidden_meaning: null,
    citations: ['持股比例', '担保关系'],
    reasoning: '专业研究内容,中高浏览',
    model: 'gpt-4o-mini', analyzed_at: '2026-05-04T11:30:00+08:00',
  },
  {
    source: 'toutiao', post_id: 'e7f8g9h0', symbol: 'ACME',
    title: '惊!ACME 一夜跌 5%,这家公司还能买吗?',
    author: '财经爆料',
    publish_time: '2026-05-06T16:00:00+08:00',
    url: 'https://toutiao.com/article/e7f8g9h0',
    content: '今天 ACME 一夜暴跌 5%,创年内新低。受浑水做空报告影响,加上高管减持,投资者情绪极度悲观。',
    view_count: 12100, reply_count: 287,
    is_relevant: true, filter_reason: null,
    summary: '今日头条标题党报道 ACME 暴跌',
    sentiment_label: 'bearish', sentiment_score: -0.65,
    emotions: ['恐慌', '夸张'],
    topics: ['股价', '做空报告', '高管减持'],
    entities: ['ACME'],
    stance: 'hostile', intent: 'rumor', factuality: 'mixed',
    risk_level: 'medium',
    risk_signals: [{ type: '情绪夸大', reason: '标题党用"惊"夸大跌幅' }],
    influence_potential: 0.50,
    hidden_meaning: '通过夸张标题制造恐慌博取流量',
    citations: ['一夜跌 5%', '创年内新低'],
    reasoning: '今日头条流量 + 标题党风格,影响力中高',
    model: 'gpt-4o-mini', analyzed_at: '2026-05-06T16:20:00+08:00',
  },
  {
    source: 'weixin', post_id: 'i1j2k3l4', symbol: 'ACME',
    title: 'IDC 行业月报:ACME 仍是首选标的',
    author: '某券商研究',
    publish_time: '2026-05-04T09:00:00+08:00',
    url: 'https://mp.weixin.qq.com/article/i1j2k3l4',
    content: '券商 IDC 行业月报维持 ACME "买入"评级,目标价 $X。理由:订单饱满、海外业务增长、估值已反映短期不确定性。',
    view_count: 3450, reply_count: 24,
    is_relevant: true, filter_reason: null,
    summary: '某券商月报维持 ACME 买入评级',
    sentiment_label: 'bullish', sentiment_score: 0.70,
    emotions: ['信心'],
    topics: ['券商评级', '行业'],
    entities: ['ACME'],
    stance: 'supportive', intent: 'recommendation', factuality: 'factual_claim',
    risk_level: 'none',
    risk_signals: [],
    influence_potential: 0.40,
    hidden_meaning: null,
    citations: ['维持"买入"评级'],
    reasoning: '券商研究背书,影响力 0.40',
    model: 'gpt-4o-mini', analyzed_at: '2026-05-04T09:30:00+08:00',
  },
  {
    source: 'zhihu', post_id: 'm5n6o7p8', symbol: 'ACME',
    title: 'ACME 投资逻辑还在吗?',
    author: '价值守望者',
    publish_time: '2026-05-06T17:30:00+08:00',
    url: 'https://zhihu.com/question/m5n6o7p8',
    content: '业绩、估值、行业地位都还在,但短期面临做空报告冲击。中长期看,数据中心需求是确定性的,ACME 仍是优质标的。',
    view_count: 4180, reply_count: 56,
    is_relevant: true, filter_reason: null,
    summary: '知乎理性回答 ACME 投资逻辑',
    sentiment_label: 'bullish', sentiment_score: 0.40,
    emotions: ['理性'],
    topics: ['投资逻辑', '估值'],
    entities: ['ACME'],
    stance: 'supportive', intent: 'analysis', factuality: 'opinion',
    risk_level: 'none',
    risk_signals: [],
    influence_potential: 0.35,
    hidden_meaning: null,
    citations: ['数据中心需求是确定性的'],
    reasoning: '知乎中等浏览理性回答',
    model: 'gpt-4o-mini', analyzed_at: '2026-05-06T18:00:00+08:00',
  },
  {
    source: 'eastmoney', post_id: 'q9r0s1t2', symbol: 'ACME',
    title: 'ACME 跌停了!浑水赢了',
    author: '股海老兵',
    publish_time: '2026-05-06T15:30:00+08:00',
    url: 'https://guba.eastmoney.com/post/q9r0s1t2',
    content: '今天 ACME 美股盘前跌了 8%,基本就是跌停状态了。浑水这次赢麻了。还能拿吗?',
    view_count: 7800, reply_count: 198,
    is_relevant: true, filter_reason: null,
    summary: '股民惊呼 ACME 接近跌停',
    sentiment_label: 'bearish', sentiment_score: -0.72,
    emotions: ['沮丧', '恐慌'],
    topics: ['股价', '做空报告'],
    entities: ['ACME', '浑水'],
    stance: 'hostile', intent: 'opinion', factuality: 'mixed',
    risk_level: 'medium',
    risk_signals: [{ type: '股价恐慌', reason: '夸大盘前跌幅' }],
    influence_potential: 0.55,
    hidden_meaning: null,
    citations: ['美股盘前跌了 8%', '跌停'],
    reasoning: '高浏览股吧帖,情绪强烈',
    model: 'gpt-4o-mini', analyzed_at: '2026-05-06T15:55:00+08:00',
  },
  {
    source: 'xueqiu', post_id: 'u3v4w5x6', symbol: 'ACME',
    title: 'ACME 公司紧急回应:浑水报告失实',
    author: '@ACME 投资者关系',
    publish_time: '2026-05-06T18:45:00+08:00',
    url: 'https://xueqiu.com/post/u3v4w5x6',
    content: 'ACME 投资者关系部门发布声明:浑水做空报告中关于债务结构和现金流的描述存在重大失实。公司将于明日召开电话会议向投资者澄清。',
    view_count: 15600, reply_count: 423,
    is_relevant: true, filter_reason: null,
    summary: 'ACME 官方紧急回应做空报告',
    sentiment_label: 'bullish', sentiment_score: 0.55,
    emotions: ['坚定', '严肃'],
    topics: ['官方回应', '做空报告'],
    entities: ['ACME', '投资者关系部门', '浑水'],
    stance: 'supportive', intent: 'fact-share', factuality: 'factual_claim',
    risk_level: 'none',
    risk_signals: [],
    influence_potential: 0.78,
    hidden_meaning: null,
    citations: ['描述存在重大失实', '明日召开电话会议'],
    reasoning: '官方账号 + 高浏览(15K),官方权威信号,影响力 0.78',
    model: 'gpt-4o-mini', analyzed_at: '2026-05-06T19:00:00+08:00',
  },
  {
    source: 'eastmoney', post_id: 'y7z8a9b0', symbol: 'ACME',
    title: 'ACME 招聘:数据中心运维工程师 (北京)',
    author: 'HR 小姐姐',
    publish_time: '2026-05-05T14:00:00+08:00',
    url: 'https://guba.eastmoney.com/post/y7z8a9b0',
    content: 'Acme Cloud北京数据中心招聘,要求 3 年以上经验,薪资面议。',
    view_count: 320, reply_count: 5,
    is_relevant: false,
    filter_reason: '招聘信息,与舆情监测无关',
    summary: '招聘信息',
    sentiment_label: 'unknown', sentiment_score: 0,
    emotions: [], topics: [], entities: [], stance: 'neutral',
    intent: 'other', factuality: 'factual_claim',
    risk_level: 'none', risk_signals: [],
    influence_potential: 0.05,
    hidden_meaning: null, citations: [],
    reasoning: '匹配 excludes 关键词"招聘",过滤',
    model: 'gpt-4o-mini', analyzed_at: '2026-05-05T14:30:00+08:00',
  },
];

// ───── Tab 3 简报(7 天)─────
const briefBody1 = `# ACME 舆情简报 · 2026-05-06

## 一、概览

今日讨论量 245 条,负面占比 32%,出现高风险信号 12 个。浑水做空报告引发集中讨论,情绪偏负面但无系统性风险。ACME 投资者关系部门已于晚间发布声明回应,预期次日有官方电话会议。

- 总声量:**245 帖**(较昨日 +12%)
- 情感分布:看多 86 / 中性 100 / 看空 50 / 复杂 9
- 风险分布:none 198 · low 35 · medium 8 · high 4

## 二、关键主题

1. **浑水做空报告**(89 帖,主导情感:负面)
   散户与机构对债务结构与现金流的合理性产生分歧。专业账户(@雪球财报派)做了详细驳斥,但情绪面仍偏空。
   引用:[【独家】浑水做空报告深度解读](https://xueqiu.com/post/a1b2c3d4)

2. **Q3 业绩公告**(56 帖,主导情感:正面)
   营收 +18% 数据强劲,数据中心订单饱满到 2027,但被做空报告稀释关注度。
   引用:[ACME Q3 业绩说明会要点](https://guba.eastmoney.com/post/e5f6g7h8)

3. **数据中心需求**(34 帖,主导情感:正面)
   行业景气度延续,AI 算力驱动 IDC 行业 Q3 增速 22%,但毛利率承压。

4. **海外业务结构**(28 帖,主导情感:中性)
   财新报道海外子公司面临地缘审查不确定性,但短期影响有限。

## 三、风险信号

- ⚠️ **HIGH** 做空报告引用 — 浑水中文直接发布全文翻译,2 小时内 487 评论,情绪传染面广
  **建议**:今日内发布官方澄清,引用第三方审计意见;管理层后续电话会议要点先行准备
- ⚠️ **MEDIUM** 财务结构质疑 — 多个雪球用户跟进债务/EBITDA 计算,部分硬伤需澄清
  **建议**:IR 团队准备 Q&A 文档,主动联系 5 家主流券商分析师
- ⚠️ **MEDIUM** 高管减持时间点 — 微博质疑减持时间与做空报告重合,有阴谋论倾向
  **建议**:公开减持背景说明(如:行权计划),避免阴谋论发酵

## 四、值得关注的帖子

1. [浑水做空报告深度解读](https://xueqiu.com/post/a1b2c3d4) — @浑水中文 — bearish/HIGH — 综合影响 0.87
2. [ACME 公司紧急回应:浑水报告失实](https://xueqiu.com/post/u3v4w5x6) — @ACME 投资者关系 — bullish/none — 0.78
3. [ACME 现金流分析:浑水的指控站不住脚](https://xueqiu.com/post/g3h4i5j6) — @雪球财报派 — bullish/none — 0.62
4. [3 分钟看懂浑水做空报告全文](https://bilibili.com/video/w9x0y1z2) — B 站财经 UP — mixed/low — 0.65
5. [ACME 高管减持公告,这是要跑?](https://weibo.com/post/o1p2q3r4) — @小道消息官博 — bearish/medium — 0.58

## 五、建议动作

1. **今日内**:针对浑水做空报告发布官方回应(参考三档草稿),CEO/CFO 出面强化可信度
2. **24 小时内**:召开 IR 电话会议,逐项回应做空报告中的财务质疑;邀请独立审计师参与
3. **本周内**:IR 团队整理 Q3 财务详细 Q&A,主动联络 5 家主流券商分析师
4. **持续**:监测做空报告二次发酵,设置高风险预警阈值;关注高管减持解读演变
`;

const briefBody2 = `# ACME 舆情简报 · 2026-05-05

## 一、概览
今日讨论量 198 条,情绪偏中性,无重大事件。Q3 业绩说明会预热为主要话题。

- 总声量:198 帖
- 情感分布:看多 42 / 中性 120 / 看空 30 / 复杂 6
- 风险分布:none 175 · low 18 · medium 5 · high 0

## 二、关键主题
1. **业绩说明会预热**(64 帖,主导情感:正面)
   投资者期待 Q3 业绩,关注海外业务进展
2. **数据中心行业**(38 帖,主导情感:正面)
   AI 算力驱动行业景气

## 三、风险信号
- ⚠️ MEDIUM 海外业务地缘风险 — 财新深度报道,需关注后续监管动向

## 四、值得关注的帖子
1. [深度:ACME 海外扩张观察](https://caixin.com/article/m3n4o5p6) — 财新记者 — mixed/low — 0.35
2. [IDC 行业月报:ACME 仍是首选标的](https://mp.weixin.qq.com/article/i1j2k3l4) — 某券商研究 — bullish/none — 0.40

## 五、建议动作
1. 准备业绩会要点
2. 跟进财新报道,提前回应海外业务关切
`;

export const mockBriefs: BriefMock[] = [
  { id: 1, symbol: 'ACME', date: '2026-05-06', body: briefBody1, model: 'gpt-4o-mini', generated_at: '2026-05-06T07:02:18+08:00' },
  { id: 2, symbol: 'ACME', date: '2026-05-05', body: briefBody2, model: 'gpt-4o-mini', generated_at: '2026-05-05T07:01:55+08:00' },
  { id: 3, symbol: 'ACME', date: '2026-05-04', body: '# ACME 舆情简报 · 2026-05-04\n\n## 一、概览\n讨论平稳,164 帖,情绪偏正。\n\n## 二、关键主题\n业绩预期为主。\n\n## 三、风险信号\n无 medium+ 风险。\n\n## 四、值得关注的帖子\n暂无突出帖。\n\n## 五、建议动作\n维持监测频次。', model: 'gpt-4o-mini', generated_at: '2026-05-04T07:00:33+08:00' },
  { id: 4, symbol: 'ACME', date: '2026-05-03', body: '# ACME 舆情简报 · 2026-05-03\n\n## 一、概览\n讨论 142 帖,周末低活跃度。', model: 'gpt-4o-mini', generated_at: '2026-05-03T07:00:00+08:00' },
  { id: 5, symbol: 'ACME', date: '2026-05-02', body: '# ACME 舆情简报 · 2026-05-02\n\n## 一、概览\n讨论 178 帖。', model: 'gpt-4o-mini', generated_at: '2026-05-02T07:00:00+08:00' },
  { id: 6, symbol: 'ACME', date: '2026-04-W18', body: '# ACME 舆情周报 · 2026-W18\n\n## 一、本周概览\n本周累计 1245 帖,关键事件:浑水做空报告。', model: 'gpt-4o-mini', generated_at: '2026-05-04T08:00:00+08:00' },
  { id: 7, symbol: 'ACME', date: '2026-04', body: '# ACME 舆情月报 · 2026-04\n\n## 一、月度概览\n4 月累计 5872 帖,情绪整体偏正。', model: 'gpt-4o-mini', generated_at: '2026-05-01T09:00:00+08:00' },
];

// ───── Tab 4 草稿 ─────
export const mockDrafts: DraftMock[] = [
  {
    id: 1, symbol: 'ACME',
    source: 'xueqiu', post_id: 'a1b2c3d4', topic: null,
    title: '回应浑水做空报告',
    summary: '需要法务+IR审核,不引用未公布数据',
    recommendation: 'standard',
    hitl_required: true,
    hitl_notes: '法务+IR 必审核 Q3 营收数据引用部分;CEO/CFO 露面建议',
    drafts: [
      {
        variant: 'conservative',
        body: '感谢市场各方对公司的关注。公司已注意到近期相关讨论。所有公开披露的财务信息均以本公司向交易所提交的公告为准。我们将持续以公开、透明的方式与投资者沟通。',
        rationale: '风险最低,保留法律解释空间,适合在事实尚未完全清晰时发布',
        predicted_effect: '中性 +0.05,不会激化情绪也无法消解市场疑虑',
        cautions: '可能被解读为冷漠或回避;如需快速消解情绪请考虑标准/进取版',
      },
      {
        variant: 'standard',
        body: 'Acme Cloud(ACME)已第一时间核实近期市场上传播的相关报告。经核实,该报告中关于本公司债务结构和现金流的描述存在重大失实。本公司将于明日上午 9:00 召开电话会议,逐项回应相关质疑。所有财务数据以本公司公告为准,我们承诺以最透明的方式回应市场关切。',
        rationale: '平衡透明度与法律边界,既给出明确否认,又预告后续动作,符合标准 IR 实践',
        predicted_effect: '偏正 +0.20,主流投资者认可,做空报告热度可下降',
        cautions: '不可引用未在公告中披露的具体数字;电话会议时间承诺务必落实',
      },
      {
        variant: 'proactive',
        body: '为消除市场疑虑,Acme Cloud(ACME)宣布以下举措:(1) 于明日召开 IR 电话会议,CEO 和 CFO 共同出席,逐项回应做空报告中的所有质疑;(2) 邀请第三方独立审计机构对 Q3 财报关键科目进行专项核查并公开结果;(3) 启动股票回购计划,展示对公司长期价值的信心。我们对市场承诺,以最高标准的透明度和负责任的态度回应每一位投资者的关切。',
        rationale: '主动姿态强势挽回情绪,符合"用行动回应"的最佳 IR 实践',
        predicted_effect: '+0.45,显著但有风险。回购计划可能强化"市场认可"信号',
        cautions: '⚠ 法务必审任何新承诺;CEO/CFO 行程必须可保证;回购计划需董事会通过;独立审计耗时不可承诺过紧时间表',
      },
    ],
    generated_at: '2026-05-06T09:42:18+08:00',
    model: 'gpt-4.1',
    status: 'pending_review',
  },
  {
    id: 2, symbol: 'ACME',
    source: null, post_id: null, topic: '高管减持时间点说明',
    title: '主题草稿:高管减持背景说明',
    summary: '为消除阴谋论,主动公开减持背景',
    recommendation: 'standard',
    hitl_required: true,
    hitl_notes: '减持背景需董秘办确认是否属于行权计划',
    drafts: [
      {
        variant: 'conservative',
        body: '关于近期高管减持公告,本公司董秘办说明:本次减持系预先签署的股票出售计划(10b5-1)的常规执行,与近期市场上的相关报告无关联。',
        rationale: '简短陈述事实,法律风险最低',
        predicted_effect: '+0.10',
        cautions: '需确认是否真有 10b5-1 计划',
      },
      {
        variant: 'standard',
        body: 'Acme Cloud董秘办说明:近期公告的高管减持系基于 2025 年 12 月签署的预设股票交易计划(10b5-1)的常规执行,该计划在做空报告发布前数月即已制定,与近期市场报告无关。本公司高管对公司长期价值保持充分信心。',
        rationale: '提供具体时间锚点,有效消解阴谋论',
        predicted_effect: '+0.30',
        cautions: '具体日期需董秘办核实',
      },
      {
        variant: 'proactive',
        body: 'Acme Cloud董秘办说明:此次高管减持系基于 2025 年 12 月签署的 10b5-1 预设交易计划的执行,与近期市场报告完全无关。同时,我们披露:该高管同期持有公司股票期权行权后所需的纳税资金来源,通过此次减持解决,符合常规高管薪酬激励安排。本公司管理层对长期发展信念坚定。',
        rationale: '完全透明披露细节,彻底消除疑虑',
        predicted_effect: '+0.45',
        cautions: '⚠ 期权行权 + 纳税资金来源属于个人信息,需高管本人同意披露',
      },
    ],
    generated_at: '2026-05-06T10:15:00+08:00',
    model: 'gpt-4.1',
    status: 'approved',
  },
];

// ───── 知识库 ─────
export const mockKnowledge = {
  brand_voice: `# ACME 品牌语调

## 核心调性
- **专业、克制、可信赖** — 我们是基础设施服务商,不做情绪化表达
- **数据驱动** — 所有声明以数据/公告为准,不轻易主观判断
- **长期视角** — 短期波动不是我们关注的重点,长期价值是

## 词汇偏好
- ✅ "我们承诺"、"以公告为准"、"长期价值"、"基础设施"
- ❌ "请投资者放心"(过于主观)、"必将"、"绝对"

## 禁忌
- 不与做空机构正面"开战",不出言挑衅
- 不评价同行,不踩竞品
- 不承诺未经审议的具体数字`,
  legal_redlines: `# 法务红线

## 绝对禁止
1. **不可承诺未公告的财务数据** — 任何具体数字必须先有公告
2. **不可披露未上市信息** — 战略 / 客户名单 / 价格等
3. **不可对未来业绩做出预测** — 即便是定性陈述也需法务审核
4. **不可对竞品做出贬损评价**
5. **不可未经董事会授权宣布回购/分红等重大资本动作**

## 高度敏感
- 高管个人信息(薪酬、行权)需高管本人同意
- 海外子公司信息涉及多国监管,需各地法务并行审核

## 必经流程
- 任何官方声明 → 法务 → IR → CFO → CEO → 发布
- 紧急情况 → 法务 + IR 双人决策可发短声明,后补流程`,
  response_playbook: `# 响应剧本

## 三档策略

### 保守版(Conservative)
- **适用**:事实尚未清晰、法务存疑、低影响事件
- **风格**:简短、原则性陈述、不做新承诺
- **目标**:维持稳定不激化

### 标准版(Standard)
- **适用**:大多数情况下的"主动应对" — 事实清晰、有明确否认空间
- **风格**:具体回应、给出后续动作时间表、保持透明
- **目标**:消解疑虑 + 引导舆论

### 进取版(Proactive)
- **适用**:重大事件需要强力回应、品牌价值受冲击、有完整应对方案
- **风格**:多措并举、邀请第三方背书、主动披露关键信息
- **目标**:扭转情绪 + 建立信任`,
};

// ───── 辅助函数 ─────

/** 影响力综合分(yuqin chat agent top_posts SQL 同款公式)*/
export function noteworthyScore(p: SentimentPost): number {
  return (p.influence_potential ?? 0) * Math.abs(p.sentiment_score ?? 0);
}

export function topPostsByInfluence(posts: SentimentPost[], n = 5): SentimentPost[] {
  return [...posts]
    .filter(p => p.is_relevant)
    .sort((a, b) => noteworthyScore(b) - noteworthyScore(a))
    .slice(0, n);
}

/** 距某 ISO 时间字符串的"X 小时前/X 分钟前"。*/
export function timeAgo(iso: string, now: Date = new Date()): string {
  const diff = (now.getTime() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return '刚刚';
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
  return `${Math.floor(diff / 86400)} 天前`;
}
