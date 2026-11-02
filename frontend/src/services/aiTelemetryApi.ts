// AI 遥测 API 客户端 — 主题 CRUD + 立即试跑.
// 后端就绪前用 mock 数据;VITE_USE_MOCK_AI_TELEMETRY=1 强制 mock.

import { localizedHeaders, readApiError } from './apiError';

const API_BASE = (import.meta.env.VITE_API_URL as string) || '/api';

export type EngineId =
  | 'deepseek' | 'doubao' | 'qwen' | 'wenxin' | 'yuanbao'
  | 'chatgpt' | 'claude' | 'gemini' | 'grok' | 'copilot';

export const CN_ENGINES: EngineId[] = ['deepseek', 'doubao', 'qwen', 'wenxin', 'yuanbao'];
export const GLOBAL_ENGINES: EngineId[] = ['chatgpt', 'claude', 'gemini', 'grok', 'copilot'];

export type ReviewStatus = 'pending' | 'approved' | 'rejected';

// 2026-05-28 — 4 维场景扩展:单 seed 并行调 4 套 LLM 模板产出
export type SceneType = 'search' | 'qa' | 'intent' | 'brand';
export const ALL_SCENES: SceneType[] = ['search', 'qa', 'intent', 'brand'];

export interface SeedPrompt {
  text: string;
  status: ReviewStatus;
  submitted_at?: string | null;
  approved_at?: string | null;
  rejected_at?: string | null;
  reviewer_id?: number | null;
}

export interface Topic {
  id: number;
  name: string;
  target: string;
  target_aliases: string[];
  industry: string;
  queries: string[];
  query_cluster_ids?: number[];      // 与 queries 同长,可能为空(老主题或未聚类)
  query_statuses?: ReviewStatus[];   // Phase C — 与 queries 同长,legacy 默认 approved
  query_selected?: boolean[];        // Phase D — 与 queries 同长,标记是否选为监测问题
  query_seeds?: string[];            // 2026-05-20 — 与 queries 同长,种子提示词(legacy 为 "")
  query_is_seed?: boolean[];         // 2026-05-26 — 与 queries 同长,标记该 query 是 seed 原文派生
  query_locked?: boolean[];          // 2026-05-26 — 与 queries 同长,locked=True 的 query 不可取消勾选(seed 原文)
  query_scene_types?: SceneType[];   // 2026-05-28 — 与 queries 同长,4 维场景标签(legacy 默认 search)
  clusters?: ClusterMetaPersist[];   // picker 端聚类后的簇元数据
  seed_prompts?: SeedPrompt[];       // Phase C — 已提交的种子词列表
  engines: EngineId[];
  enabled: boolean;
  last_run_at?: string | null;
  last_run_status?: 'success' | 'failed' | 'running' | null;
  // Phase D — 资料 + 申请状态机
  profile?: BrandProfile;
  submission_status?: SubmissionStatus;
  submitted_at?: string | null;
  approved_at?: string | null;
  rejected_at?: string | null;
  reviewer_id?: number | null;
  selected_query_count?: number;
  // 修订号:每次编辑都 +1。后端 _append_changelog 是单一来源。
  version?: number;
  // Phase D.1 — AI 自动生成排程
  auto_generate_enabled?: boolean;
  auto_generate_time?: string;    // "HH:MM"
  auto_generate_count?: number;
  auto_generate_last_run_at?: string | null;
  auto_publish_enabled?: boolean;   // 按 publish_date 自动发布;admin 可关
  // v1.4 — admin 配的扩展提示词;TopicOut 返回但普通用户不渲染
  prompt_extension?: string | null;
  created_at?: string;
  updated_at?: string;
}

export type SubmissionStatus = 'draft' | 'pending' | 'approved' | 'rejected';

// Phase D — 品牌资料 (6 大模块)
export interface BrandProfile {
  // 一、资料基础标识
  profile_name: string;
  company_full_name: string;
  company_short_name: string;
  industry: string;
  // 主体类型 — 驱动扩展词风格。service_tool / manufacturer / brand_owner / other / ''
  // 资料抽取时 AI 自动判,表单里可手改。
  entity_type: string;
  core_business_lines: string[];
  service_geo: string;
  website: string;
  // 二、内容创作方向
  creation_directions: string[];
  copywriting_types: string[];
  target_platforms: string[];
  content_tones: string[];
  content_redlines: string[];
  // 三、品牌主体信息
  team_size: string;
  founded_year: string;
  core_credentials: string[];
  brand_diff_tags: string[];
  // 四、产品 / 服务核心信息
  core_service_overview: string;
  service_features: string[];
  service_process: string[];
  target_scenarios: string[];
  service_guarantees: string[];
  // 四、品牌故事与情感素材(原五,2026-05-17 删了「目标用户与痛点」节)
  brand_story: string;
  key_person_story: string;
  case_stories: string[];
  brand_values: string;
  // 五、补充素材与创作边界(原七)
  available_materials: string[];
  brand_slogan: string;
  core_message: string;
  extra_notes: string;
}

export const EMPTY_BRAND_PROFILE: BrandProfile = {
  profile_name: '', company_full_name: '', company_short_name: '',
  industry: '', entity_type: '', core_business_lines: [], service_geo: '', website: '',
  creation_directions: [], copywriting_types: [], target_platforms: [],
  content_tones: [], content_redlines: [],
  team_size: '', founded_year: '', core_credentials: [], brand_diff_tags: [],
  core_service_overview: '', service_features: [], service_process: [],
  target_scenarios: [], service_guarantees: [],
  brand_story: '', key_person_story: '', case_stories: [], brand_values: '',
  available_materials: [], brand_slogan: '', core_message: '', extra_notes: '',
};

// 2026-05-20 起 50 → 200,扩展候选与最终勾选同上限
export const MAX_SELECTED_QUERIES = 200;
// 单次 seed 扩展候选上限(用户从这一批里再勾 ≤ MAX_SELECTED_QUERIES 个)
export const MAX_EXPANSION_CANDIDATES = 200;

export interface ClusterMetaPersist {
  cluster_id: number;
  label: string;
  size: number;
}

