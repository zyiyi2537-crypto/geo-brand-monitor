import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { BrandGrowthShell, type ShellState } from './shell';
import { aiTelemetryApi, type ResponseRow } from '../../services/aiTelemetryApi';
import { useBgLang, engineLabel } from './lang';
import { InfoHint } from './charts';

const PAGE_SIZE = 10;

export function Responses() {
  const L = useBgLang();
  return (
    <BrandGrowthShell title={L.responsesTitle} breadcrumb={[{ label: L.pageTitle, to: '/brand-growth' }]}>
      {(state) => <Body state={state} />}
    </BrandGrowthShell>
  );
}

function Body({ state }: { state: ShellState }) {
  const { token, topic, period } = state;
  const L = useBgLang();
  const [params] = useSearchParams();
  const engine = params.get('engine') || undefined;
  const queryFilter = params.get('q') || undefined;
  const [rows, setRows] = useState<ResponseRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [page, setPage] = useState(1);

  useEffect(() => {
    if (!topic) return;
    setLoading(true);
    aiTelemetryApi.listTopicResponses(topic.id, token, {
      engine, query: queryFilter, period, limit: 200,
    }).then(setRows).catch(() => setRows([])).finally(() => setLoading(false));
  }, [token, topic?.id, period, engine, queryFilter]);

  // 筛选 / 数据集变 → totalPages 重新计算,safePage 在渲染时夹到合法区间.
  const totalPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const pagedRows = rows.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  if (!topic) return null;

  const posMap: Record<string, string> = {
    lead: L.posLead, body: L.posBody, tail: L.posTail, unknown: L.posUnknown,
  };

  return (
    <div className="grid gap-4">
      <div className="text-xs text-muted flex items-center gap-1.5">
        {L.responsesFilterSummary(engine ? engineLabel(engine) : undefined, queryFilter, period, rows.length)}
        <InfoHint text={L.hintResponses} />
      </div>

      {loading ? (
        <div className="text-xs text-muted text-center py-10">{L.loading}</div>
      ) : (
        <ul className="space-y-2">
          {pagedRows.map(r => (
            <li key={r.id} className="p-3 rounded-lg text-xs"
              style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
              <div className="flex justify-between mb-2">
                <span className="text-primary font-medium">{engineLabel(r.engine)} · {r.query}</span>
                <span className="text-muted">{new Date(r.created_at).toLocaleString()}</span>
              </div>
              <div className="flex gap-2 mb-2 text-[10px]">
                <span className="px-1.5 py-0.5 rounded"
                  style={{ background: r.hit ? 'rgba(34,197,94,0.15)' : 'rgba(148,163,184,0.15)',
                           color: r.hit ? '#15803d' : '#64748b' }}>
                  {r.hit ? `✓ ${r.brand_rank ? `Top${r.brand_rank}` : L.responsesHit}` : `✕ ${L.responsesMiss}`}
                </span>
                {r.mention_position && (
                  <span className="px-1.5 py-0.5 rounded text-muted" style={{ background: 'var(--bg-input)' }}>
                    {posMap[r.mention_position] || r.mention_position}
                  </span>
                )}
                {r.citations.length > 0 && (
                  <span className="px-1.5 py-0.5 rounded text-muted" style={{ background: 'var(--bg-input)' }}>
                    {r.citations.length} {L.responsesCitationsTitle}
                  </span>
                )}
              </div>
              {r.hit_excerpt && (
                <div className="text-secondary mb-2">{r.hit_excerpt}</div>
              )}
              <button
                type="button"
                onClick={() => setExpanded(expanded === r.id ? null : r.id)}
                className="text-xs text-accent hover:underline"
              >
                {expanded === r.id ? L.responsesCollapse : L.responsesExpand}
              </button>
              {expanded === r.id && (
                <div className="mt-2 p-2 rounded text-secondary whitespace-pre-wrap"
                  style={{ background: 'var(--bg-input)', maxHeight: 320, overflowY: 'auto' }}>
                  {r.answer || L.responsesEmpty}
                  {r.citations.length > 0 && (
                    <div className="mt-2 pt-2 border-t text-[10px]" style={{ borderColor: 'var(--border-color)' }}>
                      {L.responsesCitationsTitle}:
                      <ul className="mt-1 space-y-0.5">
                        {r.citations.map((c, i) => (
                          <li key={i}>
                            <a href={c.url} target="_blank" rel="noopener noreferrer"
                              className="text-accent hover:underline">
                              [{i + 1}] {c.domain} · {c.title}
                            </a>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      {!loading && rows.length > PAGE_SIZE && (
        <div className="flex items-center justify-between text-xs text-secondary">
          <span className="tabular-nums text-muted">
            {(safePage - 1) * PAGE_SIZE + 1}-{Math.min(safePage * PAGE_SIZE, rows.length)} / 共 {rows.length} 条
          </span>
          <div className="flex items-center gap-2">
            <button type="button" disabled={safePage <= 1}
                    onClick={() => setPage(Math.max(1, safePage - 1))}
                    className="px-2 py-1 rounded-md disabled:opacity-40"
                    style={{ background: 'var(--bg-tertiary)' }}>
              上一页
            </button>
            <span className="tabular-nums">{safePage} / {totalPages}</span>
            <button type="button" disabled={safePage >= totalPages}
                    onClick={() => setPage(Math.min(totalPages, safePage + 1))}
                    className="px-2 py-1 rounded-md disabled:opacity-40"
                    style={{ background: 'var(--bg-tertiary)' }}>
              下一页
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
