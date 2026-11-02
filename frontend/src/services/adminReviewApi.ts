// Admin 审核 API — Phase C 单条审核 + Phase D 整张申请审核.
// 端点都挂在 /api/admin/review,后端用 require_admin 守门;调用方需带 admin token.

import { localizedHeaders, readApiError } from './apiError';
import type { BrandProfile, SubmissionStatus, Topic } from './aiTelemetryApi';

const API_BASE = (import.meta.env.VITE_API_URL as string) || '/api';

async function request<T>(
  method: string, path: string, token: string, body?: unknown,
  base: string = '/admin/review',
): Promise<T> {
  const init: RequestInit = {
    method,
    headers: localizedHeaders({
      Authorization: `Bearer ${token}`,
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
    }),
  };
  if (body !== undefined) init.body = JSON.stringify(body);
  const resp = await fetch(`${API_BASE}${base}${path}`, init);
  if (!resp.ok) {
    const msg = await readApiError(resp, `Request ${method} ${path} failed`);
    throw new Error(msg);
  }
  if (resp.status === 204) return undefined as T;
  return resp.json() as Promise<T>;
}

// ── Phase D — 整张申请审核 ───────────────────────────

// 项目进度 stage chip 的 5 态,值域与后端 admin_review.py::StageState 对齐.
export type StageState = 'done' | 'running' | 'pending' | 'blocked' | 'idle';

export interface TopicReviewListItem {
  topic_id: number;
  topic_name: string;
  user_id: number;
  user_email: string;
  submission_status: SubmissionStatus;
  submitted_at?: string | null;
  approved_at?: string | null;
  rejected_at?: string | null;
  profile_name: string;
  company_short_name: string;
  industry: string;
  seed_count: number;
  selected_query_count: number;
  version?: number;
  // 项目进度 stage 3-6 状态;未升级的后端会全是 'idle'(Pydantic 默认值),不影响兼容
  diagnose_status: StageState;
  plan_status: StageState;
  content_status: StageState;
  insight_status: StageState;
}

export interface TopicChangelogEntry {
  at: string;
  actor_id?: number | null;
  actor_role: 'user' | 'admin' | 'system';
  field: string;
  before?: string | null;
  after?: string | null;
  note?: string | null;
  version?: number | null;
}

export interface ExpansionLogEntry {
  at: string;
  seed: string;
  model: string;
  expanded_count: number;
  raw_excerpt: string;
}

export interface TopicReviewDetail extends Topic {
  user_id: number;
  user_email: string;
  topic_changelog: TopicChangelogEntry[];
  expansion_log: ExpansionLogEntry[];
}

export interface AdminPatchTopicPayload {
  profile?: BrandProfile;
  seed_prompts?: string[];
  selected_query_texts?: string[];
  add_queries?: string[];
  note?: string;
}

export interface TopicProgressCell {
  query: string;
  engine: string;
  status: 'pending' | 'running' | 'done';
  hit?: boolean | null;
  last_checked_at?: string | null;
}

export interface PublishPlanItem {
  // 持久化字段(PUT 时也送回去)
  id: string;
  seq: number;
  publish_date: string;
  // seed-based 新流程:seed 非空,query 留空;legacy:seed 为 null,query 非空.
  seed?: string | null;
  query: string;
  // 2026-06-11 — 多选监测 query;生成正文时要求自然覆盖这组问题。与 query 单值并存,queries 优先。
  queries?: string[];
  template_id?: number | null;
  platform?: string | null;
  note?: string | null;
  // 2026-05-28 — 单行 combo override(空 → 用画像默认)
  creation_directions?: string[];
  copywriting_types?: string[];
  // 后端实时聚合 / 联表算出来的展示字段
  day: number;                          // 老字段,= seq;留着兼容
  coverage_pct: number;
  priority: 'high' | 'med' | 'low';
  doc_id?: number | null;
  doc_status?: 'draft' | 'pending_review' | 'approved' | 'rejected' | 'published' | null;
  template_name?: string | null;
  template_kind?: string | null;
  suggested_platforms: string[];
}