export interface TopicPayload {
  name: string;
  target: string;
  target_aliases: string[];
  industry: string;
  queries: string[];
  query_cluster_ids?: number[];
  clusters?: ClusterMetaPersist[];
  // 2026-05-20 — 与 queries 同长,每条 query 来自哪个种子提示词。
  // picker 按种子分组,保存时把映射一并传后端,持久化到 queries_json[].seed。
  query_seeds?: string[];
  // 2026-06-11 — 与 queries 同长,4 维场景标签;保存时持久化到 queries_json[].scene_type。
  query_scene_types?: SceneType[];
  engines: EngineId[];
  enabled: boolean;
  // Phase C — 创建 / 更新时把当前种子词附带提交,后端追加进 seed_prompts_json (pending);
  // 编辑器允许多条种子串行扇出,因此接 list。字段名跟 Topic.seed_prompts (对象数组)区分.
  seed_drafts?: string[];
  // Phase D — 同请求带资料;后端写 profile_json + 追加 changelog。
  profile?: BrandProfile;
  // v1.4 — admin 工作台编辑时可写;普通用户编辑时即使带也会被后端忽略
  prompt_extension?: string | null;
}

// Step1 落库专用 — POST /topics/draft。queries/engines 可空,只带品牌资料 + 基础字段。
export interface TopicDraftPayload {
  name: string;
  target: string;
  target_aliases: string[];
  industry: string;
  engines: EngineId[];
  enabled: boolean;
  profile?: BrandProfile;
}

export interface RunNowResult {
  engine: EngineId;
  query: string;
  answer: string;
  citations: { url: string; domain: string; title: string }[];
  error?: string | null;
}

export interface QueryCandidate {
  text: string;
  score: number;
  sources: string[];
  cluster_id?: number;
  // 2026-05-20 — 这条候选是哪个种子提示词扩展出来的。
  // picker 用它做"按种子分组渲染"(不再用 cluster_id)。
  seed?: string;
  // 2026-05-28 — 4 维场景标签;新后端 /suggest-queries v2 每条候选都带,前端按场景分组/打 badge.
  scene?: SceneType;
}

export interface ClusterMeta {
  cluster_id: number;
  label: string;
  size: number;
  medoid_index: number;
}

export interface RunSummary {
  id: number;
  topic_id: number;
  status: 'running' | 'success' | 'failed';
  started_at: string;
  finished_at: string | null;
  error: string | null;
  response_count: number;
}

export interface ResponseRow {
  id: number;
  engine: EngineId;
  query: string;
  answer: string;
  citations: { url: string; domain: string; title: string }[];
  video_url: string | null;
  source_url?: string | null;
  error: string | null;
  created_at: string;
  hit?: boolean;
  hit_excerpt?: string | null;
  mention_position?: string | null;
  brand_rank?: number | null;
}

// ─── v1 引用追踪 ──────────────────────────────────────────

export type CellStatus = 'pending' | 'running' | 'done';

export interface QueryHitCell {
  query: string;
  engine: EngineId;
  status: CellStatus;
  first_hit_at: string | null;
  first_hit_response_id: number | null;
  last_checked_at: string | null;
  total_runs: number;
  total_hits: number;
  aliases_hit?: string[];  // 2026-05-26 — 该 cell 命中过的 target / alias 字面词,前端按命中词筛选用
}

export interface EngineFirstHit {
  engine: EngineId;
  first_hit_at: string | null;
  first_hit_query: string | null;
  days_after_start: number | null;
}

export interface TrackingMatrix {
  topic_id: number;
  target: string;
  target_aliases: string[];
  queries: string[];
  engines: EngineId[];
  started_at: string;
  cells: QueryHitCell[];
  timeline: EngineFirstHit[];
  total_runs: number;
  total_cells: number;
  hit_cells: number;
  hit_cells_pct: number;
}

export interface CellEvidence {
  response_id: number;
  run_id: number;
  created_at: string;
  engine: EngineId;
  query: string;
  hit: boolean;
  hit_excerpt: string | null;
  mention_position?: 'lead' | 'body' | 'tail' | 'unknown' | string | null;
  source_url: string | null;
  answer: string;
  citations: { url: string; domain: string; title: string }[];
}

// ─── v1.3 SAIV / 竞品份额 ──────────────────────────────────

export interface CompetitorShareEntry {
  name: string;
  count: number;
  pct: number;
}

export interface PositionDist {
  lead: number;
  body: number;
  tail: number;
  unknown: number;
}

export interface ShareOfVoice {
  topic_id: number;
  target: string;
  period_days: number;
  brand_count: number;
  competitors_count_total: number;
  saiv_pct: number;
  competitors: CompetitorShareEntry[];
  position_dist: PositionDist;
  optimal_rate_pct: number;
  total_runs: number;
  sample_size: number;
}

export interface CellInsightRec {
  priority: 'P0' | 'P1' | 'P2' | string;
  title: string;
  action: string;
  why: string;
}

export interface CompetitorMention {
  name: string;
  count: number;
  snippet: string;
}

export interface CellInsight {
  id: number;
  topic_id: number;
  query: string;
  engine: EngineId;
  window_start: string;
  window_end: string;
  verdict: 'hit_stable' | 'hit_unstable' | 'near_miss' | 'no_signal' | 'negative_mention' | string;
  summary: string;
  competitors_top3: CompetitorMention[];
  recommendations: CellInsightRec[];
  answer_format: string | null;
  citation_domains: string[];
  evidence_response_ids: number[];
  llm_model: string;
  prompt_version: string;
  generated_at: string;
  feedback: 'helpful' | 'not_helpful' | 'wrong' | null;
}

export interface CellDrawer {
  cell: QueryHitCell;
  evidence: CellEvidence[];
  insight: CellInsight | null;
}

// ─── v1.2 周报 ────────────────────────────────────────────

export interface BriefingAction {
  priority: string;
  title: string;
  why: string;
  how: string;
}

export interface Briefing {
  id: number;
  topic_id: number;
  period_start: string;
  period_end: string;
  body_md: string;
  kpi_snapshot: Record<string, unknown>;
  top_actions: BriefingAction[];
  delivered_email_at: string | null;
  feedback_score: number | null;
  llm_model: string;
  prompt_version: string;
  generated_at: string;
}

export interface KpiBlock {
  value: number;
  delta_pct: number | null;
  sparkline: number[];
}

export interface TrendPoint {
  date: string;
  values: Partial<Record<EngineId, number>>;
}

export interface DomainCount {
  domain: string;
  count: number;
  pct: number;
}

export interface OwnedSplit {
  owned: number;
  other: number;
  owned_pct: number;
  delta_pct: number | null;
}

export interface Overview {
  topic_id: number;
  period_days: number;
  brand_keywords: string[];
  visibility: KpiBlock;
  citations: KpiBlock;
  growth: KpiBlock;
  engines_covered: KpiBlock;
  engines_total: number;
  trend: TrendPoint[];
  engines: EngineId[];
  top_domains: DomainCount[];
  owned_split: OwnedSplit;
  engine_domain_matrix: Partial<Record<EngineId, Record<string, number>>>;
  engine_factor_matrix: Partial<Record<EngineId, Record<string, number>>>;  // engine -> {GEO 因子: count}
}

