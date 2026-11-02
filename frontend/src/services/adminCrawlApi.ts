// AI 爬虫日志分析 API 客户端(仅 admin)— 读 vigilath 正式环境 nginx 访问日志.
import { localizedHeaders, readApiError } from './apiError';

const API_BASE = (import.meta.env.VITE_API_URL as string) || '/api';

export interface CrawlBot {
  name: string;
  powers: string;
  importance: 'critical' | 'optional';
  requests: number;
  unique_pages: number;
  ips: number;
  status_codes: Record<string, number>;
  first_seen: string;
  last_seen: string;
  top_pages: { path: string; count: number }[];
}

export interface CrawlMissing {
  name: string;
  powers: string;
}

export interface CrawlAnalysis {
  files: { path: string; size_mb: number; gzipped: boolean }[];
  total_size_mb: number;
  total_lines: number;
  parsed_lines: number;
  period: { first: string | null; last: string | null };
  total_bot_requests: number;
  bots: CrawlBot[];
  missing_critical: CrawlMissing[];
  missing_optional: CrawlMissing[];
  log_glob: string;
  /** 快照生成时间(ISO).cron 每天刷新一次;refresh=true 时为当前时间. */
  generated_at?: string;
}

export const adminCrawlApi = {
  // 只读共享库里的快照(正式环境数据,prod 每天 cron 生成).这里不触发重算.
  async getAnalysis(token: string): Promise<CrawlAnalysis> {
    const resp = await fetch(`${API_BASE}/admin/crawl-analysis`, {
      headers: localizedHeaders({ Authorization: `Bearer ${token}` }),
    });
    if (!resp.ok) {
      throw new Error(await readApiError(resp, 'Failed to load crawl analysis'));
    }
    return resp.json() as Promise<CrawlAnalysis>;
  },
};
