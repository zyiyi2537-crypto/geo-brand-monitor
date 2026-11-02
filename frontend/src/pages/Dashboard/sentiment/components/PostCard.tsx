import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router-dom';
import type { SentimentPost } from '../../../../types/sentiment';
import { useSentimentPlatforms } from '../../../../hooks/useSentiment';
import { SentimentBadge, RiskBadge, InfluenceBar } from './badges';

// 显示绝对日期 — 去掉 "X 天前" 相对时间。
// 今年:'5/8 14:30';跨年:'2025-12-31 14:30'。
function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const now = new Date();
  const sameYear = d.getFullYear() === now.getFullYear();
  const m = d.getMonth() + 1;
  const day = d.getDate();
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  return sameYear
    ? `${m}/${day} ${hh}:${mm}`
    : `${d.getFullYear()}-${String(m).padStart(2, '0')}-${String(day).padStart(2, '0')} ${hh}:${mm}`;
}

interface Props {
  post: SentimentPost;
  selected?: boolean;
  onClick?: () => void;
  compact?: boolean;
}

function countChars(s: string): number {
  const stripped = s.replace(/\s+/g, '');
  const wordCount = s.trim().split(/\s+/).filter(Boolean).length;
  return Math.max(stripped.length, wordCount);
}

export function PostCard({ post, selected, onClick, compact }: Props) {
  const { t, i18n } = useTranslation();
  const [params] = useSearchParams();
  const highlight = params.get('q') ?? '';
  const platforms = useSentimentPlatforms().data ?? [];
  // source code → { name_zh|name_en, region } 查找表
  const platformMeta = useMemo(() => {
    const m = new Map<string, { name: string; region: string }>();
    for (const p of platforms) {
      const name = i18n.language === 'zh' ? (p.name_zh || p.code) : (p.name_en || p.code);
      m.set(p.code, { name, region: p.region });
    }
    return m;
  }, [platforms, i18n.language]);

  const meta = platformMeta.get(post.source);
  // 平台名:优先 i18n 名,fallback 到 i18n 字典 sourceLabels.<code>,再 fallback 到 raw code
  const platformName = meta?.name ?? (() => {
    const k = `dashboard.sentiment.articles.sourceLabels.${post.source}`;
    const v = t(k);
    return v === k ? post.source : v;
  })();
  const regionKey = meta?.region && `dashboard.sentiment.articles.regions.${meta.region}`;
  const regionLabel = regionKey ? t(regionKey) : '';
  const showRegion = regionKey && regionLabel !== regionKey;

  const topics = post.topics ?? [];
  return (
    <article
      onClick={onClick}
      className="px-3 py-2.5 cursor-pointer transition-colors hover:bg-tertiary/50"
      style={{
        background: selected ? 'var(--bg-tertiary)' : 'transparent',
        borderBottom: '1px solid var(--border-color)',
        borderLeft: selected ? '2px solid var(--accent-primary)' : '2px solid transparent',
      }}
    >
      {/* 行 1: [Risk] 标题(粗体黑字)— 命中 ?q 时黄高亮 */}
      <div className="flex items-start gap-2 mb-1">
        <RiskBadge level={post.risk_level} t={t} />
        <h4 className="font-semibold text-sm text-primary leading-snug line-clamp-2 flex-1 min-w-0">
          {highlightText(post.title || '(无标题)', highlight)}
        </h4>
      </div>

      {/* 行 2: 平台 · @账号 · 发布时间 · 地区 — 缺 author 整段不渲染(连同分隔点),不展示"佚名" */}
      <div className="flex items-center gap-2 flex-wrap mb-1 text-[11px]">
        <span className="font-medium" style={{ color: 'var(--text-primary)' }}>
          {platformName}
        </span>
        {post.author && (
          <>
            <span className="text-muted">·</span>
            <span className="truncate max-w-[10rem]" style={{ color: 'var(--text-secondary)' }}
              title={post.author}>
              @{post.author}
            </span>
          </>
        )}
        <span className="text-muted">·</span>
        <span style={{ color: 'var(--text-secondary)' }}>{fmtDate(post.publish_time ?? post.ingested_at)}</span>
        {showRegion && (
          <>
            <span className="text-muted">·</span>
            <span style={{ color: 'var(--text-muted)' }}>{regionLabel}</span>
          </>
        )}
      </div>

      {/* 行 3: 摘要 — 黄高亮 */}
      {!compact && post.summary && (
        <p className="text-xs text-secondary line-clamp-2 mb-1.5">
          {highlightText(post.summary, highlight)}
        </p>
      )}

      {/* 底:情感 + 影响力 + 计数 + 话题 chip,紧凑一行(详情里也有,卡片留个浓缩条) */}
      <div className="flex items-center gap-2 flex-wrap text-[11px] text-muted">
        <SentimentBadge label={post.sentiment_label} score={post.sentiment_score} t={t} />
        <InfluenceBar value={post.influence_potential} />
        {post.content && <span>📝 {countChars(post.content).toLocaleString()}</span>}
        {post.view_count != null && <span>👁 {post.view_count.toLocaleString()}</span>}
        {!compact && topics.slice(0, 2).map(tag => (
          <span key={tag} className="px-1 rounded"
            style={{ background: 'rgba(59,130,246,0.12)', color: '#1e40af' }}>
            #{tag}
          </span>
        ))}
      </div>
    </article>
  );
}

/** 按 needle split text,命中片段用 <mark> 高亮。空 needle 直接返回原文。 */
function highlightText(text: string, needle: string): React.ReactNode {
  const n = needle.trim();
  if (!n) return text;
  const escaped = n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const parts = text.split(new RegExp(`(${escaped})`, 'gi'));
  return parts.map((p, i) => i % 2 === 1
    ? <mark key={i} style={{ background: 'rgba(251,191,36,0.35)', color: 'inherit', padding: '0 1px' }}>{p}</mark>
    : p,
  );
}

// RegionTag 已并入主 header,这里删除独立组件