export interface PlanItemDraft {
  id?: string | null;                   // 新行可不传 id,后端补
  seq: number;
  publish_date: string;
  seed?: string | null;                 // seed-based 新行非空;legacy 留空 (二选一)
  query: string;                        // legacy 行 ∈ monitored;seed-based 行允许 ""
  queries?: string[];                   // 2026-06-11 — 多选监测 query,每条必 ∈ monitored
  template_id: number;
  platform: string;
  note?: string | null;
  // 2026-05-28 — 单行 combo override(空 → 用画像默认)
  creation_directions?: string[];
  copywriting_types?: string[];
}

// 新流程:draft(运营在编辑发文表)/ confirmed(已确认,文章在跑)/ failed
// 兼容旧值:ready / generating (会被后端逐步替换)
export type ExecutionPlanStatus = 'draft' | 'confirmed' | 'failed' | 'ready' | 'generating';

export interface ExecutionPlan {
  id: number;
  topic_id: number;
  generated_at: string;
  generated_by_reviewer_id?: number | null;
  status: ExecutionPlanStatus;
  error?: string | null;
  overview: Record<string, unknown>;
  topic_changelog: TopicChangelogEntry[];
  expansion_log: ExpansionLogEntry[];
  monitored_queries: string[];
  run_id?: number | null;
  run_status?: 'running' | 'success' | 'failed' | null;
  progress: TopicProgressCell[];
  progress_done: number;
  progress_total: number;
  publishing_plan: PublishPlanItem[];
  confirmed_at?: string | null;
  confirmed_by_id?: number | null;
  last_edited_at?: string | null;
}

// ── v3.3 战略方案 ───────────────────────────

export type SolutionStatus = 'idle' | 'generating' | 'ready' | 'failed';
export type SolutionSeverity = 'high' | 'med' | 'low';

export interface SolutionDiagnosisCheck {
  category: string;
  status: 'PASS' | 'WARN' | 'FAIL' | 'INFO' | string;
  message: string;
  fix?: string | null;
}

export interface SolutionDiagnosisCluster {
  key: string;
  title_zh: string;
  severity: SolutionSeverity;
  summary: string;
  bullets: string[];
  checks: SolutionDiagnosisCheck[];
}

export interface SolutionExecutionLayer {
  key: string;
  title_zh: string;
  hint: string;
  clusters: string[];
}

export interface SolutionDiagnosis {
  url: string;
  score: number;
  grade: string;
  pass_count: number;
  warn_count: number;
  fail_count: number;
  info_count: number;
  clusters: SolutionDiagnosisCluster[];
  execution_layers: SolutionExecutionLayer[];
  all_checks: SolutionDiagnosisCheck[];
}

export interface SolutionSevenStep {
  step: number;
  name: string;
  core_goal: string;
  core_action: string;
  output_value: string;
}

export interface SolutionKeywordTier {
  tier: string;
  title_zh: string;
  description: string;
  keywords: string[];
}

export interface SolutionVisionItem {
  title: string;
  body: string;
}

export interface SolutionQueryItem {
  text: string;
  cluster_id: number;       // -1 表示未分组
  seed: string;             // 这条 Query 当时是从哪个种子提示词扩展出来的(legacy 为空串)
}

export interface SolutionQueryCluster {
  cluster_id: number;
  label: string;
}

export interface SolutionQueriesSnapshot {
  clusters: SolutionQueryCluster[];
  queries: SolutionQueryItem[];
}

export interface TopicStrategicSolution {
  id: number;
  topic_id: number;
  status: SolutionStatus;
  website_url: string;
  error?: string | null;
  generated_by_admin_id?: number | null;
  llm_model: string;
  created_at?: string | null;
  updated_at?: string | null;
  brand_snapshot?: BrandProfile | null;
  diagnosis?: SolutionDiagnosis | null;
  seven_steps: SolutionSevenStep[];
  keyword_tiers: SolutionKeywordTier[];
  vision: SolutionVisionItem[];
  queries_snapshot?: SolutionQueriesSnapshot | null;
}