export interface ClusterBreakdownItem {
  cluster_id: number;
  label: string;
  query_count: number;
  response_count: number;
  mention_count: number;
  mention_rate: number;
  citation_count: number;
}

export interface IntentBreakdown {
  topic_id: number;
  period_days: number;
  brand_keywords: string[];
  clusters: ClusterBreakdownItem[];
  uncategorized: ClusterBreakdownItem;
}

// ── 品牌增长页 — 雷达 5 维 + 行业基准 + 竞品替代证据 ───────
export interface PositionBreakdown {
  top3_pct: number;
  top5_pct: number;
  visible_pct: number;
  source_pct: number;
  seed_coverage_pct: number;
}

export interface EngineSlice {
  engine: string;
  breakdown: PositionBreakdown;
  total_queries: number;
}

export interface GroupBreakdown {
  scope: 'query';
  total_queries: number;
  total_engines: number;
  total_cells: number;
  breakdown: PositionBreakdown;
  by_engine: EngineSlice[];
}

export interface PositionBreakdownResp {
  topic_id: number;
  period_days: number;
  industry: string;
  // 兼容字段:与 query_group 同值,RadarBlock 仍读这里
  total_cells: number;
  total_queries: number;
  breakdown: PositionBreakdown;
  industry_baseline: PositionBreakdown | null;
  // 全 query 组 + 各 engine 切片(模型多选对比用)
  query_group: GroupBreakdown | null;
  engines: string[];
}

// ── 增长报告(首次跑批 vs 当前累计) ────────────────────────
// period=0 语义:全部历史(自上线至今)。品牌增长页统一传这个。
export const ALL_TIME_PERIOD = 0;

export type GrowthStatus = 'new_hit' | 'improved' | 'steady' | 'regressed' | 'still_miss';

export interface GrowthQueryRow {
  query: string;
  seed?: string | null;
  baseline_hit: boolean;
  baseline_rank: number | null;
  baseline_engines: string[];
  current_hit: boolean;
  current_rank: number | null;
  current_engines: string[];
  status: GrowthStatus;
}

export interface GrowthSnapshot {
  run_at: string | null;
  queries_total: number;
  queries_hit: number;
  hit_rate_pct: number;
  avg_rank: number | null;
  engines_covered: number;
}

export interface GrowthReport {
  topic_id: number;
  target: string;
  generated_at: string;
  has_baseline: boolean;
  baseline: GrowthSnapshot;
  current: GrowthSnapshot;
  rows: GrowthQueryRow[];
}

export interface IndustryBenchmark {
  industry: string;
  sample_size: number;
  breakdown: PositionBreakdown | null;
}

export interface CompetitorSubstitutionItem {
  query: string;
  competitor_name: string;
  competitor_count: number;
  sample_response_id: number;
  sample_snippet: string;
}

export interface AdminAccount {
  id: number;
  email: string;
  name?: string | null;
  // 客户填的品牌名(ai_telemetry_topics.target).admin 画像列表优先展示
  // 这个,代表客户在系统里的身份;users.name 是 admin 内部备注,作为兜底.
  brand_target?: string | null;
  is_active: boolean;
  is_admin: boolean;
  topic_count: number;
  has_prompt_extension: boolean;
}

export interface AdminRun {
  run_id: number;
  topic_id: number;
  topic_name: string;
  topic_target: string;
  user_id: number;
  user_email: string;
  started_at: string;
  finished_at: string | null;
  status: 'running' | 'success' | 'failed' | string;
  error: string | null;
  response_count: number;
  hit_count: number;
  error_count: number;
}

export interface CompetitorSubstitutionResp {
  topic_id: number;
  period_days: number;
  competitor_filter: string | null;
  items: CompetitorSubstitutionItem[];
  total: number;
}


export function isMockMode(): boolean {
  return String(import.meta.env.VITE_USE_MOCK_AI_TELEMETRY || '').toLowerCase() === '1';
}

// ── mock state ──────────────────────────────────────────────
let _mockSeq = 100;
const _mockTopics: Topic[] = [
  {
    id: 1,
    name: 'VNET 品牌问询',
    target: '世纪互联',
    target_aliases: ['VNET', 'Century Link China'],
    industry: 'IDC 数据中心',
    queries: ['世纪互联怎么样', '国内 IDC 服务商推荐', 'VNET vs 万国数据'],
    engines: ['deepseek', 'doubao', 'qwen', 'wenxin', 'yuanbao', 'chatgpt'],
    enabled: true,
    last_run_at: new Date(Date.now() - 2 * 3600 * 1000).toISOString(),
    last_run_status: 'success',
  },
];

export interface BrowserWorker {
  id: number;
  worker_uid: string;
  hostname: string | null;
  label: string | null;
  region: string | null;
  exit_ip: string | null;
  engines: string[];
  max_concurrency: number;
  status: string;          // online | offline(由心跳新鲜度算)
  raw_status: string;      // online | draining | disabled | offline
  enabled: boolean;
  version: string | null;
  last_heartbeat_at: string | null;
  done_today: number;
  in_flight: number;
  breaker: Record<string, unknown>;
}

export interface WorkerQueueStats {
  queue: Record<string, Record<string, number>>;   // engine → {status: count}
  used_today: Record<string, number>;              // engine → 今日发起数
  daily_cap: Record<string, number | null>;        // engine → 日上限(null=不限)
}

export interface EngineSessionRow {
  id: number;
  engine: string;
  label: string | null;
  account_handle: string | null;   // 采集端抓的昵称/掩码手机号
  status: string;            // active | quarantined | expired
  use_count: number;
  captcha_count: number;
  last_used_at: string | null;
  captured_at: string | null;
  expires_at: string | null;
  last_fail_type: string | null;
  used_today?: number;
  auth_type?: string | null;       // password/apikey/qr/cookie
  egress?: string | null;          // proxy/host
  exit_ip?: string | null;         // 实际出口 IP(worker check-in 回报)
  exit_ip_at?: string | null;
  daily_cap?: number | null;       // 每账号覆盖值(null=用引擎默认)
  effective_cap?: number;          // 实际生效上限(0=不限)
  remaining?: number | null;       // 今日剩余配额(null=不限)
  priority?: number;               // 调度优先级,低值优先
  disabled?: boolean;              // 是否被手动停用
  rate_limited?: boolean;          // 是否限流冷却中
}

