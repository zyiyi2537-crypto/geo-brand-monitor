// 舆情模块共享类型定义.
// 字段命名严格对齐后端(yuqin SQLite + GEO sentiment_accounts).

export type RunStatus = 'pending' | 'running' | 'success' | 'failed' | null;
export type SentimentLabel = 'bullish' | 'bearish' | 'neutral' | 'mixed' | 'unknown';
export type RiskLevel = 'none' | 'low' | 'medium' | 'high';
export type DraftVariant = 'conservative' | 'standard' | 'proactive';

// ─────────────── 关键词分类(对标客户实际配置规模) ───────────────
// 客户用 Excel 维护 6+ 类、上百关键词,我们用结构化分组承载.

export type KeywordKind =
  | 'entity'      // 公司主体(目标 + 子公司 + 别名 + 项目代号)
  | 'legal'       // 法院 / 诉讼 / 官司
  | 'exec'        // 高管(姓名 + Title 前缀,展开成"主体 × 姓名"组合)
  | 'project'     // 项目代号(如 Reits / 超互联 / AIDC)
  | 'competitor'  // 友商(用于对比分析,不是品牌主体)
  | 'custom';     // 用户自定义

export interface KeywordItem {
  term: string;            // 关键词文本(单词或带空格的"主体 修饰词")
  is_new?: boolean;        // 黄色高亮 = 新增
  enabled?: boolean;       // 默认 true
  note?: string;           // 备注
}

export interface KeywordGroup {
  name: string;            // 显示名:"公司主体" / "法院诉讼" / 自定义
  kind: KeywordKind;       // 类别
  items: KeywordItem[];
}

export interface SentimentAccount {
  id: number;
  user_id: number;
  target: string;
  ticker: string;
  aliases: string[];
  intent: string | null;
  /** 旧字段:扁平关键词列表(向后兼容).新代码用 keyword_groups. */
  keywords: string[];
  excludes: string[];
  /** 结构化关键词分组 — 6+ 类别,每类多条目. */
  keyword_groups?: KeywordGroup[];
  /** 媒体白名单(平台 code 列表,空数组 = 全平台). */
  media_allowlist: string[];
  notify_emails: string[];
  /** 微信公众号合集 URL 列表 — 周级别盯防 KOL/竞品官号. 空 = 不启用. */
  weixin_album_urls: string[];
  /** newsnow source id 列表(如 ['weibo','zhihu','v2ex']). 空 = 不启用. */
  newsnow_sources: string[];
  active: boolean;
  last_run_at: string | null;
  last_run_status: RunStatus;
  last_run_error: string | null;
  created_at: string;
}

export interface AccountCreatePayload {
  target: string;
  ticker: string;
  aliases?: string[];
  intent?: string;
  keywords?: string[];
  keyword_groups?: KeywordGroup[];
  excludes?: string[];
  media_allowlist?: string[];
  notify_emails?: string[];
  weixin_album_urls?: string[];
  newsnow_sources?: string[];
  run_now?: boolean;
}

export type AccountUpdatePayload = Partial<{
  target: string;
  ticker: string;
  aliases: string[];
  intent: string;
  keywords: string[];
  keyword_groups: KeywordGroup[];
  excludes: string[];
  media_allowlist: string[];
  notify_emails: string[];
  weixin_album_urls: string[];
  newsnow_sources: string[];
  active: boolean;
}>;

/** 把结构化分组展开成扁平 keywords 列表(发给 yuqin 用).
 *  不区分 kind,所有 enabled 条目都拼进去.
 */
export function flattenKeywordGroups(groups: KeywordGroup[]): string[] {
  const out: string[] = [];
  for (const g of groups) {
    for (const it of g.items) {
      if (it.enabled === false) continue;
      const t = it.term.trim();
      if (t) out.push(t);
    }
  }
  return Array.from(new Set(out));    // 去重
}

export interface RunStatusPayload {
  status: RunStatus;
  last_run_at: string | null;
  error: string | null;
}

export interface RiskSignal {
  type: string;
  reason: string;
}

/** posts JOIN analyses 行(yuqin sentinel-service 返回的形态).
 *  注意:JSON 字段被 _row_to_dict 反序列化,所以前端拿到的是数组而不是 JSON 字符串.
 */
export interface SentimentPost {
  source: string;
  post_id: string;
  symbol: string;
  title: string | null;
  author: string | null;
  publish_time: string | null;
  ingested_at?: string | null;
  url: string | null;
  content: string | null;
  view_count: number | null;
  reply_count: number | null;
  like_count?: number | null;
  share_count?: number | null;
  // analyses
  is_relevant: 0 | 1 | boolean;
  filter_reason: string | null;
  summary: string | null;
  sentiment_label: SentimentLabel | string | null;
  sentiment_score: number | null;
  emotions?: string[];
  topics?: string[];
  entities?: string[];
  stance: string | null;
  intent: string | null;
  factuality: string | null;
  risk_level: RiskLevel | string | null;
  risk_signals?: RiskSignal[];
  influence_potential: number | null;
  hidden_meaning: string | null;
  citations?: string[];
  reasoning: string | null;
  model: string | null;
  analyzed_at: string | null;
}