export const adminReviewApi = {
  // 项目列表 / 详情 / 编辑(admin 视角)
  async listTopicReviews(token: string, status?: SubmissionStatus): Promise<TopicReviewListItem[]> {
    const qs = status ? `?status=${status}` : '';
    return request<TopicReviewListItem[]>('GET', `/topics${qs}`, token);
  },
  async getTopicReview(topicId: number, token: string): Promise<TopicReviewDetail> {
    return request<TopicReviewDetail>('GET', `/topic/${topicId}`, token);
  },
  async patchTopic(topicId: number, payload: AdminPatchTopicPayload, token: string): Promise<TopicReviewDetail> {
    return request<TopicReviewDetail>('PATCH', `/topic/${topicId}`, token, payload);
  },
  async rerunTopic(topicId: number, token: string): Promise<ExecutionPlan> {
    return request<ExecutionPlan>('POST', `/topic/${topicId}/rerun`, token);
  },
  // 去审核新通道:启动项目 / 重新启动.
  // 默认幂等(同 topic 已有 ready/generating plan 直接返回);force=true 才强制重跑.
  async startTopic(topicId: number, token: string, force = false): Promise<ExecutionPlan> {
    const qs = force ? '?force=true' : '';
    return request<ExecutionPlan>(
      'POST', `/${topicId}/start${qs}`, token, undefined, '/admin/topics',
    );
  },
  async getExecutionPlan(topicId: number, token: string): Promise<ExecutionPlan> {
    return request<ExecutionPlan>('GET', `/topic/${topicId}/execution-plan`, token);
  },
  // 重新生成计划书快照(资料/监测问题/日志按 topic 当前状态重建;发文表与状态不动)
  async regenerateExecutionPlan(topicId: number, token: string): Promise<ExecutionPlan> {
    return request<ExecutionPlan>(
      'POST', `/topic/${topicId}/execution-plan/regenerate`, token,
    );
  },
  // 整段替换发文表(draft / confirmed 都允许)
  async updateExecutionPlan(
    topicId: number, items: PlanItemDraft[], token: string,
  ): Promise<ExecutionPlan> {
    return request<ExecutionPlan>(
      'PUT', `/topic/${topicId}/execution-plan`, token, { items },
    );
  },
  // 确认 → 触发文章生成(draft → confirmed;confirmed 时为幂等增量,force=true 全量重生)
  async confirmExecutionPlan(
    topicId: number, token: string, force = false,
  ): Promise<ExecutionPlan> {
    const qs = force ? '?force=true' : '';
    return request<ExecutionPlan>(
      'POST', `/topic/${topicId}/execution-plan/confirm${qs}`, token,
    );
  },
  // 单条重生(覆写已有 doc 的正文)
  async regeneratePlanItem(
    topicId: number, itemId: string, token: string,
  ): Promise<ExecutionPlan> {
    return request<ExecutionPlan>(
      'POST',
      `/topic/${topicId}/execution-plan/items/${encodeURIComponent(itemId)}/regenerate`,
      token,
    );
  },

  // ── v3.3 战略方案 ─────────────────────────
  async getStrategicSolution(topicId: number, token: string): Promise<TopicStrategicSolution> {
    // 后端无记录时返回 status='idle' 的存根,所以这里不需要 null 分支
    return request<TopicStrategicSolution>('GET', `/topic/${topicId}/solution`, token);
  },
  async generateStrategicSolution(
    topicId: number, websiteUrl: string, token: string,
  ): Promise<TopicStrategicSolution> {
    return request<TopicStrategicSolution>(
      'POST', `/topic/${topicId}/solution/generate`, token,
      { website_url: websiteUrl },
    );
  },
};
