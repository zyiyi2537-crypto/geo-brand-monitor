// 通用情感/风险胶囊 — 严格按 yuqin enum 配色,所有 tab/card 共用。
// 真实 API 返回的 sentiment_label / risk_level 可能是任意 string 或 null,
// 这里做容错(unknown 字段归 unknown 桶,null 归 none).

const SENTIMENT_COLOR: Record<string, { bg: string; fg: string }> = {
  bullish: { bg: 'rgba(22,163,74,0.12)', fg: '#16a34a' },
  bearish: { bg: 'rgba(220,38,38,0.12)', fg: '#dc2626' },
  neutral: { bg: 'rgba(100,116,139,0.12)', fg: '#64748b' },
  mixed:   { bg: 'rgba(124,58,237,0.12)', fg: '#7c3aed' },
  unknown: { bg: 'rgba(148,163,184,0.12)', fg: '#94a3b8' },
};

const RISK_COLOR: Record<string, { bg: string; fg: string }> = {
  none:   { bg: 'rgba(148,163,184,0.15)', fg: '#64748b' },
  low:    { bg: 'rgba(251,191,36,0.18)',  fg: '#b45309' },
  medium: { bg: 'rgba(251,146,60,0.20)',  fg: '#9a3412' },
  high:   { bg: 'rgba(239,68,68,0.20)',   fg: '#b91c1c' },
};

const SENTIMENT_KEYS = new Set(['bullish', 'bearish', 'neutral', 'mixed']);
const RISK_KEYS = new Set(['none', 'low', 'medium', 'high']);

function normalizeSentiment(label: string | null | undefined): string {
  const l = (label ?? '').toLowerCase();
  return SENTIMENT_KEYS.has(l) ? l : 'unknown';
}

function normalizeRisk(level: string | null | undefined): string {
  const l = (level ?? '').toLowerCase();
  return RISK_KEYS.has(l) ? l : 'none';
}

export function SentimentBadge({ label, score, t }: {
  label: string | null | undefined;
  score?: number | null;
  t: (k: string) => string;
}) {
  const key = normalizeSentiment(label);
  const c = SENTIMENT_COLOR[key];
  const labelText = t(`dashboard.sentiment.articles.labels.${key}`);
  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-semibold"
      style={{ background: c.bg, color: c.fg }}
    >
      <span>{labelText}</span>
      {typeof score === 'number' && (
        // 分数原始范围 -1..+1,按百分比展示更直观(用户反馈:小数看不懂)
        <span className="font-mono text-[10px] opacity-80">
          {score >= 0 ? '+' : ''}{Math.round(score * 100)}%
        </span>
      )}
    </span>
  );
}

export function RiskBadge({ level, t }: {
  level: string | null | undefined;
  t: (k: string) => string;
}) {
  const key = normalizeRisk(level);
  const c = RISK_COLOR[key];
  const labelText = t(`dashboard.sentiment.articles.risk.${key}`);
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-bold uppercase tracking-wide"
      style={{ background: c.bg, color: c.fg }}
    >
      {labelText}
    </span>
  );
}

export function SourceBadge({ source }: { source: string }) {
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-semibold uppercase tracking-wide"
      style={{ background: 'var(--bg-tertiary)', color: 'var(--text-secondary)' }}
    >
      {source}
    </span>
  );
}

export function InfluenceBar({ value }: { value: number | null | undefined }) {
  const v = value ?? 0;
  const pct = Math.max(0, Math.min(1, v)) * 100;
  return (
    <div className="inline-flex items-center gap-1.5">
      <div
        className="rounded-full overflow-hidden"
        style={{ width: 52, height: 4, background: 'var(--bg-tertiary)' }}
      >
        <div
          style={{
            width: `${pct}%`,
            height: '100%',
            background: 'var(--accent-primary)',
          }}
        />
      </div>
      <span className="font-mono text-[10px] text-muted">{v.toFixed(2)}</span>
    </div>
  );
}