export interface PostsResponse {
  count: number;
  items: SentimentPost[];
  total?: number;
  offset?: number;
  limit?: number;
  days?: number;
  start?: string | null;
  end?: string | null;
}

// 排序键 — 与后端 _SORT_SQL.keys() 一一对应。
// 默认 newest(对标图里"按最新文章 默认")。
export type PostSortKey =
  | 'newest' | 'oldest'
  | 'engagement' | 'replies' | 'likes' | 'shares' | 'views'
  | 'cluster'
  | 'mediaAZ' | 'mediaZA'
  | 'scoreSentiment' | 'scoreInfluence';

export interface PostsQuery {
  limit?: number;
  offset?: number;
  /** days 与 start/end 二选一;后端 start/end 优先 */
  days?: number;
  start?: string;
  end?: string;
  sort_by?: PostSortKey;
}

export interface BriefSummary {
  id: number;
  symbol: string;
  date: string;
  model: string;
  generated_at: string;
}

export interface Brief extends BriefSummary {
  body: string;
}

export interface BriefsResponse {
  count: number;
  items: BriefSummary[];
}

export interface DraftRow {
  id: number;
  symbol: string;
  source: string | null;
  post_id: string | null;
  topic: string | null;
  variant: DraftVariant | string;
  body: string;
  rationale: string | null;
  predicted_effect: string | null;
  cautions: string | null;
  model: string;
  generated_at: string;
}

export interface DraftsResponse {
  count: number;
  items: DraftRow[];
}

/** 草稿生成接口直接返回的形态(三档 + 元信息) */
export interface DraftGenerateResult {
  summary: string;
  drafts: {
    variant: DraftVariant;
    body: string;
    rationale: string | null;
    predicted_effect: string | null;
    cautions: string | null;
  }[];
  recommendation: DraftVariant;
  hitl_required: boolean;
  hitl_notes: string;
}

export interface KnowledgeDoc {
  key: 'brand_voice' | 'legal_redlines' | 'response_playbook' | string;
  body: string;
  updated_at: string;
}

export type MediaType =
  | 'web' | 'weibo' | 'wechat' | 'app' | 'forum'
  | 'short_video' | 'long_video' | 'broadcast'
  | 'newspaper' | 'magazine' | 'blog' | 'ecommerce' | 'review';

export type Industry =
  | 'finance' | 'general' | 'tech' | 'science'
  | 'party_media' | 'health' | 'overseas_en';

/** 媒体平台目录条目(全局只读,GET /api/sentiment/platforms 返回)。
 *  - media_type:载体形态(网媒/微博/微信/APP/论坛/短视频/长视频/...)
 *  - industry:主题/行业(金融财经/综合资讯/科技/科普/党政央媒/...)
 *  - region:地区
 *  category 是 legacy 单轴,前端不再消费(后端 SentimentPlatformOut 仍输出
 *  以兼容外部),保留为可选 string。 */
export interface SentimentPlatform {
  code: string;
  domain: string;
  category?: string;                            // legacy
  media_type: MediaType | string;
  industry: Industry | string;
  region: 'mainland' | 'hk' | 'overseas' | string;
  name_zh: string;
  name_en: string;
}

export interface TodayKpi {
  total_today: number;
  high_risk: number;
  avg_sentiment: number;
  active_sources: number;
  trend_total_pct: number;
  trend_risk_pct: number;
  trend_sentiment_pct: number;
}

export interface SentimentTrendRow {
  date: string;
  bullish: number;
  neutral: number;
  bearish: number;
  mixed: number;
}

export interface RiskDistRow {
  level: RiskLevel;
  count: number;
  color: string;
}

export interface TodayResponse {
  ticker: string;
  kpi: TodayKpi;
  sentiment_trend: SentimentTrendRow[];
  risk_dist: RiskDistRow[];
  latest_brief: Brief | null;
  top_posts: SentimentPost[];
}

// ─────────────── newsnow 实时热点(不绑 account)──────────────
// 数据极薄:只有 title + url + 极少 extra(微博/知乎偶尔含 hotness)。
// 无时间戳 / 无正文 / 无作者 — 这是 newsnow 接口的天花板。
// fetched_at 由后端注入,代表"这一拉的时刻"。

export type NewsnowCategory = 'social' | 'news' | 'tech' | 'finance' | string;

export interface NewsnowSource {
  id: string;
  name_zh: string;
  name_en: string;
  category: NewsnowCategory;
}

export interface NewsnowSourcesResponse {
  count: number;
  items: NewsnowSource[];
}

export interface NewsnowItem {
  id?: string | number;
  title: string;
  url?: string;
  mobileUrl?: string;
  /** newsnow 偶尔在 extra 里塞 hotness / icon / info,前端用 string 渲染 */
  extra?: {
    info?: string;
    icon?: string;
    hover?: string;
    [k: string]: unknown;
  };
}

export interface NewsnowHotResponse {
  source: string;
  items: NewsnowItem[];
  count: number;
  fetched_at: string;
}
