import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { BrandGrowthShell, type ShellState } from './shell';
import { contentApi, type ContentDoc } from '../../services/contentApi';
import { useBgLang, engineLabel, ENGINE_ORDER } from './lang';
import { InfoHint, LoadingBlock } from './charts';

type RoiFilter = 'all' | 'hit' | 'miss';

const PAGE_SIZE = 10;

export function Published() {
  const L = useBgLang();
  return (
    <BrandGrowthShell title={L.publishedTitle} breadcrumb={[{ label: L.pageTitle, to: '/brand-growth' }]}>
      {(state) => <Body state={state} />}
    </BrandGrowthShell>
  );
}

function Body({ state }: { state: ShellState }) {
  const { token, topic, selectedEngines } = state;
  const L = useBgLang();
  const [params, setParams] = useSearchParams();
  const roi = (params.get('roi') as RoiFilter) || 'all';
  const platform = params.get('platform') || '';
  const [docs, setDocs] = useState<ContentDoc[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);

  // ROI(命中/未命中)与模型筛选都按 cited_by 在前端算 —— cited_by 是 URL 级 per-engine
  // 命中记录,选了某个模型时 ROI 必须按该模型口径重判(后端 query_hit 是全引擎汇总,
  // miss 口径与单模型对不上),所以这里只拉全量已发布稿件,过滤全在前端。
  useEffect(() => {
    if (!topic) return;
    setLoading(true);
    contentApi.listDocs(topic.id, { status: 'published' }, token)
      .then(setDocs).catch(() => setDocs([])).finally(() => setLoading(false));
  }, [token, topic?.id]);

  // 切换 ROI / 平台 / 模型时回到第一页
  useEffect(() => { setPage(1); }, [roi, platform, selectedEngines.join(',')]);

  if (!topic) return null;

  // 选了部分引擎 → 只看这些引擎是否引用过;全选/未选 → 看任意引擎
  const isCited = (d: ContentDoc): boolean => {
    const cb = d.cited_by || {};
    const engs = selectedEngines.length > 0 ? selectedEngines : Object.keys(cb);
    return engs.some(e => Array.isArray(cb[e]) && cb[e].length > 0);
  };
  const roiFiltered = roi === 'all'
    ? docs
    : docs.filter(d => (roi === 'hit' ? isCited(d) : !isCited(d)));

  const platforms = Array.from(new Set(
    docs.flatMap(d => d.publish_targets.map(t => t.platform)).filter(Boolean)
  ));
  const visible = platform ? roiFiltered.filter(d => d.publish_targets.some(t => t.platform === platform)) : roiFiltered;
  const totalPages = Math.max(1, Math.ceil(visible.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const pagedDocs = visible.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  const setRoi = (r: RoiFilter) => {
    const next = new URLSearchParams(params);
    if (r === 'all') next.delete('roi'); else next.set('roi', r);
    setParams(next, { replace: true });
  };
  const setPlatform = (p: string) => {
    const next = new URLSearchParams(params);
    if (!p) next.delete('platform'); else next.set('platform', p);
    setParams(next, { replace: true });
  };

  const roiLabels: Record<RoiFilter, string> = {
    all: L.publishedFilterAll,
    hit: L.publishedFilterHit,
    miss: L.publishedFilterMiss,
  };

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-1.5">
          <div className="flex gap-1 p-0.5 rounded" style={{ background: 'var(--bg-input)' }}>
            {(['all', 'hit', 'miss'] as RoiFilter[]).map(r => (
              <button
                key={r} type="button" onClick={() => setRoi(r)}
                className="px-3 py-1 text-xs rounded"
                style={{
                  background: roi === r ? 'var(--accent-primary)' : 'transparent',
                  color: roi === r ? 'white' : 'var(--text-secondary)',
                }}
              >
                {roiLabels[r]}
              </button>
            ))}
          </div>
          <InfoHint text={L.hintPublished} />
        </div>
        {platforms.length > 0 && (
          <select
            value={platform} onChange={e => setPlatform(e.target.value)}
            className="text-xs px-2 py-1 rounded"
            style={{ background: 'var(--bg-input)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }}
          >
            <option value="">{L.publishedAllPlatform}</option>
            {platforms.map(p => <option key={p} value={p}>{p}</option>)}
          </select>
        )}
        <span className="text-xs text-muted ml-auto">{L.publishedTotal(visible.length)}</span>
      </div>

      {loading ? (
        <LoadingBlock label={L.loading} />
      ) : visible.length === 0 ? (
        <div className="text-xs text-muted text-center py-10">{L.publishedEmpty}</div>
      ) : (
        <>
          <ul className="grid gap-3">
            {pagedDocs.map(d => <DocCard key={d.id} doc={d} topicId={topic.id} />)}
          </ul>
          {visible.length > PAGE_SIZE && (
            <div className="flex items-center justify-between text-xs text-secondary">
              <span className="tabular-nums text-muted">
                {(safePage - 1) * PAGE_SIZE + 1}-{Math.min(safePage * PAGE_SIZE, visible.length)} / 共 {visible.length} 篇
              </span>
              <div className="flex items-center gap-2">
                <button type="button" disabled={safePage <= 1}
                        onClick={() => setPage(p => Math.max(1, p - 1))}
                        className="px-2 py-1 rounded-md disabled:opacity-40"
                        style={{ background: 'var(--bg-tertiary)' }}>
                  上一页
                </button>
                <span className="tabular-nums">{safePage} / {totalPages}</span>
                <button type="button" disabled={safePage >= totalPages}
                        onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                        className="px-2 py-1 rounded-md disabled:opacity-40"
                        style={{ background: 'var(--bg-tertiary)' }}>
                  下一页
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function DocCard({ doc, topicId }: { doc: ContentDoc; topicId: number }) {
  const navigate = useNavigate();
  const L = useBgLang();
  const earliestMark = doc.publish_targets
    .map(t => t.marked_at).filter(Boolean).sort()[0];
  const ts = earliestMark || doc.review_decision_at;
  const citedEngines = Object.entries(doc.cited_by || {})
    .filter(([, ids]) => ids && ids.length > 0)
    .map(([eng, ids]) => ({ eng, count: ids.length }))
    .sort((a, b) => {
      const ra = ENGINE_ORDER.indexOf(a.eng);
      const rb = ENGINE_ORDER.indexOf(b.eng);
      const ia = ra === -1 ? Number.MAX_SAFE_INTEGER : ra;
      const ib = rb === -1 ? Number.MAX_SAFE_INTEGER : rb;
      return ia - ib || a.eng.localeCompare(b.eng);
    });
  return (
    <li className="p-4 rounded-lg" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
      <div className="flex justify-between mb-2">
        <span className="px-2 py-0.5 rounded text-[10px]"
          style={{ background: doc.source === 'ai' ? 'rgba(59,130,246,0.15)' : 'rgba(168,85,247,0.15)',
                   color: doc.source === 'ai' ? '#3b82f6' : '#a855f7' }}>
          {doc.source === 'ai' ? L.publishedSourceAi : L.publishedSourceUser}
        </span>
        <span className="text-xs text-muted">
          {L.publishedAt} · {ts ? new Date(ts).toLocaleDateString() : '—'}
        </span>
      </div>
      <h3 className="text-base font-medium text-primary mb-2">{doc.title}</h3>
      {doc.summary && <p className="text-sm text-secondary mb-3 line-clamp-2">{doc.summary}</p>}

      {citedEngines.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-3 items-center">
          <span className="text-[10px] text-muted self-center inline-flex items-center gap-1">
            {L.publishedAiCited}<InfoHint text={L.hintPublishedCited} />:
          </span>
          {citedEngines.map(({ eng, count }) => (
            <span key={eng} className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] rounded"
              style={{ background: 'rgba(34,197,94,0.15)', color: '#22c55e' }}>
              {engineLabel(eng)} · {count}
            </span>
          ))}
        </div>
      )}

      {doc.publish_targets.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-3">
          {doc.publish_targets.map((t, i) => (
            <a
              key={i}
              href={t.url || '#'}
              target={t.url ? '_blank' : undefined}
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded"
              style={{ background: 'var(--bg-input)', color: t.url ? 'var(--accent-primary)' : 'var(--text-muted)' }}
            >
              {t.platform} · {t.media}{t.url ? ' ↗' : ''}
            </a>
          ))}
        </div>
      )}

      {doc.source_query_text && (
        <div className="text-xs pt-2 border-t" style={{ borderColor: 'var(--border-color)' }}>
          <span className="text-muted">{L.publishedRelQuery}: </span>
          <button
            type="button"
            onClick={() => navigate(`/brand-growth/queries?topic=${topicId}&q=${encodeURIComponent(doc.source_query_text)}`)}
            className="text-accent hover:underline"
          >
            {doc.source_query_text}{L.publishedRelQueryArrow}
          </button>
        </div>
      )}
    </li>
  );
}
