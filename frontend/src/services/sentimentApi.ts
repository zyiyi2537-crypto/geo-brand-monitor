// 舆情后端 API 客户端.
// 所有方法走 /api/sentiment/*,需 Bearer token(由 AuthContext 注入).
// VITE_USE_MOCK_SENTIMENT=1 时不走网络,前端组件直接读 mocks/sentiment.ts.

import { localizedHeaders, readApiError } from './apiError';
import type {
  AccountCreatePayload, AccountUpdatePayload,
  Brief, BriefsResponse, DraftGenerateResult, DraftsResponse,
  KnowledgeDoc, NewsnowHotResponse, NewsnowSourcesResponse,
  PostsResponse, PostsQuery, RunStatusPayload,
  SentimentAccount, SentimentPlatform, TodayResponse,
} from '../types/sentiment';

const API_BASE = (import.meta.env.VITE_API_URL as string) || '/api';

/** 是否使用 mock 数据(在 .env / 启动时设置 VITE_USE_MOCK_SENTIMENT=1)。
 *  Sentiment.tsx / 各 Tab 通过 isMockMode() 决定走 mock 还是真实 API. */
export function isMockMode(): boolean {
  return String(import.meta.env.VITE_USE_MOCK_SENTIMENT || '').toLowerCase() === '1';
}

function authHeaders(token: string, extra: Record<string, string> = {}): Record<string, string> {
  return localizedHeaders({
    Authorization: `Bearer ${token}`,
    ...extra,
  });
}

async function request<T>(
  method: string, path: string, token: string,
  body?: unknown,
): Promise<T> {
  const init: RequestInit = {
    method,
    headers: authHeaders(token, body !== undefined ? { 'Content-Type': 'application/json' } : {}),
  };
  if (body !== undefined) init.body = JSON.stringify(body);
  const resp = await fetch(`${API_BASE}/sentiment${path}`, init);
  if (!resp.ok) {
    const msg = await readApiError(resp, `Request ${method} ${path} failed`);
    throw new Error(msg);
  }
  if (resp.status === 204) return undefined as T;
  return resp.json() as Promise<T>;
}

// ─────────────────────────── 账号 CRUD ────────────────────────

export const sentimentApi = {
  listPlatforms(token: string): Promise<SentimentPlatform[]> {
    return request<SentimentPlatform[]>('GET', '/platforms', token);
  },

  listAccounts(token: string): Promise<SentimentAccount[]> {
    return request<SentimentAccount[]>('GET', '/accounts', token);
  },

  createAccount(payload: AccountCreatePayload, token: string): Promise<SentimentAccount> {
    return request<SentimentAccount>('POST', '/accounts', token, payload);
  },

  getAccount(accountId: number, token: string): Promise<SentimentAccount> {
    return request<SentimentAccount>('GET', `/accounts/${accountId}`, token);
  },

  updateAccount(
    accountId: number, payload: AccountUpdatePayload, token: string,
  ): Promise<SentimentAccount> {
    return request<SentimentAccount>('PUT', `/accounts/${accountId}`, token, payload);
  },

  deleteAccount(accountId: number, token: string): Promise<void> {
    return request<void>('DELETE', `/accounts/${accountId}`, token);
  },

  // ── 状态机 / 触发 ──
  getRunStatus(accountId: number, token: string): Promise<RunStatusPayload> {
    return request<RunStatusPayload>('GET', `/accounts/${accountId}/run-status`, token);
  },

  runNow(accountId: number, token: string): Promise<{ queued: boolean }> {
    return request<{ queued: boolean }>('POST', `/accounts/${accountId}/run-now`, token);
  },

  listRunLogs(accountId: number, token: string, limit = 20) {
    return request<unknown[]>(
      'GET', `/accounts/${accountId}/run-logs?limit=${limit}`, token,
    );
  },

  // ── 数据查询 ──
  getToday(accountId: number, ticker: string, token: string, days = 7): Promise<TodayResponse> {
    return request<TodayResponse>(
      'GET',
      `/accounts/${accountId}/today?ticker=${encodeURIComponent(ticker)}&days=${days}`,
      token,
    );
  },

  listPosts(
    accountId: number, ticker: string, token: string,
    query: PostsQuery = {},
  ): Promise<PostsResponse> {
    const limit = query.limit ?? 50;
    const offset = query.offset ?? 0;
    const usp = new URLSearchParams();
    usp.set('ticker', ticker);
    usp.set('limit', String(limit));
    usp.set('offset', String(offset));
    // start/end 优先;若给了 start/end 则后端忽略 days,这里仍透传 days 兼容
    if (query.days !== undefined) usp.set('days', String(query.days));
    if (query.start) usp.set('start', query.start);
    if (query.end) usp.set('end', query.end);
    if (query.sort_by) usp.set('sort_by', query.sort_by);
    return request<PostsResponse>(
      'GET',
      `/accounts/${accountId}/posts?${usp.toString()}`,
      token,
    );
  },

  listBriefs(accountId: number, ticker: string, token: string): Promise<BriefsResponse> {
    return request<BriefsResponse>(
      'GET',
      `/accounts/${accountId}/briefs?ticker=${encodeURIComponent(ticker)}`,
      token,
    );
  },

  getBrief(accountId: number, briefId: number, token: string): Promise<Brief> {
    return request<Brief>('GET', `/accounts/${accountId}/briefs/${briefId}`, token);
  },

  listDrafts(accountId: number, ticker: string, token: string): Promise<DraftsResponse> {
    return request<DraftsResponse>(
      'GET',
      `/accounts/${accountId}/drafts?ticker=${encodeURIComponent(ticker)}`,
      token,
    );
  },

  generateDraft(
    payload: { account_id: number; source?: string; post_id?: string; topic?: string; situation?: string },
    token: string,
  ): Promise<DraftGenerateResult> {
    return request<DraftGenerateResult>('POST', '/drafts/generate', token, payload);
  },

  // ── newsnow 实时热点(不绑 account)──
  listNewsnowSources(token: string): Promise<NewsnowSourcesResponse> {
    return request<NewsnowSourcesResponse>('GET', '/newsnow/sources', token);
  },

  getNewsnowHot(source: string, token: string, limit = 30): Promise<NewsnowHotResponse> {
    const usp = new URLSearchParams({ source, limit: String(limit) });
    return request<NewsnowHotResponse>('GET', `/newsnow/hot?${usp.toString()}`, token);
  },

  // ── 知识库 ──
  listKnowledge(accountId: number, token: string): Promise<KnowledgeDoc[]> {
    return request<KnowledgeDoc[]>('GET', `/accounts/${accountId}/knowledge`, token);
  },

  upsertKnowledge(
    accountId: number, key: string, body: string, token: string,
  ): Promise<KnowledgeDoc> {
    return request<KnowledgeDoc>(
      'PUT', `/accounts/${accountId}/knowledge/${key}`, token, { body },
    );
  },
};

export default sentimentApi;
