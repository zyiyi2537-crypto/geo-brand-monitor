import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { BrandGrowthShell, type ShellState } from './shell';
import {
  aiTelemetryApi, type TrackingMatrix, type ResponseRow, type EngineId,
  type QueryHitCell,
} from '../../services/aiTelemetryApi';
import { useBgLang, engineLabel, sortEngines } from './lang';
import { InfoHint } from './charts';

type LayerKey = 'all' | 'top1' | 'top3' | 'top5' | 'visible' | 'source';

export function Matrix() {
  const L = useBgLang();
  return (
    <BrandGrowthShell title={L.matrixTitle} breadcrumb={[{ label: L.pageTitle, to: '/brand-growth' }]}>
      {(state) => <Body state={state} />}
    </BrandGrowthShell>
  );
}

function Body({ state }: { state: ShellState }) {
  const { token, topic, period } = state;
  const L = useBgLang();
  const [params, setParams] = useSearchParams();
  const layer = (params.get('layer') || 'all') as LayerKey;
  const qFilter = params.get('q') || '';
  const [matrix, setMatrix] = useState<TrackingMatrix | null>(null);
  const [responses, setResponses] = useState<ResponseRow[]>([]);
  const [drawerCell, setDrawerCell] = useState<{ query: string; engine: EngineId } | null>(null);

  useEffect(() => {
    if (!topic) return;
    aiTelemetryApi.getTrackingMatrix(topic.id, token).then(setMatrix).catch(() => setMatrix(null));
    aiTelemetryApi.listTopicResponses(topic.id, token, { period, limit: 500 })
      .then(setResponses).catch(() => setResponses([]));
  }, [token, topic?.id, period]);

  if (!topic || !matrix) return <div className="text-muted">加载中…</div>;

  // 给每个 cell 算最好的 brand_rank
  const cellRank = new Map<string, number | null>();
  for (const r of responses) {
    if (!r.hit) continue;
    const key = `${r.query}|${r.engine}`;
    const cur = cellRank.get(key);
    const rank = r.brand_rank ?? null;
    if (rank === null) continue;
    if (cur === undefined || cur === null || rank < cur) cellRank.set(key, rank);
  }

  const queries = qFilter ? matrix.queries.filter(q => q === qFilter) : matrix.queries;
  const sortedEngines = sortEngines(matrix.engines);

  const cellColor = (cell: QueryHitCell): string => {
    if (cell.total_hits === 0) {
      if (cell.status === 'pending' || cell.status === 'running') return 'var(--bg-input)';
      return '#94a3b8'; // miss
    }
    const rank = cellRank.get(`${cell.query}|${cell.engine}`);
    if (layer !== 'all') {
      const matches =
        (layer === 'top1' && rank === 1) ||
        (layer === 'top3' && rank !== null && rank !== undefined && rank <= 3) ||
        (layer === 'top5' && rank !== null && rank !== undefined && rank <= 5) ||
        (layer === 'visible') ||
        (layer === 'source');
      if (!matches) return 'rgba(148,163,184,0.2)';
    }
    if (rank === 1) return '#15803d';
    if (rank !== null && rank !== undefined && rank <= 3) return '#22c55e';
    if (rank !== null && rank !== undefined && rank <= 5) return '#86efac';
    return '#bbf7d0';
  };

  const setLayer = (l: LayerKey) => {
    const next = new URLSearchParams(params);
    if (l === 'all') next.delete('layer'); else next.set('layer', l);
    setParams(next, { replace: true });
  };

  const layerName: Record<LayerKey, string> = {
    all: L.layerAll, top1: L.layerTop1, top3: L.layerTop3,
    top5: L.layerTop5, visible: L.layerVisible, source: L.layerSource,
  };

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-3 justify-between">
        <div className="flex items-center gap-2">
          <div className="flex gap-1 p-0.5 rounded" style={{ background: 'var(--bg-input)' }}>
            {(['all', 'top1', 'top3', 'top5', 'visible', 'source'] as LayerKey[]).map(l => (
              <button
                key={l} type="button" onClick={() => setLayer(l)}
                className="px-3 py-1 text-xs rounded"
                style={{
                  background: layer === l ? 'var(--accent-primary)' : 'transparent',
                  color: layer === l ? 'white' : 'var(--text-secondary)',
                }}
              >
                {layerName[l]}
              </button>
            ))}
          </div>
          <InfoHint text={L.hintMatrix} />
        </div>
        <div className="text-xs text-muted">
          {L.matrixHitRate} {matrix.hit_cells_pct.toFixed(1)}% · {matrix.hit_cells} / {matrix.total_cells}
        </div>
      </div>

      <div className="p-3 rounded-lg overflow-x-auto" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
        <table className="text-xs">
          <thead>
            <tr>
              <th className="text-left px-2 py-1.5 sticky left-0" style={{ background: 'var(--bg-card)' }}>{L.queriesColQuery}</th>
              {sortedEngines.map(e => (
                <th key={e} className="px-2 py-1.5 text-muted">{engineLabel(e)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {queries.map(q => (
              <tr key={q}>
                <td className="text-left px-2 py-1.5 text-primary max-w-[260px] truncate sticky left-0"
                  style={{ background: 'var(--bg-card)' }}>{q}</td>
                {sortedEngines.map(e => {
                  const cell = matrix.cells.find(c => c.query === q && c.engine === e);
                  if (!cell) return <td key={e} />;
                  const rank = cellRank.get(`${q}|${e}`);
                  return (
                    <td key={e} className="px-1 py-1">
                      <button
                        type="button"
                        onClick={() => setDrawerCell({ query: q, engine: e })}
                        className="w-10 h-10 rounded text-[10px] font-medium text-white tabular-nums"
                        style={{ background: cellColor(cell) }}
                        title={`${q} × ${e}: hits=${cell.total_hits}/${cell.total_runs}${rank ? ` rank=${rank}` : ''}`}
                      >
                        {cell.total_hits > 0 ? (rank ? `#${rank}` : '✓') : (cell.status === 'pending' ? '·' : '✕')}
                      </button>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {drawerCell && (
        <CellDrawer
          topicId={topic.id} query={drawerCell.query} engine={drawerCell.engine}
          token={token} onClose={() => setDrawerCell(null)}
        />
      )}
    </div>
  );
}

function CellDrawer({ topicId, query, engine, token, onClose }: {
  topicId: number; query: string; engine: EngineId; token: string; onClose: () => void;
}) {
  const L = useBgLang();
  const [rows, setRows] = useState<ResponseRow[]>([]);
  useEffect(() => {
    aiTelemetryApi.listTopicResponses(topicId, token, { query, engine, limit: 20 })
      .then(setRows).catch(() => setRows([]));
  }, [topicId, query, engine, token]);
  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex justify-end" onClick={onClose}>
      <div className="w-full max-w-2xl h-full overflow-y-auto p-4" onClick={e => e.stopPropagation()}
        style={{ background: 'var(--bg-card)' }}>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium text-primary">{query}{L.matrixDrawerTitleSep}{engineLabel(engine)}</h3>
          <button type="button" onClick={onClose} className="text-xs text-muted">{L.matrixDrawerClose}</button>
        </div>
        <ul className="space-y-2">
          {rows.map(r => (
            <li key={r.id} className="p-2 rounded text-xs" style={{ background: 'var(--bg-input)' }}>
              <div className="flex justify-between mb-1 text-muted">
                <span>{new Date(r.created_at).toLocaleString()}</span>
                <span>
                  {r.hit ? `✓ ${r.brand_rank ? `Top${r.brand_rank}` : L.matrixCellHit}` : `✕ ${L.matrixCellMiss}`}
                </span>
              </div>
              {r.hit_excerpt ? (
                <div className="text-secondary">{r.hit_excerpt}</div>
              ) : (
                <div className="text-secondary line-clamp-3">{r.answer.slice(0, 240)}</div>
              )}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
