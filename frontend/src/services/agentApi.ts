// GEO 优化 Agent — 对话式后端(独立 service,nginx 反代 /api/agent/*)。
// chat 走 SSE 流式:POST + ReadableStream(EventSource 不支持自定义 Authorization 头)。

import { localizedHeaders } from './apiError';

const API_BASE = (import.meta.env.VITE_API_URL as string) || '/api';

export interface AgentCard {
  tool: string;
  data: Record<string, unknown>;
}

export interface ChatCallbacks {
  onDelta: (text: string) => void;
  onCards?: (cards: AgentCard[]) => void;   // 数据工具返回 → 结构化卡片
  onDone?: () => void;
  onError?: (msg: string) => void;
  signal?: AbortSignal;
}

/** 流式对话。把 message 发给 agent,逐 token 回调 onDelta。 */
export async function streamAgentChat(
  message: string,
  topicId: number | null,
  cb: ChatCallbacks,
): Promise<void> {
  const token = localStorage.getItem('token');
  let resp: Response;
  try {
    resp = await fetch(`${API_BASE}/agent/chat`, {
      method: 'POST',
      headers: localizedHeaders({
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token ?? ''}`,
      }),
      body: JSON.stringify({ message, topic_id: topicId }),
      signal: cb.signal,
    });
  } catch (e) {
    cb.onError?.(e instanceof Error ? e.message : '网络错误');
    return;
  }

  if (resp.status === 401) { cb.onError?.('未登录或登录已过期'); return; }
  if (resp.status === 503) { cb.onError?.('Agent 服务暂不可用'); return; }
  if (!resp.ok || !resp.body) { cb.onError?.(`请求失败(${resp.status})`); return; }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const parts = buf.split('\n\n');
      buf = parts.pop() ?? '';
      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith('data:')) continue;
        const payload = line.slice(5).trim();
        try {
          const obj = JSON.parse(payload) as { delta?: string; cards?: AgentCard[]; error?: string; done?: boolean };
          if (obj.delta) cb.onDelta(obj.delta);
          else if (obj.cards) cb.onCards?.(obj.cards);
          else if (obj.error) cb.onError?.(obj.error);
          else if (obj.done) { cb.onDone?.(); return; }
        } catch { /* 跳过非 JSON 行 */ }
      }
    }
  } catch (e) {
    if ((e as Error)?.name !== 'AbortError') cb.onError?.((e as Error).message);
    return;
  }
  cb.onDone?.();
}

export interface AgentNotification {
  id: number;
  title: string;
  body: string;
  created_at: string | null;
}

/** 拉未读主动通知(舆情高风险等)。 */
export async function fetchNotifications(): Promise<AgentNotification[]> {
  const token = localStorage.getItem('token');
  try {
    const r = await fetch(`${API_BASE}/agent/notifications`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!r.ok) return [];
    const d = await r.json();
    return (d.notifications as AgentNotification[]) || [];
  } catch {
    return [];
  }
}

/** 标记所有未读为已读。 */
export async function markNotificationsRead(): Promise<void> {
  const token = localStorage.getItem('token');
  try {
    await fetch(`${API_BASE}/agent/notifications/read`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    });
  } catch { /* 忽略 */ }
}
