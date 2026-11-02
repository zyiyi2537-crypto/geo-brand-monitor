// 平台审核规则库 API — /api/admin/platform-rules,后端 require_admin 守门.
// 规则文本在生成文章时按发文行平台注入 prompt;「从拒稿学习」把平台拒稿原因
// 提炼成规则增量(pending),admin 采纳后生效。

import { localizedHeaders, readApiError } from './apiError';

const API_BASE = (import.meta.env.VITE_API_URL as string) || '/api';

export interface PlatformRule {
  platform: string;
  rules_text: string;
  pending_rules_text: string;
  learned_at?: string | null;
  updated_at?: string | null;
  rejected_count: number;
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
  const resp = await fetch(`${API_BASE}/admin/platform-rules${path}`, init);
  if (!resp.ok) {
    const msg = await readApiError(resp, `Request ${method} ${path} failed`);
    throw new Error(msg);
  }
  return resp.json() as Promise<T>;
}

export const platformRulesApi = {
  async list(token: string): Promise<PlatformRule[]> {
    return request('GET', '', token);
  },
  async update(
    platform: string, rulesText: string, token: string, clearPending = false,
  ): Promise<PlatformRule> {
    return request('PUT', `/${encodeURIComponent(platform)}`, token,
      { rules_text: rulesText, clear_pending: clearPending });
  },
  // LLM 生成初稿(不落库,返回草稿文本由 admin 校对)
  async seed(platform: string, token: string): Promise<{ platform: string; draft: string }> {
    return request('POST', `/${encodeURIComponent(platform)}/seed`, token);
  },
  // 全平台:聚合拒稿原因 → LLM 提炼增量写入 pending
  async learn(token: string): Promise<PlatformRule[]> {
    return request('POST', '/learn', token);
  },
  async approvePending(platform: string, token: string): Promise<PlatformRule> {
    return request('POST', `/${encodeURIComponent(platform)}/approve-pending`, token);
  },
};
