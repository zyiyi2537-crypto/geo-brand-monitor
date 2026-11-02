// Admin 内容审核 API — Phase D.
// 端点都挂在 /api/admin/content-review,后端 require_admin 守门.

import { localizedHeaders, readApiError } from './apiError';

const API_BASE = (import.meta.env.VITE_API_URL as string) || '/api';

export type DocStatus = 'draft' | 'pending_review' | 'approved' | 'rejected' | 'published';
export type DocSource = 'ai' | 'user';

export interface TopicWithDocs {
  topic_id: number;
  topic_name: string;
  user_id: number;
  user_email: string;
  doc_count: number;
  draft_count: number;
  pending_review_count: number;
  approved_count: number;
  published_count: number;
  rejected_count: number;
}

export interface PublishTarget {
  platform: string;
  media: string;
  url?: string;
  marked_at?: string;
  marked_by?: number;
}

export interface GeneratedDoc {
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
  // 2026-05-28 — 多变体生成 combo 标识(同一 query 多份稿件按这俩区分)
  creation_direction?: string | null;
  copywriting_type?: string | null;
  // Mediumsly 推送状态:成功 → post_id + url + pushed_at;失败 → last_error
  mediumsly_post_id?: string | null;
  mediumsly_url?: string | null;
  mediumsly_pushed_at?: string | null;
  mediumsly_last_error?: string | null;
  // 2026-06-12 — 平台审核结果回填(passed/rejected;rejected 原因是规则学习素材)
  platform_review_status?: 'passed' | 'rejected' | null;
  platform_reject_reason?: string | null;
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
  const resp = await fetch(`${API_BASE}/admin/content-review${path}`, init);
  if (!resp.ok) {
    const msg = await readApiError(resp, `Request ${method} ${path} failed`);
    throw new Error(msg);
  }
  if (resp.status === 204) return undefined as T;
  return resp.json() as Promise<T>;
}

export const adminContentReviewApi = {
  async listTopics(token: string): Promise<TopicWithDocs[]> {
    return request('GET', '/topics', token);
  },
  async listDocs(
    topicId: number,
    status: string | undefined,
    token: string,
    source?: DocSource,
  ): Promise<GeneratedDoc[]> {
    const qs = new URLSearchParams();
    if (status) qs.set('status', status);
    if (source) qs.set('source', source);
    const suffix = qs.toString() ? `?${qs.toString()}` : '';
    return request('GET', `/topics/${topicId}/docs${suffix}`, token);
  },
  async getDoc(docId: number, token: string): Promise<GeneratedDoc> {
    return request('GET', `/docs/${docId}`, token);
  },
  // admin 改 AI / user 稿正文(不限 source / status)
  async updateDoc(
    docId: number,
    payload: { title?: string; body_markdown?: string; summary?: string },
    token: string,
  ): Promise<GeneratedDoc> {
    return request('PATCH', `/docs/${docId}`, token, payload);
  },
  async selectForReview(docIds: number[], token: string): Promise<void> {
    return request('POST', '/docs/select', token, { doc_ids: docIds });
  },
  async approveDoc(docId: number, token: string): Promise<GeneratedDoc> {
    return request('POST', `/docs/${docId}/approve`, token);
  },
  // 重新生成单篇稿件 — 同步跑 LLM,返回覆写后的 doc(可能需 30-60s)
  async regenerateDoc(docId: number, token: string): Promise<GeneratedDoc> {
    return request('POST', `/docs/${docId}/regenerate`, token);
  },
  async rejectDoc(docId: number, reason: string, token: string): Promise<GeneratedDoc> {
    return request('POST', `/docs/${docId}/reject`, token, { reason });
  },
  async publishDoc(
    docId: number,
    targets: { platform: string; media: string; url?: string }[],
    token: string,
    pushToMediumsly = false,
  ): Promise<GeneratedDoc> {
    return request('POST', `/docs/${docId}/publish`, token, {
      publish_targets: targets,
      push_to_mediumsly: pushToMediumsly,
    });
  },
  // 回填平台方审核结果(仅 published 稿);rejected 必带原因,供平台规则学习
  async setPlatformReview(
    docId: number,
    status: 'passed' | 'rejected',
    token: string,
    reason?: string,
  ): Promise<GeneratedDoc> {
    return request('POST', `/docs/${docId}/platform-review`, token, { status, reason });
  },
};