export interface SelectorProposal {
  input_sels?: string[];
  send_sels?: string[];
  answer_sels?: string[];
  chat_api?: string;
  url?: string;
}

export interface EngineHealth {
  engine: string;
  ok: boolean;
  ans_len: number;
  cites: number;
  error: string | null;
}

export interface EngineIpGroup {
  exit_ip: string;
  engine: string;
  accounts: number;
  used_today: number;
  ip_account_total: number;   // 该 IP 上跨引擎的总账号数(密度)
}

export interface EngineSessionPage {
  items: EngineSessionRow[];
  total: number;             // 筛选后条数(驱动分页)
  grand_total: number;       // 全池条数
  active_total: number;      // 全池 status=active 且未过期(真正可被 check-out)
  engines: string[];         // 池里出现过的引擎(筛选下拉用)
  quarantined_total?: number;             // 掉线(隔离)总数,需处理
  quarantined_by_engine?: Record<string, number>;
  page: number;
  page_size: number;
}

async function request<T>(
  method: string, path: string, token: string, body?: unknown,
): Promise<T> {
  const init: RequestInit = {
    method,
    headers: localizedHeaders({
      Authorization: `Bearer ${token}`,
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
    }),
  };
  if (body !== undefined) init.body = JSON.stringify(body);
  const resp = await fetch(`${API_BASE}/ai-telemetry${path}`, init);
  if (!resp.ok) {
    const msg = await readApiError(resp, `Request ${method} ${path} failed`);
    throw new Error(msg);
  }
  if (resp.status === 204) return undefined as T;
  return resp.json() as Promise<T>;
}

// 对外网关:租户 / 调用流水(运营管理页用)
export interface GatewayTenant {
  id: number; name: string; status: string; tier: string;
  engines: string[]; daily_quota_default: number; daily_quota: Record<string, number>;
  credit_balance: number; active_keys: number; calls_today: number;
  billable_total: number; credits_spent_total: number; created_at: string | null;
}
export interface GatewayJob {
  id: number; tenant_id: string | null; engine: string; query: string;
  status: string; error: string | null; created_at: string | null; finished_at: string | null;
  answer?: string; citations?: { url?: string; domain?: string; title?: string }[];
  source_url?: string | null; video_url?: string | null;
}

// 种子扩展入参 — suggestQueries(普通) 与 suggestQueriesStream(SSE) 共用,避免两处漂移。
export interface SuggestQueryArgs {
  seed: string; count: number;
  target?: string; aliases?: string[]; industry?: string;
  // 主体类型 — 驱动扩展词风格(service_tool / manufacturer / brand_owner / other / '')
  entity_type?: string;
  // 用户在 profile 里填的服务地域;非空时 prompt 把地点维度锁在该地域。
  service_geo?: string;
  // 4 维场景;不传默认全 4 维 fan-out。
  scenes?: SceneType[];
  // 每场景产出条数(每维 ≤50,4 维合 ≤200)。
  countPerScene?: number;
  // 画像字段(intent / brand 场景注入,search / qa 忽略)。
  profile_cases?: string[];
  core_credentials?: string[];
  brand_diff_tags?: string[];
  core_service_overview?: string;
}

// 普通版和流式版发同一套 body,后端 _parse_suggest_args 统一解析。
function buildSuggestBody(args: SuggestQueryArgs): Record<string, unknown> {
  return {
    seed: args.seed,
    count: args.count,
    // 后端 v2 优先用 count_per_scene;否则用 count/4 兜底,保 老调用方语义稳定。
    ...(args.countPerScene ? { count_per_scene: args.countPerScene } : {}),
    ...(args.scenes ? { scenes: args.scenes } : {}),
    target: args.target || '',
    aliases: args.aliases || [],
    industry: args.industry || '',
    entity_type: args.entity_type || '',
    service_geo: args.service_geo || '',
    profile_cases: args.profile_cases || [],
    core_credentials: args.core_credentials || [],
    brand_diff_tags: args.brand_diff_tags || [],
    core_service_overview: args.core_service_overview || '',
  };
}

