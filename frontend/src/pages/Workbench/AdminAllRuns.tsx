// admin 跨用户 / 跨主题 / 每日跑批结果总览
// 路由:/workbench/runs
import { useCallback, useEffect, useMemo, useState, type CSSProperties } from 'react';
import { Link } from 'react-router-dom';
import { aiTelemetryApi, type AdminAccount, type AdminRun } from '../../services/aiTelemetryApi';

function today(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${dd}`;
}

function fmtDateTime(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

const PAGE_SIZE = 10;

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

export function AdminAllRuns() {
  const token = localStorage.getItem('token') || '';
  const [day, setDay] = useState<string>(today());
  const [userId, setUserId] = useState<number | ''>('');
  const [status, setStatus] = useState<string>('');
  const [accounts, setAccounts] = useState<AdminAccount[]>([]);
  const [runs, setRuns] = useState<AdminRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [page, setPage] = useState(1);

  useEffect(() => {
    aiTelemetryApi.adminListAccounts(token)
      .then(setAccounts)
      .catch(() => setAccounts([]));
  }, [token]);

  const load = useCallback(() => {
    setLoading(true);
    setErr(null);
    aiTelemetryApi.adminListRuns(token, {
      day: day || undefined,
      userId: userId === '' ? undefined : userId,
      status: status || undefined,
      limit: 200,
    })
      .then(setRuns)
      .catch(e => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [token, day, userId, status]);

  useEffect(() => { load(); }, [load]);

  // runs 缩短 / 筛选变后总页数变 → safePage 在渲染时夹到合法区间.
  const totalPages = Math.max(1, Math.ceil(runs.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const pagedRuns = runs.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  const totals = useMemo(() => {
    let resp = 0, hit = 0;
    for (const r of runs) { resp += r.response_count; hit += r.hit_count; }
    return { runs: runs.length, resp, hit };
  }, [runs]);

  const inputStyle: CSSProperties = {
    background: 'var(--bg-input)',
    border: '1px solid var(--border-color)',
    color: 'var(--text-primary)',
  };

  return (
    <div className="grid gap-4">
      <div>
        <h1 className="text-xl font-semibold text-primary">跑批结果</h1>
        <p className="text-xs text-muted mt-1">
          跨用户 · 跨主题 · 按天列出每次跑批的命中统计;点 Run ID 进详情看每条 (模型 × 问题) 答复。
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs">
        <label className="text-muted">日期</label>
        <input
          type="date"
          value={day}
          onChange={e => setDay(e.target.value)}
          className="px-2 py-1 rounded-md"
          style={{ ...inputStyle, minWidth: 140 }}
        />
        <button
          type="button"
          onClick={() => setDay('')}
          className="text-xs text-accent hover:underline"
          title="清空日期 = 列最近 200 条"
        >
          清空日期
        </button>

        <span className="mx-2 text-muted">·</span>

        <label className="text-muted">用户</label>
        <select
          value={userId === '' ? '' : String(userId)}
          onChange={e => setUserId(e.target.value === '' ? '' : Number(e.target.value))}
          className="px-2 py-1 rounded-md"
          style={{ ...inputStyle, minWidth: 200 }}
        >
          <option value="">全部用户</option>
          {accounts.map(a => (
            <option key={a.id} value={a.id}>
              #{a.id} {a.email}{a.is_admin ? ' (admin)' : ''}
            </option>
          ))}
        </select>

        <label className="text-muted">状态</label>
        <select
          value={status}
          onChange={e => setStatus(e.target.value)}
          className="px-2 py-1 rounded-md"
          style={{ ...inputStyle, minWidth: 100 }}
        >
          <option value="">全部</option>
          <option value="success">成功</option>
          <option value="running">运行中</option>
          <option value="failed">失败</option>
        </select>

        <button
          type="button"
          onClick={load}
          className="ml-2 px-2 py-1 rounded-md text-xs"
          style={{ ...inputStyle }}
        >
          刷新
        </button>

        <span className="ml-auto text-muted">
          {totals.runs} 次跑批 · 共 {totals.resp} 条答复 · 命中 {totals.hit}
        </span>
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
              <th className="text-right px-2 py-2 w-16">Run ID</th>
              <th className="text-left px-2 py-2">用户</th>
              <th className="text-left px-2 py-2">主题</th>
              <th className="text-left px-2 py-2">品牌词</th>
              <th className="text-left px-2 py-2 w-40">开始时间</th>
              <th className="text-left px-2 py-2 w-40">完成时间</th>
              <th className="text-center px-2 py-2 w-16">状态</th>
              <th className="text-right px-2 py-2 w-20">命中/答复</th>
              <th className="text-right px-2 py-2 w-14">错误</th>
              <th className="text-right px-2 py-2 w-20"></th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={10} className="px-3 py-10 text-center text-muted">加载中…</td></tr>
            ) : err ? (
              <tr><td colSpan={10} className="px-3 py-10 text-center" style={{ color: '#ef4444' }}>{err}</td></tr>
            ) : runs.length === 0 ? (
              <tr><td colSpan={10} className="px-3 py-10 text-center text-muted">没有符合条件的跑批</td></tr>
            ) : pagedRuns.map(r => (
              <tr key={r.run_id} className="border-t" style={{ borderColor: 'var(--border-color)' }}>
                <td className="px-2 py-2 text-right tabular-nums">
                  <Link to={`/workbench/runs/${r.run_id}`} className="text-accent hover:underline">
                    #{r.run_id}
                  </Link>
                </td>
                <td className="px-2 py-2 text-primary truncate max-w-[200px]" title={r.user_email}>
                  <span className="text-muted tabular-nums">#{r.user_id}</span> {r.user_email}
                </td>
                <td className="px-2 py-2 text-primary truncate max-w-[200px]" title={r.topic_name}>
                  {r.topic_name}
                </td>
                <td className="px-2 py-2 text-secondary truncate max-w-[160px]" title={r.topic_target}>
                  {r.topic_target || '—'}
                </td>
                <td className="px-2 py-2 text-secondary tabular-nums">{fmtDateTime(r.started_at)}</td>
                <td className="px-2 py-2 text-secondary tabular-nums">{fmtDateTime(r.finished_at)}</td>
                <td className="px-2 py-2 text-center"><StatusChip status={r.status} /></td>
                <td className="px-2 py-2 text-right tabular-nums text-primary">
                  {r.hit_count}/{r.response_count}
                </td>
                <td className="px-2 py-2 text-right tabular-nums"
                    style={r.error_count > 0 ? { color: '#ef4444' } : undefined}>
                  {r.error_count}
                </td>
                <td className="px-2 py-2 text-right">
                  <Link to={`/workbench/runs/${r.run_id}`} className="text-xs text-accent hover:underline">
                    查看详情
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {runs.length > PAGE_SIZE && (
        <div className="flex items-center justify-between text-xs text-secondary">
          <span className="tabular-nums text-muted">
            {(safePage - 1) * PAGE_SIZE + 1}-{Math.min(safePage * PAGE_SIZE, runs.length)} / 共 {runs.length} 条
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
