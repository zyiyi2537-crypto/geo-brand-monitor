import axios from 'axios';
import type { GeoTestResult } from '../types/geo';
import type {
  AdvancedMode,
  AdvancedRequestBody,
  AdvancedResponseOf,
} from '../types/advanced';
import { extractAxiosErrorMessage, currentLocale } from './apiError';

const API_BASE_URL = import.meta.env.VITE_API_URL || '/api';

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  // 15 min. Entity audit runs 10 queries × ~85s/query on each browser engine
  // (Qwen/DeepSeek open a fresh stealth context per query and wait for the
  // full answer stream + source drawer expansion). Real runs we've observed:
  // ~856s on 小米汽车. 300s used to cut off around q3. 默认 25 类全跑的慢站
  // 也会触到这个边界,后端会写 L1 缓存兜底;后续切 SSE 后此值可降回。
  timeout: 900000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Stamp every outgoing request with the current UI locale so the backend
// error handler can return localized error messages.
apiClient.interceptors.request.use((config) => {
  config.headers = config.headers || {};
  config.headers['X-Locale'] = currentLocale();
  return config;
});

/** Error thrown by geoApi calls with the HTTP status attached so callers can
 *  branch on specific cases (e.g. 429 quota exceeded). Message is the
 *  backend-supplied string when available, otherwise a generic fallback. */
export class ApiError extends Error {
  status?: number;
  constructor(message: string, status?: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

function throwApiError(error: unknown, fallback: string): never {
  if (axios.isAxiosError(error)) {
    const message = extractAxiosErrorMessage(error, fallback);
    throw new ApiError(message, error.response?.status);
  }
  throw new ApiError(fallback);
}

// Route-path segment for each advanced mode. Keep in sync with backend
// backend/app/api/advanced.py paths.
const ADVANCED_PATH: Record<AdvancedMode, string> = {
  aeo: '/check/advanced/aeo',
  compare: '/check/advanced/compare',
  crawlTest: '/check/advanced/crawl-test',
  authority: '/check/advanced/authority',
  citation: '/check/advanced/citation',
  visibility: '/check/advanced/visibility',
  entity: '/check/advanced/entity',
};

/**
 * Pick the check endpoint + headers based on whether the caller is logged in.
 *
 * - Logged in → POST /api/check with Bearer token. Backend enforces per-user
 *   quota and runs the user's tier's allowed_check_categories.
 * - Not logged in → POST /api/check/anonymous. No quota, always 5-category free
 *   run, returns tier='free'.
 */
function resolveCheckRequest() {
  const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;
  if (token) {
    return {
      path: '/check',
      headers: { Authorization: `Bearer ${token}` },
    };
  }
  return { path: '/check/anonymous', headers: {} };
}

export const geoApi = {
  async runGeoCheck(
    url: string,
    includeFix: boolean = true,
    signal?: AbortSignal,
    forceRefresh: boolean = false,
  ): Promise<GeoTestResult> {
    const request = {
      url,
      include_fix: includeFix,
      force_refresh: forceRefresh,
    };
    const { path, headers } = resolveCheckRequest();
    try {
      const response = await apiClient.post(path, request, { headers, signal });
      return response.data;
    } catch (error) {
      throwApiError(error, 'Failed to run GEO check');
    }
  },

  async runAdvancedCheck<M extends AdvancedMode>(
    mode: M,
    body: AdvancedRequestBody<M>,
    signal?: AbortSignal,
  ): Promise<AdvancedResponseOf<M>> {
    const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;
    const headers: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};
    try {
      const response = await apiClient.post(ADVANCED_PATH[mode], body, { headers, signal });
      const data = response.data;

      // Entity / compare mode: POST may return {task_id, status:"running"}
      // instead of the full result.  Poll GET /{mode_path}/{task_id} until done.
      if ((mode === 'entity' || mode === 'compare') && data.task_id && data.status === 'running') {
        return this._pollTask(mode, data.task_id, headers, signal) as Promise<AdvancedResponseOf<M>>;
      }

      return data as AdvancedResponseOf<M>;
    } catch (error) {
      throwApiError(error, 'Failed to run advanced check');
    }
  },

  async _pollTask(
    mode: 'entity' | 'compare',
    taskId: string,
    headers: Record<string, string>,
    signal?: AbortSignal,
  ): Promise<any> {
    const POLL_INTERVAL = 5000;
    let retries = 0;
    const MAX_RETRIES = 3;
    while (true) {
      await new Promise((r) => setTimeout(r, POLL_INTERVAL + retries * 2000));
      if (signal?.aborted) throw new ApiError('Aborted');
      try {
        const resp = await apiClient.get(`${ADVANCED_PATH[mode]}/${taskId}`, { headers, signal, timeout: 15000 });
        retries = 0; // reset on success
        if (resp.data.status === 'running') continue;
        return resp.data;
      } catch (error) {
        // Retry on transient 502/503/504 from upstream proxy
        const status = axios.isAxiosError(error) ? error.response?.status : 0;
        if (retries < MAX_RETRIES && status && status >= 502 && status <= 504) {
          retries++;
          continue;
        }
        throwApiError(error, 'Failed to poll entity audit result');
      }
    }
  },

  async getEnginesStatus(): Promise<Record<string, { available: boolean; type: string; has_session?: boolean }>> {
    try {
      const response = await apiClient.get('/check/advanced/engines/status');
      return response.data;
    } catch {
      return {};
    }
  },

  async runCompetitiveIntel(
    body: { url: string; competitor_domains?: string[] },
    signal?: AbortSignal,
  ): Promise<any> {
    const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;
    const headers: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};
    try {
      const response = await apiClient.post('/check/advanced/competitive-intel', body, { headers, signal });
      return response.data;
    } catch (error) {
      throwApiError(error, 'Failed to run competitive intelligence check');
    }
  },