export const aiTelemetryApi = {
  async listTopics(token: string): Promise<Topic[]> {
    if (isMockMode()) return Promise.resolve([..._mockTopics]);
    return request<Topic[]>('GET', '/topics', token);
  },

  // 单条主题元信息 — owner 自取;admin 可取任意主题(品牌增长面板按 ?topic= 解析非自有主题用)。
  async getTopic(id: number, token: string): Promise<Topic> {
    if (isMockMode()) {
      const t = _mockTopics.find(t => t.id === id);
      if (!t) throw new Error('topic not found');
      return Promise.resolve(t);
    }
    return request<Topic>('GET', `/topics/${id}`, token);
  },

  async createTopic(payload: TopicPayload, token: string): Promise<Topic> {
    if (isMockMode()) {
      const t: Topic = {
        id: _mockSeq++, ...payload,
        last_run_at: null, last_run_status: null,
      };
      _mockTopics.push(t);
      return Promise.resolve(t);
    }
    return request<Topic>('POST', '/topics', token, payload);
  },

  // Step1「下一步」即落库:只存品牌资料 + 基础字段,queries/engines 可空,后端建 draft。
  // 返回带 id 的 topic,供后续 step 增量更新,避免拖到最后才一次性保存丢数据。
  async createDraftTopic(payload: TopicDraftPayload, token: string): Promise<Topic> {
    if (isMockMode()) {
      const t: Topic = {
        id: _mockSeq++,
        name: payload.name, target: payload.target,
        target_aliases: payload.target_aliases, industry: payload.industry,
        queries: [], engines: payload.engines, enabled: payload.enabled,
        profile: payload.profile,
        last_run_at: null, last_run_status: null,
      } as Topic;
      _mockTopics.push(t);
      return Promise.resolve(t);
    }
    return request<Topic>('POST', '/topics/draft', token, payload);
  },

  async updateTopic(id: number, payload: TopicPayload, token: string): Promise<Topic> {
    if (isMockMode()) {
      const i = _mockTopics.findIndex(t => t.id === id);
      if (i >= 0) _mockTopics[i] = { ..._mockTopics[i], ...payload };
      return Promise.resolve(_mockTopics[i]);
    }
    return request<Topic>('PUT', `/topics/${id}`, token, payload);
  },

  async deleteTopic(id: number, token: string): Promise<void> {
    if (isMockMode()) {
      const i = _mockTopics.findIndex(t => t.id === id);
      if (i >= 0) _mockTopics.splice(i, 1);
      return Promise.resolve();
    }
    return request<void>('DELETE', `/topics/${id}`, token);
  },

  // Phase C — 甲方追加种子提示词(待审核)
  async submitSeedPrompt(topicId: number, text: string, token: string): Promise<Topic> {
    return request<Topic>('POST', `/topics/${topicId}/seed-prompts`, token, { text });
  },

  async suggestQueries(
    args: SuggestQueryArgs,
    token: string,
  ): Promise<{ seed: string; queries: QueryCandidate[]; clusters: ClusterMeta[] }> {
    if (isMockMode()) {
      // mock: 拼出 args.count 条假候选 + 5 簇 + 递减分数,够前端 picker 调试
      const stems = ['是什么', '怎么样', '推荐', '对比', '替代方案', '价格', '评价', '案例', '使用场景', '行业应用'];
      const scenesArr: SceneType[] = ['search', 'qa', 'intent', 'brand'];
      const out: QueryCandidate[] = [];
      const clusterLabels = ['认知与定义', '对比与差异', '价格与费用', '案例与口碑', '使用与场景'];
      for (let i = 0; out.length < args.count; i++) {
        out.push({
          text: `${args.seed} ${stems[i % stems.length]} ${Math.floor(i / stems.length) + 1}`,
          score: Math.max(20, 90 - i),
          sources: i % 4 === 0 ? ['suggest:baidu'] : ['llm:deepseek'],
          cluster_id: i % 5,
          scene: scenesArr[i % scenesArr.length],
        });
      }
      const clusters: ClusterMeta[] = clusterLabels.map((l, i) => ({
        cluster_id: i,
        label: l,
        size: out.filter(q => q.cluster_id === i).length,
        medoid_index: out.findIndex(q => q.cluster_id === i),
      }));
      return Promise.resolve({ seed: args.seed, queries: out, clusters });
    }
    return request<{ seed: string; queries: QueryCandidate[]; clusters: ClusterMeta[] }>(
      'POST', '/suggest-queries', token, buildSuggestBody(args),
    );
  },

  // SSE 流式扩展:每个场景生成完就回调一次,前端边收边渲染,不必等整包。
  // onScene(scene, queries):某场景的候选到了(可能为空,带 error 时表示该场景失败)。
  // 整个流走完才 resolve;中途异常 reject。提示词/解析与 suggestQueries 完全一致。
  async suggestQueriesStream(
    args: SuggestQueryArgs,
    token: string,
    onScene: (scene: SceneType, queries: QueryCandidate[], error?: string | null) => void,
  ): Promise<void> {
    if (isMockMode()) {
      // mock:直接复用普通版结果,按 scene 分组逐组回调,模拟流式。
      const { queries } = await this.suggestQueries(args, token);
      for (const sc of (['search', 'qa', 'intent', 'brand'] as SceneType[])) {
        onScene(sc, queries.filter(q => q.scene === sc));
      }
      return;
    }
    const resp = await fetch(`${API_BASE}/ai-telemetry/suggest-queries/stream`, {
      method: 'POST',
      headers: localizedHeaders({
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      }),
      body: JSON.stringify(buildSuggestBody(args)),
    });
    if (!resp.ok || !resp.body) {
      throw new Error(await readApiError(resp, 'POST /suggest-queries/stream failed'));
    }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      // SSE 以空行(\n\n)分隔事件
      const parts = buf.split('\n\n');
      buf = parts.pop() || '';
      for (const part of parts) {
        const dataLine = part.split('\n').find(l => l.startsWith('data:'));
        if (!dataLine) continue;
        const json = dataLine.slice(5).trim();
        if (!json) continue;
        let obj: { type?: string; scene?: SceneType; queries?: QueryCandidate[]; error?: string | null };
        try { obj = JSON.parse(json); } catch { continue; }
        if (obj.type === 'scene' && obj.scene) {
          onScene(obj.scene, Array.isArray(obj.queries) ? obj.queries : [], obj.error ?? null);
        }
      }
    }
  },

  async runNow(payload: TopicPayload, token: string): Promise<RunNowResult[]> {
    if (isMockMode()) {
      return Promise.resolve(
        payload.engines.flatMap(engine =>
          payload.queries.map(query => ({
            engine,
            query,
            answer: `[mock] ${engine} 关于 "${query}" 的回答...`,
            citations: [{ url: 'https://example.com', domain: 'example.com', title: 'Example' }],
            error: null,
          }))
        )
      );
    }
    return request<RunNowResult[]>('POST', '/topics/run-now', token, payload);
  },

  async triggerRun(topicId: number, token: string): Promise<{ status: string; topic_id: number }> {
    if (isMockMode()) return Promise.resolve({ status: 'started', topic_id: topicId });
    return request('POST', `/topics/${topicId}/run`, token);
  },

  async listRuns(topicId: number, token: string, limit = 20): Promise<RunSummary[]> {
    if (isMockMode()) return Promise.resolve([]);
    return request<RunSummary[]>('GET', `/topics/${topicId}/runs?limit=${limit}`, token);
  },

  async listResponses(runId: number, token: string): Promise<ResponseRow[]> {
    if (isMockMode()) return Promise.resolve([]);
    return request<ResponseRow[]>('GET', `/runs/${runId}/responses`, token);
  },

  async getOverview(topicId: number, periodDays: number, token: string): Promise<Overview> {
    if (isMockMode()) {
      const trend = Array.from({ length: periodDays }, (_, i) => ({
        date: new Date(Date.now() - (periodDays - 1 - i) * 86400000).toISOString().slice(0, 10),
        values: { deepseek: Math.floor(Math.random() * 10), qwen: Math.floor(Math.random() * 8) },
      }));
      return Promise.resolve({
        topic_id: topicId, period_days: periodDays,
        brand_keywords: ['mock'],
        visibility: { value: 78, delta_pct: 12, sparkline: trend.map(t => t.values.deepseek || 0) },
        citations: { value: 1248, delta_pct: 16, sparkline: trend.map(t => t.values.deepseek || 0) },
        growth: { value: 32, delta_pct: null, sparkline: [] },
        engines_covered: { value: 5, delta_pct: null, sparkline: [] },
        engines_total: 10,
        trend,
        engines: ['deepseek', 'qwen'],
        top_domains: [
          { domain: 'zhihu.com', count: 42, pct: 18 },
          { domain: 'baike.baidu.com', count: 28, pct: 12 },
        ],
        owned_split: { owned: 24, other: 200, owned_pct: 10.7, delta_pct: 2.1 },
        engine_domain_matrix: { deepseek: { 'zhihu.com': 8 }, qwen: { 'baike.baidu.com': 5 } },
        engine_factor_matrix: {
          deepseek: { list_mention: 12, reviews: 5, social: 8, other: 6 },
          qwen: { list_mention: 7, directory: 4, social: 5, other: 3 },
        },
      });
    }
    return request<Overview>('GET', `/topics/${topicId}/overview?period=${periodDays}`, token);
  },

  // ── v1.3 SAIV / 竞品份额 / 优选率 / 命中位置 ────────
  async getShareOfVoice(
    topicId: number, periodDays: number, token: string,
  ): Promise<ShareOfVoice> {
    if (isMockMode()) return Promise.resolve(_mockSoV(topicId, periodDays));
    return request<ShareOfVoice>('GET', `/topics/${topicId}/share-of-voice?period=${periodDays}`, token);
  },

  // 按 picker 端聚出的 intent cluster 把本期 response 分组聚合
  async getIntentBreakdown(
    topicId: number, periodDays: number, token: string,
  ): Promise<IntentBreakdown> {
    if (isMockMode()) {
      const mk = (cid: number, label: string, qc: number, rc: number, mc: number, cc: number) => ({
        cluster_id: cid, label, query_count: qc, response_count: rc,
        mention_count: mc,
        mention_rate: rc ? Math.round(mc / rc * 1000) / 1000 : 0,
        citation_count: cc,
      });
      return Promise.resolve({
        topic_id: topicId, period_days: periodDays, brand_keywords: ['mock'],
        clusters: [
          mk(0, '认知与定义', 12, 84, 31, 96),
          mk(1, '对比与差异', 10, 70, 18, 64),
          mk(2, '价格与费用', 8, 56, 38, 72),
          mk(3, '案例与口碑', 6, 42, 25, 50),
          mk(4, '使用与场景', 4, 28, 9, 22),
        ],
        uncategorized: mk(-1, 'uncategorized', 0, 0, 0, 0),
      });
    }
    return request<IntentBreakdown>(
      'GET', `/topics/${topicId}/intent-breakdown?period=${periodDays}`, token,
    );
  },

  // ── v1 引用追踪 ──────────────────────────
  async getTrackingMatrix(topicId: number, token: string): Promise<TrackingMatrix> {
    if (isMockMode()) return Promise.resolve(_mockMatrix(topicId));
    return request<TrackingMatrix>('GET', `/topics/${topicId}/tracking-matrix`, token);
  },

  async getGrowthReport(topicId: number, token: string): Promise<GrowthReport> {
    return request<GrowthReport>('GET', `/topics/${topicId}/growth-report`, token);
  },

  async getCellDrawer(
    topicId: number, query: string, engine: EngineId, token: string,
  ): Promise<CellDrawer> {
    if (isMockMode()) return Promise.resolve(_mockDrawer(topicId, query, engine));
    const qs = new URLSearchParams({ query, engine }).toString();
    return request<CellDrawer>('GET', `/topics/${topicId}/cells/drawer?${qs}`, token);
  },

  // ── v1.1 LLM 诊断 ─────────────────────────
  async fetchCellInsight(
    topicId: number, query: string, engine: EngineId, token: string, force = false,
  ): Promise<CellInsight> {
    if (isMockMode()) return Promise.resolve(_mockInsight(topicId, query, engine));
    const qs = new URLSearchParams({ query, engine, force: String(force) }).toString();
    return request<CellInsight>('POST', `/topics/${topicId}/cells/insight?${qs}`, token);
  },

  async postCellInsightFeedback(
    insightId: number, feedback: 'helpful' | 'not_helpful' | 'wrong', token: string,
  ): Promise<void> {
    if (isMockMode()) return Promise.resolve();
    return request<void>('POST', `/cell-insights/${insightId}/feedback`, token, { feedback });
  },

  // ── v1.2 周报 ─────────────────────────────
  async listBriefings(topicId: number, token: string, limit = 12): Promise<Briefing[]> {
    if (isMockMode()) return Promise.resolve([_mockBriefing(topicId)]);
    return request<Briefing[]>('GET', `/topics/${topicId}/briefings?limit=${limit}`, token);
  },

  async getBriefing(briefingId: number, token: string): Promise<Briefing> {
    if (isMockMode()) return Promise.resolve(_mockBriefing(0, briefingId));
    return request<Briefing>('GET', `/briefings/${briefingId}`, token);
  },

  async triggerBriefing(topicId: number, token: string): Promise<Briefing> {
    if (isMockMode()) return Promise.resolve(_mockBriefing(topicId));
    return request<Briefing>('POST', `/topics/${topicId}/briefings/generate`, token);
  },

  async postBriefingFeedback(briefingId: number, score: number, token: string): Promise<void> {
    if (isMockMode()) return Promise.resolve();
    return request<void>('POST', `/briefings/${briefingId}/feedback`, token, { score });
  },

  // ── 品牌增长页 — Phase 1 后端聚合的真值接口 ─────────────
  async getPositionBreakdown(
    topicId: number, periodDays: number, token: string,
  ): Promise<PositionBreakdownResp> {
    return request<PositionBreakdownResp>(
      'GET', `/topics/${topicId}/position-breakdown?period=${periodDays}`, token,
    );
  },

  async getIndustryBenchmark(
    industry: string, periodDays: number, token: string,
  ): Promise<IndustryBenchmark> {
    const qs = new URLSearchParams({ industry, period: String(periodDays) }).toString();
    return request<IndustryBenchmark>('GET', `/benchmarks/industry?${qs}`, token);
  },

  async getCompetitorSubstitutions(
    topicId: number, periodDays: number, token: string,
    opts: { competitor?: string; limit?: number } = {},
  ): Promise<CompetitorSubstitutionResp> {
    const params = new URLSearchParams({ period: String(periodDays) });
    if (opts.competitor) params.set('competitor', opts.competitor);
    if (opts.limit) params.set('limit', String(opts.limit));
    return request<CompetitorSubstitutionResp>(
      'GET', `/topics/${topicId}/competitor-substitutions?${params.toString()}`, token,
    );
  },

  // ── admin 跨用户管理 ─────────────────────────────────
  async adminListAccounts(token: string): Promise<AdminAccount[]> {
    return request<AdminAccount[]>('GET', '/admin/accounts', token);
  },

  // ── 调度中心 / Worker 管理 ───────────────────────────
  async adminListWorkers(token: string): Promise<BrowserWorker[]> {
    return request<BrowserWorker[]>('GET', '/admin/workers', token);
  },
  async adminWorkersQueueStats(token: string): Promise<WorkerQueueStats> {
    return request<WorkerQueueStats>('GET', '/admin/workers-queue-stats', token);
  },
  async adminWorkerAction(
    workerUid: string, action: 'enable' | 'disable' | 'drain', token: string,
  ): Promise<{ ok: boolean; status: string }> {
    return request('POST', `/admin/workers/${workerUid}/${action}`, token);
  },
  // 添加账号·密码授权:server 端自动登录(走代理)抓登录态入池
  async adminAuthorizeAccount(
    token: string, engine: string, identifier: string, password: string,
  ): Promise<{ ok: boolean; error?: string | null; account_handle?: string; uploaded?: boolean }> {
    return request('POST', '/admin/authorize-account', token, { engine, identifier, password });
  },

  // 扫码协助授权:开始(返回二维码)+ 轮询(登录成功入池)
  async adminAuthorizeQrStart(
    token: string, engine: string,
  ): Promise<{ session_id?: string; qr_image?: string; error?: string | null }> {
    return request('POST', '/admin/authorize-qr/start', token, { engine });
  },
  async adminAuthorizeQrPoll(
    token: string, sessionId: string,
  ): Promise<{ status: string; qr_image?: string; uploaded?: boolean; error?: string | null }> {
    return request('POST', '/admin/authorize-qr/poll', token, { session_id: sessionId });
  },

  async adminListEngineSessions(
    token: string, page = 1, pageSize = 20, engine = '', status = '',
  ): Promise<EngineSessionPage> {
    const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
    if (engine) params.set('engine', engine);
    if (status) params.set('status', status);
    return request<EngineSessionPage>('GET', `/admin/engine-sessions?${params}`, token);
  },

  // Worker 管理:引擎自愈 — 探针+LLM 提议选择器(只提议)
  async adminHealEngine(
    token: string, engine: string,
  ): Promise<{
    engine: string; probe_error: string | null; proposal: SelectorProposal | null;
    validation: { ans_len: number; cites: number; error: string | null } | null;
    validated: boolean; llm_raw: string;
  }> {
    return request('POST', `/admin/heal-engine/${engine}`, token);
  },
  // Worker 管理:把审阅过的提议写入中心配置(全队生效)
  async adminHealEngineApply(
    token: string, engine: string, patch: SelectorProposal,
  ): Promise<{ engine: string; applied: SelectorProposal }> {
    return request('POST', `/admin/heal-engine/${engine}/apply`, token, patch);
  },

  // Worker 管理:引擎健康哨兵最新结果
  async adminEngineHealth(
    token: string,
  ): Promise<{ checked_at: string | null; engines: EngineHealth[] }> {
    return request('GET', '/admin/engine-health', token);
  },

  // Worker 管理:按出口 IP 聚合(每 IP 挂几个号/今日用量/密度)
  async adminEngineSessionsByIp(
    token: string,
  ): Promise<{ groups: EngineIpGroup[]; ip_count: number }> {
    return request('GET', '/admin/engine-sessions/by-ip', token);
  },

  // Worker 管理:启停账号 / 改单账号日上限(-1=清除覆盖) / 改优先级
  async adminPatchEngineSession(
    token: string, sessionId: number,
    patch: { disabled?: boolean; daily_cap?: number; priority?: number },
  ): Promise<{ id: number; daily_cap: number | null; priority: number; disabled: boolean }> {
    return request('PATCH', `/admin/engine-sessions/${sessionId}`, token, patch);
  },

  // ── 对外网关运营管理 ─────────────────────────────────
  async adminGatewayTenants(token: string): Promise<{ tenants: GatewayTenant[] }> {
    return request('GET', '/admin/gateway/tenants', token);
  },
  async adminGatewayCreateTenant(
    payload: { name: string; tier?: string; engines?: string[]; daily_quota_default?: number; daily_quota?: Record<string, number> },
    token: string,
  ): Promise<{ tenant_id: number; key_id: number; api_key: string }> {
    return request('POST', '/admin/gateway/tenants', token, payload);
  },
  async adminGatewayUpdateTenant(
    tenantId: number,
    payload: { status?: string; tier?: string; engines?: string[]; daily_quota_default?: number; daily_quota?: Record<string, number> },
    token: string,
  ): Promise<{ ok: boolean }> {
    return request('PATCH', `/admin/gateway/tenants/${tenantId}`, token, payload);
  },
  async adminGatewayTopUp(tenantId: number, amount: number, token: string): Promise<{ credit_balance: number }> {
    return request('POST', `/admin/gateway/tenants/${tenantId}/credits`, token, { amount });
  },
  async adminGatewayReissueKey(tenantId: number, token: string): Promise<{ api_key: string }> {
    return request('POST', `/admin/gateway/tenants/${tenantId}/keys`, token);
  },
  async adminGatewayRevokeKey(keyId: number, token: string): Promise<{ ok: boolean }> {
    return request('POST', `/admin/gateway/keys/${keyId}/revoke`, token);
  },
  async adminGatewayJobs(token: string, tenantId?: number, limit = 50): Promise<{ jobs: GatewayJob[] }> {
    const q = tenantId != null ? `?tenant_id=${tenantId}&limit=${limit}` : `?limit=${limit}`;
    return request('GET', `/admin/gateway/jobs${q}`, token);
  },
  async adminListUserTopics(userId: number, token: string): Promise<Topic[]> {
    return request<Topic[]>('GET', `/admin/users/${userId}/topics`, token);
  },

  // admin 替指定 user 直接创建主题(跳过审核,落库即 approved)
  async adminCreateTopicForUser(
    userId: number, payload: TopicPayload, token: string,
  ): Promise<Topic> {
    return request<Topic>('POST', `/admin/users/${userId}/topics`, token, payload);
  },

  // admin 取单条 run 元信息
  async adminGetRun(runId: number, token: string): Promise<AdminRun> {
    return request<AdminRun>('GET', `/admin/runs/${runId}`, token);
  },

  // admin 跨用户跑批总览
  async adminListRuns(
    token: string,
    opts: { day?: string; userId?: number; topicId?: number; status?: string; limit?: number; offset?: number } = {},
  ): Promise<AdminRun[]> {
    const params = new URLSearchParams();
    if (opts.day) params.set('day', opts.day);
    if (opts.userId !== undefined) params.set('user_id', String(opts.userId));
    if (opts.topicId !== undefined) params.set('topic_id', String(opts.topicId));
    if (opts.status) params.set('status', opts.status);
    if (opts.limit !== undefined) params.set('limit', String(opts.limit));
    if (opts.offset !== undefined) params.set('offset', String(opts.offset));
    const qs = params.toString();
    const suffix = qs ? `?${qs}` : '';
    return request<AdminRun[]>('GET', `/admin/runs${suffix}`, token);
  },

  async listTopicResponses(
    topicId: number, token: string,
    opts: { engine?: string; domain?: string; query?: string; period?: number; limit?: number } = {},
  ): Promise<ResponseRow[]> {
    const params = new URLSearchParams();
    if (opts.engine) params.set('engine', opts.engine);
    if (opts.domain) params.set('domain', opts.domain);
    if (opts.query) params.set('query', opts.query);
    if (opts.period) params.set('period', String(opts.period));
    if (opts.limit) params.set('limit', String(opts.limit));
    const qs = params.toString();
    const suffix = qs ? `?${qs}` : '';
    return request<ResponseRow[]>('GET', `/topics/${topicId}/responses${suffix}`, token);
  },
};

