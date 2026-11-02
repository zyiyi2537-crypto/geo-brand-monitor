// 内容模板 API — 执行计划编辑器用.
// 端点挂在 /api/admin/content-templates,后端 require_admin 守门.

import { localizedHeaders, readApiError } from './apiError';

const API_BASE = (import.meta.env.VITE_API_URL as string) || '/api';

export type TemplateScope = 'system' | 'tenant' | 'topic';

export interface ContentTemplate {
  id: number;
  scope: TemplateScope;
  tenant_id?: number | null;
  topic_id?: number | null;
  name: string;
  kind: string;                          // 长文 / 短文 / FAQ / 案例 / 测评 / 对比 / 教程 / 问答
  prompt_template: string;
  target_platforms: string[];
  length_min: number;
  length_max: number;
  locked: boolean;
  locked_at?: string | null;
  locked_by_id?: number | null;
  created_by_id?: number | null;
  created_at: string;
  updated_at: string;
}

export interface ContentTemplateCreatePayload {
  scope?: TemplateScope;                 // 默认 tenant
  topic_id?: number;
  name: string;
  kind?: string;
  prompt_template: string;
  target_platforms?: string[];
  length_min?: number;
  length_max?: number;
}

export interface ContentTemplateUpdatePayload {
  name?: string;
  kind?: string;
  prompt_template?: string;
  target_platforms?: string[];
  length_min?: number;
  length_max?: number;
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
  const resp = await fetch(`${API_BASE}/admin/content-templates${path}`, init);
  if (!resp.ok) {
    const msg = await readApiError(resp, `Request ${method} ${path} failed`);
    throw new Error(msg);
  }
  if (resp.status === 204) return undefined as T;
  return resp.json() as Promise<T>;
}

export const contentTemplatesApi = {
  async list(
    token: string, opts: { scope?: TemplateScope; topicId?: number } = {},
  ): Promise<ContentTemplate[]> {
    const qs = new URLSearchParams();
    if (opts.scope) qs.set('scope', opts.scope);
    if (opts.topicId !== undefined) qs.set('topic_id', String(opts.topicId));
    const suffix = qs.toString() ? `?${qs.toString()}` : '';
    return request<ContentTemplate[]>('GET', suffix, token);
  },
  async create(payload: ContentTemplateCreatePayload, token: string): Promise<ContentTemplate> {
    return request<ContentTemplate>('POST', '', token, payload);
  },
  async update(
    id: number, payload: ContentTemplateUpdatePayload, token: string,
  ): Promise<ContentTemplate> {
    return request<ContentTemplate>('PATCH', `/${id}`, token, payload);
  },
  async lock(id: number, token: string): Promise<ContentTemplate> {
    return request<ContentTemplate>('POST', `/${id}/lock`, token);
  },
};