  async checkGeo(data: any, signal?: AbortSignal): Promise<GeoTestResult> {
    const { path, headers } = resolveCheckRequest();
    try {
      const response = await apiClient.post(path, data, { headers, signal });
      return response.data;
    } catch (error) {
      throwApiError(error, 'Failed to run GEO check');
    }
  },

  runGeoCheckStream(
    url: string,
    includeFix: boolean = true,
    onUpdate: (data: any) => void,
    onError: (error: Error) => void,
  ): () => void {
    const encodedUrl = encodeURIComponent(url);
    const eventSource = new EventSource(`${API_BASE_URL}/geo/stream?url=${encodedUrl}&include_fix=${includeFix}`);

    eventSource.addEventListener('status', (event) => {
      try {
        const data = JSON.parse(event.data);
        onUpdate(data);

        if (data.status === 'completed' || data.status === 'failed') {
          eventSource.close();
        }
      } catch (error) {
        onError(new Error('Failed to parse SSE event'));
        eventSource.close();
      }
    });

    eventSource.addEventListener('error', () => {
      if (eventSource.readyState === EventSource.CLOSED) {
        onError(new Error('SSE connection error'));
        eventSource.close();
      }
    });

    return () => eventSource.close();
  },

  async downloadFixPackage(url: string): Promise<void> {
    const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'X-Locale': currentLocale(),
    };
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(`${API_BASE_URL}/check/fix-package`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ url }),
    });

    if (!response.ok) {
      if (response.status === 403) {
        throw new ApiError('This feature requires a starter or higher membership.', response.status);
      }
      throw new ApiError('Failed to download fix package', response.status);
    }

    const blob = await response.blob();
    const contentDisposition = response.headers.get('Content-Disposition') || '';
    const filenameMatch = contentDisposition.match(/filename="(.+)"/);
    const filename = filenameMatch
      ? filenameMatch[1]
      : `geo-fix-${url.replace(/[^a-z0-9]/gi, '-')}-${Date.now()}.zip`;

    const objectUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = objectUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(objectUrl);
  },
};