// ── mock helpers ────────────────────────────────────────────
function _mockMatrix(topicId: number): TrackingMatrix {
  const queries = ['Q1 跨境TMT投资律师', 'Q2 私募股权律师', 'Q3 资本市场律师'];
  const engines: EngineId[] = ['wenxin', 'doubao', 'yuanbao'];
  const now = new Date();
  const cells: QueryHitCell[] = [];
  for (const q of queries) {
    for (const e of engines) {
      const hit = q === queries[0] && (e === 'wenxin' || e === 'doubao');
      cells.push({
        query: q, engine: e,
        status: hit ? 'done' : 'done',
        first_hit_at: hit ? new Date(now.getTime() - 86400000).toISOString() : null,
        first_hit_response_id: hit ? 1 : null,
        last_checked_at: now.toISOString(),
        total_runs: 3,
        total_hits: hit ? 2 : 0,
      });
    }
  }
  return {
    topic_id: topicId,
    target: '金诚同达律所', target_aliases: ['KWM', 'King & Wood'],
    queries, engines,
    started_at: new Date(now.getTime() - 5 * 86400000).toISOString(),
    cells,
    timeline: engines.map(e => ({
      engine: e,
      first_hit_at: e === 'wenxin' || e === 'doubao'
        ? new Date(now.getTime() - 86400000).toISOString() : null,
      first_hit_query: e === 'wenxin' || e === 'doubao' ? queries[0] : null,
      days_after_start: e === 'wenxin' ? 3 : (e === 'doubao' ? 3 : null),
    })),
    total_runs: 3,
    total_cells: queries.length * engines.length,
    hit_cells: 2,
    hit_cells_pct: Math.round(2 / (queries.length * engines.length) * 1000) / 10,
  };
}

