// Phase D — 用户侧 topic 资料 / 监测问题勾选 / 提交审核 API client.
//
// 服务端关联路由:backend/geo/api/ai_telemetry.py
//  PUT  /api/ai-telemetry/topics/{id}/profile
//  POST /api/ai-telemetry/topics/{id}/expand-queries
//  POST /api/ai-telemetry/topics/{id}/selected-queries
//  POST /api/ai-telemetry/topics/{id}/submit-for-review

import { localizedHeaders, readApiError } from './apiError';
import type { BrandProfile, SceneType, Topic } from './aiTelemetryApi';

const API_BASE = (import.meta.env.VITE_API_URL as string) || '/api';

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

// 2026-05-28 v2 — 4 维场景扩展返回结构.
// 老调用方还在用 .queries(平铺数组),这里保留作 fallback 字段.
export interface SceneExpansionResult {
  queries: string[];
  model?: string;
  error?: string | null;
}
export interface ExpandQueriesResp {
  seed: string;
  total_count?: number;
  scenes?: Partial<Record<SceneType, SceneExpansionResult>>;
  /** @deprecated 2026-05-28 — 老 schema 字段,新后端只返 scenes;前端兼容仍读 */
  queries?: string[];
  model?: string;
}

export interface SelectedItem {
  text: string;
  selected: boolean;
  /** 2026-05-20 — 这条 query 来自哪个种子词;候选阶段才有,既有 query 不回填。 */
  seed?: string;
  /** 2026-05-28 — 4 维场景标签;新选的候选必传,老选项可省略后端兜底 search。 */
  scene_type?: SceneType;
}

export interface ExtractProfileResp {
  profile: BrandProfile;
  used_model: string;
  // LLM 顺手给的种子提示词候选(可能空)。前端在编辑器里会附加到种子词步骤。
  seed_suggestions?: string[];
}

// 2026-05-18 — topic 媒体素材(图片 / 视频),「资料上传」弹窗里的非文本资料
export interface TopicMedia {
  id: number;
  topic_id: number;
  filename: string;
  kind: 'image' | 'video';
  mime: string;
  size: number;
  url: string;       // 后端给的 /topics/{id}/media/{mid}/blob,带 Bearer 才能读
  uploaded_at: string;
}

export const topicProfileApi = {
  async updateProfile(topicId: number, profile: BrandProfile, token: string): Promise<Topic> {
    return request<Topic>('PUT', `/topics/${topicId}/profile`, token, profile);
  },
  /**
   * 2026-05-28 v2 — 4 维场景扩展.
   * scenes 不传 → 后端默认 4 维全跑;count_per_scene 不传 → 后端默认每维 50(共 200).
   * 返回里某 scene 可能带 error 字段(brand 在 target 为空时被自动跳过),前端按 scene 分 tab 展示.
   */
  async expandQueries(
    topicId: number,
    seed: string,
    options: { scenes?: SceneType[]; countPerScene?: number } | undefined,
    token: string,
  ): Promise<ExpandQueriesResp> {
    const body: Record<string, unknown> = { seed };
    if (options?.scenes) body.scenes = options.scenes;
    if (options?.countPerScene) body.count_per_scene = options.countPerScene;
    return request<ExpandQueriesResp>(
      'POST', `/topics/${topicId}/expand-queries`, token, body,
    );
  },
  async updateSelectedQueries(topicId: number, items: SelectedItem[], token: string): Promise<Topic> {
    return request<Topic>(
      'POST', `/topics/${topicId}/selected-queries`, token, { items },
    );
  },
  async extractProfile(text: string, token: string): Promise<ExtractProfileResp> {
    return request<ExtractProfileResp>('POST', '/profile/extract', token, { text });
  },
  // PDF / Word / 纯文本文件 — 后端用 pypdf / python-docx 解析后走同一条
  // LLM pipeline,所以前端 PDF.js / mammoth 都不用上,bundle 不胖。
  async extractProfileFile(file: File, token: string): Promise<ExtractProfileResp> {
    const fd = new FormData();
    fd.append('file', file, file.name);
    const resp = await fetch(`${API_BASE}/ai-telemetry/profile/extract-file`, {
      method: 'POST',
      headers: localizedHeaders({ Authorization: `Bearer ${token}` }),
      body: fd,
    });
    if (!resp.ok) {
      const msg = await readApiError(resp, 'AI 解析失败');
      throw new Error(msg);
    }
    return resp.json();
  },

  async listMedia(topicId: number, token: string): Promise<TopicMedia[]> {
    return request<TopicMedia[]>('GET', `/topics/${topicId}/media`, token);
  },
  async uploadMedia(topicId: number, file: File, token: string): Promise<TopicMedia> {
    const fd = new FormData();
    fd.append('file', file, file.name);
    const resp = await fetch(`${API_BASE}/ai-telemetry/topics/${topicId}/media`, {
      method: 'POST',
      headers: localizedHeaders({ Authorization: `Bearer ${token}` }),
      body: fd,
    });
    if (!resp.ok) {
      const msg = await readApiError(resp, '上传失败');
      throw new Error(msg);
    }
    return resp.json();
  },
  async deleteMedia(topicId: number, mediaId: number, token: string): Promise<void> {
    await request<void>('DELETE', `/topics/${topicId}/media/${mediaId}`, token);
  },
};
