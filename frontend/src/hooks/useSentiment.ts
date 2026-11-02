// React Query hooks 包装 sentimentApi.
// 自动注入 token,统一 staleTime,提供 invalidate 方法.

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuth } from '../contexts/AuthContext';
import { sentimentApi, isMockMode } from '../services/sentimentApi';
import { SENTIMENT_PLATFORMS as PLATFORM_FALLBACK } from '../constants/sentimentPlatforms';
import type {
  AccountCreatePayload, AccountUpdatePayload, PostsQuery, PostsResponse,
  SentimentPlatform,
} from '../types/sentiment';

const ACCOUNTS_KEY = ['sentiment', 'accounts'] as const;
const PLATFORMS_KEY = ['sentiment', 'platforms'] as const;

/** 把 constants/sentimentPlatforms.ts 里的本地静态条目"升级"为完整 SentimentPlatform 形态。
 *  仅用于 (a) mock 模式 (b) 后端 /platforms 拉取失败时的兜底,确保页面不至于空白。 */
function fallbackPlatforms(): SentimentPlatform[] {
  return PLATFORM_FALLBACK.map(p => ({
    code: p.code,
    domain: p.domain,
    category: p.category,
    media_type: p.media_type,
    industry: p.industry,
    region: p.region,
    name_zh: '', name_en: '',  // 让消费者回退到 i18n sourceLabels 翻译
  }));
}

/** 拉媒体平台目录(全局只读,几乎不变)。
 *  - mock 模式:直接用 constants
 *  - 真实模式:走 GET /api/sentiment/platforms,失败兜底 constants
 *  - staleTime: 1h(平台目录改完最多 1 小时生效;通常用户重新登录就拿到新版) */
export function useSentimentPlatforms() {
  const { token } = useAuth();
  return useQuery<SentimentPlatform[]>({
    queryKey: PLATFORMS_KEY,
    queryFn: async () => {
      if (isMockMode() || !token) return fallbackPlatforms();
      try {
        const data = await sentimentApi.listPlatforms(token);
        return data.length > 0 ? data : fallbackPlatforms();
      } catch {
        return fallbackPlatforms();
      }
    },
    staleTime: 60 * 60_000,
    initialData: fallbackPlatforms,  // 首次渲染就有数据,避免 UI 闪空
  });
}

export function useSentimentAccounts() {
  const { token } = useAuth();
  return useQuery({
    queryKey: ACCOUNTS_KEY,
    queryFn: () => sentimentApi.listAccounts(token!),
    enabled: !!token,
    staleTime: 60_000,
  });
}

export function useCreateAccount() {
  const { token } = useAuth();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: AccountCreatePayload) => sentimentApi.createAccount(payload, token!),
    onSuccess: () => qc.invalidateQueries({ queryKey: ACCOUNTS_KEY }),
  });
}

export function useUpdateAccount() {
  const { token } = useAuth();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: AccountUpdatePayload }) =>
      sentimentApi.updateAccount(id, payload, token!),
    onSuccess: () => qc.invalidateQueries({ queryKey: ACCOUNTS_KEY }),
  });
}

export function useDeleteAccount() {
  const { token } = useAuth();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => sentimentApi.deleteAccount(id, token!),
    onSuccess: () => qc.invalidateQueries({ queryKey: ACCOUNTS_KEY }),
  });
}

export function useRunStatus(accountId: number | null) {
  const { token } = useAuth();
  const qc = useQueryClient();
  return useQuery({
    queryKey: ['sentiment', 'run-status', accountId],
    queryFn: async () => {
      const data = await sentimentApi.getRunStatus(accountId!, token!);
      // 状态从 running/pending 翻到 terminal(success/failed)时,
      // 主动让数据查询失效 — 用户不必手动刷新就能看到新结果.
      const prev = qc.getQueryData<{ status?: string }>(['sentiment', 'run-status', accountId]);
      const wasRunning = prev?.status === 'running' || prev?.status === 'pending';
      const nowDone = data?.status === 'success' || data?.status === 'failed';
      if (wasRunning && nowDone) {
        qc.invalidateQueries({ queryKey: ['sentiment', 'today', accountId] });
        qc.invalidateQueries({ queryKey: ['sentiment', 'posts', accountId] });
        qc.invalidateQueries({ queryKey: ['sentiment', 'briefs', accountId] });
        qc.invalidateQueries({ queryKey: ACCOUNTS_KEY });
      }
      return data;
    },
    enabled: !!token && accountId !== null && accountId > 0,
    staleTime: 5_000,
    // 任务运行中每 15s 轮询;终态停止轮询(返回 false)
    refetchInterval: (query) => {
      const s = (query.state.data as { status?: string } | undefined)?.status;
      return s === 'running' || s === 'pending' ? 15_000 : false;
    },
    refetchIntervalInBackground: false,
  });
}

export function useRunNow() {
  const { token } = useAuth();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (accountId: number) => sentimentApi.runNow(accountId, token!),
    onSuccess: (_data, accountId) => {
      qc.invalidateQueries({ queryKey: ['sentiment', 'run-status', accountId] });
      qc.invalidateQueries({ queryKey: ACCOUNTS_KEY });
    },
  });
}

export function useTodayData(accountId: number | null, ticker: string | null) {
  const { token } = useAuth();
  return useQuery({
    queryKey: ['sentiment', 'today', accountId, ticker],
    queryFn: () => sentimentApi.getToday(accountId!, ticker!, token!),
    enabled: !!token && !!accountId && !!ticker,
    staleTime: 60_000,
    refetchOnWindowFocus: true,
  });
}