function _mockDrawer(_topicId: number, query: string, engine: EngineId): CellDrawer {
  return {
    cell: {
      query, engine, status: 'done',
      first_hit_at: new Date(Date.now() - 86400000).toISOString(),
      first_hit_response_id: 1, last_checked_at: new Date().toISOString(),
      total_runs: 3, total_hits: 2,
    },
    evidence: [
      {
        response_id: 1, run_id: 1, created_at: new Date(Date.now() - 86400000).toISOString(),
        engine, query, hit: true,
        hit_excerpt: '…推荐关注 [金诚同达律所],在 TMT 行业有丰富积累…',
        source_url: 'https://yiyan.baidu.com/chat/abc',
        answer: 'mock answer body',
        citations: [{ url: 'https://gov.cn', domain: 'gov.cn', title: '示例' }],
      },
    ],
    insight: null,
  };
}

function _mockInsight(topicId: number, query: string, engine: EngineId): CellInsight {
  return {
    id: 1, topic_id: topicId, query, engine,
    window_start: new Date(Date.now() - 7 * 86400000).toISOString(),
    window_end: new Date().toISOString(),
    verdict: 'hit_unstable',
    summary: '近 7 天 3 次跑批命中 2 次,引擎倾向 listicle 答题套路',
    competitors_top3: [
      { name: '君合律师事务所', count: 3, snippet: '…在跨境投资领域推荐君合…' },
      { name: '中伦律师事务所', count: 2, snippet: '…中伦律师事务所的 TMT 团队…' },
    ],
    recommendations: [
      { priority: 'P0', title: '加 TMT 案例长文', action: '30 天内 jincheng.com 加 3 篇 TMT 海外并购深度案例', why: '该引擎对深度报告类内容权重高' },
      { priority: 'P1', title: '优化 PR 投放', action: '把"金诚同达 TMT 团队"投到 lawinfochina.com', why: '该域名在 citations 高频出现' },
    ],
    answer_format: 'listicle',
    citation_domains: ['gov.cn', 'lawinfochina.com'],
    evidence_response_ids: [1, 2, 3],
    llm_model: 'mock', prompt_version: 'cell_v1',
    generated_at: new Date().toISOString(),
    feedback: null,
  };
}

