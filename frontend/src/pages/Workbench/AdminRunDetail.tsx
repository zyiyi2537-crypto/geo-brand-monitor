// 单条 run 详情(表头筛选)— admin 进入查看一次跑批的所有 response
// 路由:/workbench/runs/:runId
import { useEffect, useMemo, useState, type CSSProperties } from 'react';
import { Link, useParams } from 'react-router-dom';
import { aiTelemetryApi, type AdminRun, type ResponseRow } from '../../services/aiTelemetryApi';

type HitFilter = '' | 'hit' | 'miss' | 'error';
type RankFilter = '' | 'top1' | 'top3' | 'top5' | 'ranked' | 'no_rank';

function fmtDateTime(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function StatusChip({ status }: { status: string }) {
  const map: Record<string, { bg: string; fg: string; label: string }> = {
    success: { bg: 'rgba(34,197,94,0.15)', fg: '#15803d', label: '成功' },
    running: { bg: 'rgba(59,130,246,0.15)', fg: '#1d4ed8', label: '运行中' },
    failed: { bg: 'rgba(239,68,68,0.15)', fg: '#b91c1c', label: '失败' },
  };
  const m = map[status] || { bg: 'rgba(148,163,184,0.18)', fg: '#475569', label: status };
  return (
    <span className="px-1.5 py-0.5 rounded text-[10px] font-medium"
      style={{ background: m.bg, color: m.fg }}>
      {m.label}
    </span>
  );
}

export function AdminRunDetail() {
  const { runId: runIdParam } = useParams();
  const runId = Number(runIdParam);
  const token = localStorage.getItem('token') || '';

  const [run, setRun] = useState<AdminRun | null>(null);
  const [rows, setRows] = useState<ResponseRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  // 筛选
  const [engineFilter, setEngineFilter] = useState<string>('');
  const [queryFilter, setQueryFilter] = useState<string>('');
  const [hitFilter, setHitFilter] = useState<HitFilter>('');
  const [rankFilter, setRankFilter] = useState<RankFilter>('');
  const [positionFilter, setPositionFilter] = useState<string>('');

  useEffect(() => {
    if (!Number.isFinite(runId)) return;
    setLoading(true);
    setErr(null);
    Promise.all([
      aiTelemetryApi.adminGetRun(runId, token),
      aiTelemetryApi.listResponses(runId, token),
    ])
      .then(([r, rs]) => { setRun(r); setRows(rs); })
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [runId, token]);

  const engines = useMemo(() => {
    const s = new Set<string>();
    for (const r of rows) s.add(r.engine);
    return Array.from(s).sort();
  }, [rows]);

  const positions = useMemo(() => {
    const s = new Set<string>();
    for (const r of rows) if (r.mention_position) s.add(r.mention_position);
    return Array.from(s).sort();
  }, [rows]);

  const filtered = useMemo(() => {
    const q = queryFilter.trim().toLowerCase();
    return rows.filter(r => {
      if (engineFilter && r.engine !== engineFilter) return false;
      if (q && !(r.query || '').toLowerCase().includes(q)) return false;
      if (hitFilter === 'hit' && !r.hit) return false;
      if (hitFilter === 'miss' && (r.hit || r.error)) return false;
      if (hitFilter === 'error' && !r.error) return false;
      if (positionFilter && r.mention_position !== positionFilter) return false;
      const rank = r.brand_rank;
      if (rankFilter === 'top1' && rank !== 1) return false;
      if (rankFilter === 'top3' && !(typeof rank === 'number' && rank <= 3)) return false;
      if (rankFilter === 'top5' && !(typeof rank === 'number' && rank <= 5)) return false;
      if (rankFilter === 'ranked' && typeof rank !== 'number') return false;
      if (rankFilter === 'no_rank' && typeof rank === 'number') return false;
      return true;
    });
  }, [rows, engineFilter, queryFilter, hitFilter, positionFilter, rankFilter]);

  const inputStyle: CSSProperties = {
    background: 'var(--bg-input)',
    border: '1px solid var(--border-color)',
    color: 'var(--text-primary)',
  };
  const headerFilterStyle: CSSProperties = {
    ...inputStyle,
    fontSize: '10px',
    padding: '2px 6px',
    width: '100%',
    minWidth: 0,
  };

  if (loading) return <div className="text-xs text-muted py-10 text-center">加载中…</div>;
  if (err) return <div className="text-xs py-10 text-center" style={{ color: '#ef4444' }}>{err}</div>;
  if (!run) return <div className="text-xs text-muted py-10 text-center">未找到该跑批</div>;

  return (
    <div className="grid gap-4">
      <div>
        <div className="flex items-center gap-2 text-xs text-muted">
          <Link to="/workbench/runs" className="hover:underline">← 跑批结果</Link>
          <span>·</span>
          <span>Run #{run.run_id}</span>
        </div>
        <h1 className="text-xl font-semibold text-primary mt-1 flex items-center gap-2">
          {run.topic_name}
          <StatusChip status={run.status} />
        </h1>
        <div className="text-xs text-muted mt-1 flex flex-wrap gap-x-4 gap-y-1">
          <span>用户:<span className="text-primary">#{run.user_id} {run.user_email}</span></span>
          <span>品牌词:<span className="text-primary">{run.topic_target || '—'}</span></span>
          <span>开始:<span className="text-primary tabular-nums">{fmtDateTime(run.started_at)}</span></span>
          <span>完成:<span className="text-primary tabular-nums">{fmtDateTime(run.finished_at)}</span></span>
          <span>命中/答复:<span className="text-primary">{run.hit_count}/{run.response_count}</span></span>
          {run.error_count > 0 && (
            <span style={{ color: '#ef4444' }}>错误 {run.error_count}</span>
          )}
          <Link
            to={`/workbench/topics/${run.topic_id}/edit?step=5`}
            className="ml-auto text-accent hover:underline"
          >
            执行策略与规划 →
          </Link>
        </div>
        {run.error && (
          <div className="mt-2 text-xs px-3 py-2 rounded"
            style={{ background: 'rgba(239,68,68,0.1)', color: '#b91c1c' }}>
            跑批错误:{run.error}
          </div>
        )}
      </div>

      <div className="text-xs text-muted">
        {filtered.length} / {rows.length} 条
      </div>

      <div
        className="rounded-lg overflow-auto"
        style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border-color)',
          maxHeight: 'clamp(420px, 70vh, 760px)',
        }}
      >
        <table className="w-full text-xs">
          <thead className="sticky top-0 z-10" style={{ background: 'var(--bg-card)' }}>
            <tr className="text-muted" style={{ boxShadow: 'inset 0 -1px 0 var(--border-color)' }}>
              <th className="text-right px-2 py-2 w-12">序号</th>
              <th className="text-left px-2 py-2 w-28">模型</th>
              <th className="text-left px-2 py-2">问题</th>
              <th className="text-center px-2 py-2 w-20">命中</th>
              <th className="text-center px-2 py-2 w-20">排名</th>
              <th className="text-center px-2 py-2 w-20">段落</th>
              <th className="text-left px-2 py-2">答复 / 错误</th>
            </tr>
            <tr style={{ boxShadow: 'inset 0 -1px 0 var(--border-color)', background: 'var(--bg-card)' }}>
              <th className="px-2 py-1.5" />
              <th className="px-2 py-1.5">
                <select value={engineFilter} onChange={e => setEngineFilter(e.target.value)} style={headerFilterStyle}>
                  <option value="">全部</option>
                  {engines.map(e => <option key={e} value={e}>{e}</option>)}
                </select>
              </th>
              <th className="px-2 py-1.5">
                <input
                  type="text"
                  value={queryFilter}
                  onChange={e => setQueryFilter(e.target.value)}
                  placeholder="搜索问题文本"
                  style={headerFilterStyle}
                />
              </th>
              <th className="px-2 py-1.5">
                <select value={hitFilter} onChange={e => setHitFilter(e.target.value as HitFilter)} style={headerFilterStyle}>
                  <option value="">全部</option>
                  <option value="hit">命中</option>
                  <option value="miss">未命中</option>
                  <option value="error">错误</option>
                </select>
              </th>
              <th className="px-2 py-1.5">
                <select value={rankFilter} onChange={e => setRankFilter(e.target.value as RankFilter)} style={headerFilterStyle}>
                  <option value="">全部</option>
                  <option value="top1">Top1</option>
                  <option value="top3">Top1-3</option>
                  <option value="top5">Top1-5</option>
                  <option value="ranked">有排名</option>
                  <option value="no_rank">未抽出</option>
                </select>
              </th>
              <th className="px-2 py-1.5">
                <select value={positionFilter} onChange={e => setPositionFilter(e.target.value)} style={headerFilterStyle}>
                  <option value="">全部</option>
                  {positions.map(p => <option key={p} value={p}>{p}</option>)}
                </select>
              </th>
              <th className="px-2 py-1.5" />
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr><td colSpan={7} className="px-3 py-10 text-center text-muted">当前筛选无匹配 response</td></tr>
            ) : filtered.map((r, i) => (
              <tr key={r.id} className="border-t align-top" style={{ borderColor: 'var(--border-color)' }}>
                <td className="px-2 py-2 text-right tabular-nums text-muted">{i + 1}</td>
                <td className="px-2 py-2 text-primary">{r.engine}</td>
                <td className="px-2 py-2 text-primary truncate max-w-[280px]" title={r.query}>{r.query}</td>
                <td className="px-2 py-2 text-center">
                  {r.error ? (
                    <span className="px-1 py-0.5 rounded text-[10px]"
                      style={{ background: 'rgba(239,68,68,0.15)', color: '#b91c1c' }}>错</span>
                  ) : r.hit ? (
                    <span className="px-1 py-0.5 rounded text-[10px]"
                      style={{ background: 'rgba(34,197,94,0.15)', color: '#15803d' }}>✓</span>
                  ) : (
                    <span className="text-muted">—</span>
                  )}
                </td>
                <td className="px-2 py-2 text-center tabular-nums text-secondary">
                  {r.brand_rank != null ? r.brand_rank : '—'}
                </td>
                <td className="px-2 py-2 text-center text-secondary">{r.mention_position || '—'}</td>
                <td className="px-2 py-2 text-secondary">
                  {r.error ? (
                    <span style={{ color: '#ef4444' }} title={r.error}>{r.error.slice(0, 240)}</span>
                  ) : (
                    <span title={r.answer}>
                      {(r.answer || '').slice(0, 280) || '(空答复)'}
                      {r.answer && r.answer.length > 280 ? '…' : ''}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