/** 一次性拉取(BriefsTab、向后兼容)。新代码请用 useInfinitePosts。 */
export function usePosts(accountId: number | null, ticker: string | null, limit = 200) {
  const { token } = useAuth();
  return useQuery({
    queryKey: ['sentiment', 'posts', accountId, ticker, limit],
    queryFn: () => sentimentApi.listPosts(accountId!, ticker!, token!, { limit, days: 0 }),
    enabled: !!token && !!accountId && !!ticker,
    staleTime: 60_000,
  });
}

/** 分页 + 时间范围 — ArticlesTab 用。
 *  filters 改变会自动重置第一页(queryKey 含 filters);
 *  fetchNextPage() 拼接下一段。 */
export interface InfinitePostsFilters {
  pageSize?: number;
  /** 时间范围:days 与 start/end 二选一 */
  days?: number;
  start?: string;
  end?: string;
  /** 起始 offset — "跳转到第 N 页" 时设为 (N-1)*pageSize,
   *  用 queryKey 区分,改值会重置 infinite query */
  startOffset?: number;
  /** 排序键 — 见 PostSortKey,改值会重置 infinite query 第一页 */
  sortBy?: import('../types/sentiment').PostSortKey;
}

export function useInfinitePosts(
  accountId: number | null,
  ticker: string | null,
  filters: InfinitePostsFilters = {},
) {
  const { token } = useAuth();
  const pageSize = filters.pageSize ?? 50;
  const startOffset = filters.startOffset ?? 0;
  return useInfiniteQuery<PostsResponse, Error>({
    queryKey: [
      'sentiment', 'posts-infinite', accountId, ticker,
      pageSize, filters.days, filters.start, filters.end, startOffset,
      filters.sortBy,
    ],
    queryFn: ({ pageParam }) => {
      const q: PostsQuery = { limit: pageSize, offset: (pageParam as number) ?? startOffset };
      if (filters.start || filters.end) {
        if (filters.start) q.start = filters.start;
        if (filters.end) q.end = filters.end;
      } else if (filters.days !== undefined) {
        q.days = filters.days;
      }
      if (filters.sortBy) q.sort_by = filters.sortBy;
      return sentimentApi.listPosts(accountId!, ticker!, token!, q);
    },
    initialPageParam: startOffset,
    getNextPageParam: (lastPage, allPages) => {
      const fetched = allPages.reduce((sum, p) => sum + (p.items?.length ?? 0), 0);
      const total = lastPage.total ?? fetched;
      const consumed = startOffset + fetched;
      return consumed < total ? consumed : undefined;
    },
    enabled: !!token && !!accountId && !!ticker,
    staleTime: 60_000,
  });
}

export function useBriefs(accountId: number | null, ticker: string | null) {
  const { token } = useAuth();
  return useQuery({
    queryKey: ['sentiment', 'briefs', accountId, ticker],
    queryFn: () => sentimentApi.listBriefs(accountId!, ticker!, token!),
    enabled: !!token && !!accountId && !!ticker,
    staleTime: 60_000,
  });
}

export function useBriefDetail(accountId: number | null, briefId: number | null) {
  const { token } = useAuth();
  return useQuery({
    queryKey: ['sentiment', 'brief', accountId, briefId],
    queryFn: () => sentimentApi.getBrief(accountId!, briefId!, token!),
    enabled: !!token && !!accountId && !!briefId,
    staleTime: 5 * 60_000,
  });
}

export function useDrafts(accountId: number | null, ticker: string | null) {
  const { token } = useAuth();
  return useQuery({
    queryKey: ['sentiment', 'drafts', accountId, ticker],
    queryFn: () => sentimentApi.listDrafts(accountId!, ticker!, token!),
    enabled: !!token && !!accountId && !!ticker,
    staleTime: 60_000,
  });
}

// ─────────────────── newsnow 实时热点 ──────────────────

/** 推荐源目录(静态)。staleTime 长 — 几乎不变。 */
export function useNewsnowSources() {
  const { token } = useAuth();
  return useQuery({
    queryKey: ['sentiment', 'newsnow-sources'],
    queryFn: () => sentimentApi.listNewsnowSources(token!),
    enabled: !!token,
    staleTime: 60 * 60_000,
  });
}

/** 指定 source 的热榜。newsnow 自身缓存 30 分钟,前端 5 分钟过期触发刷新。 */
export function useNewsnowHot(source: string | null, limit = 30) {
  const { token } = useAuth();
  return useQuery({
    queryKey: ['sentiment', 'newsnow-hot', source, limit],
    queryFn: () => sentimentApi.getNewsnowHot(source!, token!, limit),
    enabled: !!token && !!source,
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: true,
  });
}

export function useGenerateDraft() {
  const { token } = useAuth();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Parameters<typeof sentimentApi.generateDraft>[0]) =>
      sentimentApi.generateDraft(payload, token!),
    onSuccess: (_data, payload) => {
      qc.invalidateQueries({ queryKey: ['sentiment', 'drafts', payload.account_id] });
    },
  });
}

export function useKnowledge(accountId: number | null) {
  const { token } = useAuth();
  return useQuery({
    queryKey: ['sentiment', 'knowledge', accountId],
    queryFn: () => sentimentApi.listKnowledge(accountId!, token!),
    enabled: !!token && !!accountId,
    staleTime: 5 * 60_000,
  });
}

export function useUpsertKnowledge() {
  const { token } = useAuth();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ accountId, key, body }: { accountId: number; key: string; body: string }) =>
      sentimentApi.upsertKnowledge(accountId, key, body, token!),
    onSuccess: (_data, { accountId }) => {
      qc.invalidateQueries({ queryKey: ['sentiment', 'knowledge', accountId] });
    },
  });
}