function _mockSoV(topicId: number, periodDays: number): ShareOfVoice {
  return {
    topic_id: topicId, target: '世纪互联', period_days: periodDays,
    brand_count: 23,
    competitors_count_total: 41,
    saiv_pct: 35.9,
    competitors: [
      { name: '万国数据', count: 18, pct: 28.1 },
      { name: '世纪华通', count: 12, pct: 18.8 },
      { name: '光环新网', count: 6, pct: 9.4 },
      { name: '宝信软件', count: 3, pct: 4.7 },
      { name: '数据港', count: 2, pct: 3.1 },
    ],
    position_dist: { lead: 12, body: 8, tail: 3, unknown: 0 },
    optimal_rate_pct: 82.9,
    total_runs: 7,
    sample_size: 35,
  };
}

function _mockBriefing(topicId: number, id = 1): Briefing {
  return {
    id, topic_id: topicId,
    period_start: new Date(Date.now() - 7 * 86400000).toISOString(),
    period_end: new Date().toISOString(),
    body_md: '## 本周亮点\n- 文心一言 Q1 完成首次命中\n\n## 下周优先行动\n- 加 TMT 案例长文',
    kpi_snapshot: { hit_rate: 22.2, ttfm_days: 3, new_hits_count: 2, lost_hits_count: 0 },
    top_actions: [
      { priority: 'P0', title: 'TMT 案例库扩容', why: '文心引擎偏好深度报告', how: '30 天内加 3 篇' },
    ],
    delivered_email_at: null, feedback_score: null,
    llm_model: 'mock', prompt_version: 'briefing_v1',
    generated_at: new Date().toISOString(),
  };
}
