// Phase D.1 — 用户侧内容 API.
// 后端挂在 /api/content/*,owner-only 校验.

import { localizedHeaders, readApiError } from './apiError';

const API_BASE = (import.meta.env.VITE_API_URL as string) || '/api';

export type DocStatus = 'draft' | 'pending_review' | 'approved' | 'rejected' | 'published';
export type DocSource = 'ai' | 'user';

export interface PublishTarget {
  platform: string;
  media: string;
  url?: string;
  marked_at?: string;
  marked_by?: number;
}

export interface ContentDoc {
  id: number;
  topic_id: number;
  execution_plan_id?: number | null;
  created_at: string;
  source_query_text: string;
  title: string;
  body_markdown: string;
  summary: string;
  llm_model: string;
  generation_error?: string | null;
  status: DocStatus;
  selected_for_review: boolean;
  review_decision_at?: string | null;
  reviewer_id?: number | null;
  reject_reason?: string | null;
  publish_targets: PublishTarget[];
  source: DocSource;
  // URL 级 ROI 命中:{engine: [response_id]} — 空对象表示没被 AI 引用过
  cited_by: Record<string, number[]>;
}

export interface ContentStats {
  draft: number;
  pending_review: number;
  approved: number;
  rejected: number;
  published: number;
  total: number;
  ai_count: number;
  user_count: number;
}

export interface UserDocSubmitPayload {
  title: string;
  body_markdown: string;
  summary?: string;
  source_query_text?: string;
  submit_for_review?: boolean;
}

export interface UserDocUpdatePayload {
  title?: string;
  body_markdown?: string;
  summary?: string;
  source_query_text?: string;
}

export interface AutoGenerateConfig {
  enabled: boolean;
  time: string;       // "HH:MM"
  count: number;
  publish_enabled?: boolean;   // 按 publish_date 自动发布开关;不传则后端不改
}

export interface AutoGenerateState extends AutoGenerateConfig {
  auto_generate_last_run_at?: string | null;
  auto_publish_enabled?: boolean;
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
  const resp = await fetch(`${API_BASE}/content${path}`, init);
  if (!resp.ok) {
    const msg = await readApiError(resp, `Request ${method} ${path} failed`);
    throw new Error(msg);
  }
  if (resp.status === 204) return undefined as T;
  return resp.json() as Promise<T>;
}

export const contentApi = {
  async listDocs(
    topicId: number,
    opts: {
      status?: DocStatus | 'to_review' | 'all';
      source?: DocSource | 'all';
      query_hit?: 'hit' | 'miss';   // 战报页 ROI 筛选
    },
    token: string,
  ): Promise<ContentDoc[]> {
    const qs = new URLSearchParams();
    if (opts.status && opts.status !== 'all') qs.set('status', opts.status);
    if (opts.source && opts.source !== 'all') qs.set('source', opts.source);
    if (opts.query_hit) qs.set('query_hit', opts.query_hit);
    const suffix = qs.toString() ? `?${qs.toString()}` : '';
    return request('GET', `/topics/${topicId}/docs${suffix}`, token);
  },
  async stats(topicId: number, token: string): Promise<ContentStats> {
    return request('GET', `/topics/${topicId}/stats`, token);
  },
  async getDoc(docId: number, token: string): Promise<ContentDoc> {
    return request('GET', `/docs/${docId}`, token);
  },
  async submitMyDoc(
    topicId: number, payload: UserDocSubmitPayload, token: string,
  ): Promise<ContentDoc> {
    return request('POST', `/topics/${topicId}/docs`, token, payload);
  },
  async updateMyDoc(
    docId: number, payload: UserDocUpdatePayload, token: string,
  ): Promise<ContentDoc> {
    return request('PATCH', `/docs/${docId}`, token, payload);
  },
  async submitForReview(docId: number, token: string): Promise<ContentDoc> {
    return request('POST', `/docs/${docId}/submit-review`, token);
  },
  async approveMyDoc(docId: number, token: string): Promise<ContentDoc> {
    return request('POST', `/docs/${docId}/approve`, token);
  },
  async rejectMyDoc(docId: number, reason: string, token: string): Promise<ContentDoc> {
    return request('POST', `/docs/${docId}/reject`, token, { reason });
  },
  async configureAutoGenerate(
    topicId: number, payload: AutoGenerateConfig, token: string,
  ): Promise<AutoGenerateState> {
    return request('PATCH', `/topics/${topicId}/auto-generate`, token, payload);
  },
  async runNow(topicId: number, token: string): Promise<{ queued: number; topic_id: number }> {
    return request('POST', `/topics/${topicId}/run-now`, token);
  },
};
