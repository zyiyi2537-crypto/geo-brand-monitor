import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  aiTelemetryApi,
  type BrowserWorker,
  type WorkerQueueStats,
  type EngineSessionPage,
  type EngineIpGroup,
  type EngineHealth,
  type SelectorProposal,
} from '../../services/aiTelemetryApi';
import { fmtTime } from '../../utils/datetime';

const REFRESH_MS = 10000;
const SESSION_PAGE_SIZE = 20;

export function AdminWorkers() {
  const token = localStorage.getItem('token') || '';
  const { t } = useTranslation();
  const [workers, setWorkers] = useState<BrowserWorker[]>([]);
  const [stats, setStats] = useState<WorkerQueueStats | null>(null);
  const [sessions, setSessions] = useState<EngineSessionPage | null>(null);
  const [ipGroups, setIpGroups] = useState<EngineIpGroup[]>([]);
  const [health, setHealth] = useState<{ checked_at: string | null; engines: EngineHealth[] }>({ checked_at: null, engines: [] });
  const [sessPage, setSessPage] = useState(1);
  const [sessEngine, setSessEngine] = useState('');
  const [sessStatus, setSessStatus] = useState('');
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [busyUid, setBusyUid] = useState<string | null>(null);
  const [authForm, setAuthForm] = useState({ engine: 'deepseek', identifier: '', password: '' });
  const [authBusy, setAuthBusy] = useState(false);
  const [authMsg, setAuthMsg] = useState<string | null>(null);
  const [qr, setQr] = useState<{ open: boolean; engine: string; sid: string | null; img: string | null; status: string }>(
    { open: false, engine: 'wenxin', sid: null, img: null, status: '' });
  const [heal, setHeal] = useState<{ open: boolean; engine: string; loading: boolean; proposal: SelectorProposal | null; raw: string; msg: string; validated: boolean; valText: string }>(
    { open: false, engine: '', loading: false, proposal: null, raw: '', msg: '', validated: false, valText: '' });

  const reload = useCallback(() => {
    Promise.all([
      aiTelemetryApi.adminListWorkers(token),
      aiTelemetryApi.adminWorkersQueueStats(token),
      aiTelemetryApi.adminListEngineSessions(token, sessPage, SESSION_PAGE_SIZE, sessEngine, sessStatus),
      aiTelemetryApi.adminEngineSessionsByIp(token).catch(() => ({ groups: [], ip_count: 0 })),
      aiTelemetryApi.adminEngineHealth(token).catch(() => ({ checked_at: null, engines: [] })),
    ])
      .then(([ws, st, ss, byip, hl]) => {
        setWorkers(ws); setStats(st); setSessions(ss); setIpGroups(byip.groups || []); setHealth(hl); setErr(null);
        // 行被清理后页码可能越界(空页),回第一页
        if (ss.items.length === 0 && ss.page > 1) setSessPage(1);
      })
      .catch(e => setErr(e?.message || 'failed'))
      .finally(() => setLoading(false));
  }, [token, sessPage, sessEngine, sessStatus]);

  const startQr = useCallback(async () => {
    setQr(s => ({ ...s, open: true, sid: null, img: null, status: 'starting' }));
    try {
      const r = await aiTelemetryApi.adminAuthorizeQrStart(token, qr.engine);
      if (r.session_id && r.qr_image) setQr(s => ({ ...s, sid: r.session_id!, img: r.qr_image!, status: 'waiting' }));
      else setQr(s => ({ ...s, status: 'error:' + (r.error || '抓码失败') }));
    } catch (e) { setQr(s => ({ ...s, status: 'error:' + ((e as Error)?.message || '失败') })); }
  }, [token, qr.engine]);

  useEffect(() => {
    if (!qr.open || !qr.sid || qr.status === 'done') return;
    const id = setInterval(async () => {
      try {
        const r = await aiTelemetryApi.adminAuthorizeQrPoll(token, qr.sid!);
        if (r.status === 'done') {
          setQr(s => ({ ...s, status: 'done' }));
          reload();
          setTimeout(() => setQr(s => ({ ...s, open: false })), 1500);
        } else if (r.status === 'expired') {
          setQr(s => ({ ...s, status: 'expired' }));
        } else if (r.qr_image) {
          setQr(s => ({ ...s, img: r.qr_image! }));
        }
      } catch { /* 轮询失败忽略,下次再试 */ }
    }, 2500);
    return () => clearInterval(id);
  }, [qr.open, qr.sid, qr.status, token, reload]);

  const doAuthorize = useCallback(async () => {
    if (!authForm.identifier || !authForm.password) return;
    setAuthBusy(true); setAuthMsg(null);
    try {
      const r = await aiTelemetryApi.adminAuthorizeAccount(token, authForm.engine, authForm.identifier, authForm.password);
      setAuthMsg(r.ok
        ? `✅ 授权成功 ${r.account_handle || ''}${r.uploaded ? ' · 已入池' : ''}`
        : `❌ ${r.error || '失败'}`);
      if (r.ok) { setAuthForm(f => ({ ...f, identifier: '', password: '' })); reload(); }
    } catch (e) {
      setAuthMsg(`❌ ${(e as Error)?.message || '请求失败'}`);
    } finally { setAuthBusy(false); }
  }, [token, authForm, reload]);

  useEffect(() => {
    reload();
    const id = setInterval(reload, REFRESH_MS);
    return () => clearInterval(id);
  }, [reload]);

  const act = async (uid: string, action: 'enable' | 'disable' | 'drain') => {
    setBusyUid(uid);
    try {
      await aiTelemetryApi.adminWorkerAction(uid, action, token);
      reload();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyUid(null);
    }
  };

  const patchSession = async (
    id: number, patch: { disabled?: boolean; daily_cap?: number; priority?: number },
  ) => {
    try {
      await aiTelemetryApi.adminPatchEngineSession(token, id, patch);
      reload();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  const doHeal = async (engine: string) => {
    setHeal({ open: true, engine, loading: true, proposal: null, raw: '', msg: '', validated: false, valText: '' });
    try {
      const r = await aiTelemetryApi.adminHealEngine(token, engine);
      const v = r.validation;
      setHeal(h => ({ ...h, loading: false, proposal: r.proposal, raw: r.llm_raw || '',
        validated: r.validated,
        valText: v ? (r.validated ? `✅ 验证通过 答${v.ans_len}/引${v.cites}` : `❌ 验证失败 ${v.error || '无答案'}`) : '',
        msg: r.probe_error ? `探针异常: ${r.probe_error}` : '' }));
    } catch (e) {
      setHeal(h => ({ ...h, loading: false, msg: `失败: ${(e as Error)?.message || ''}` }));
    }
  };
  const doHealApply = async () => {
    if (!heal.proposal) return;
    setHeal(h => ({ ...h, loading: true }));
    try {
      await aiTelemetryApi.adminHealEngineApply(token, heal.engine, heal.proposal);
      setHeal(h => ({ ...h, loading: false, msg: '✅ 已应用到中心配置,全队下次查询生效' }));
    } catch (e) {
      setHeal(h => ({ ...h, loading: false, msg: `应用失败: ${(e as Error)?.message || ''}` }));
    }
  };

  const engines = stats ? Object.keys(stats.queue).sort() : [];

  return (
    <div className="max-w-[1200px] mx-auto p-6">
      <div className="mb-4">
        <h1 className="text-xl font-semibold text-primary">
          {t('workbench.adminWorkers.heading', { defaultValue: 'Worker 管理' })}
        </h1>
        <p className="text-xs text-muted mt-1">
          {t('workbench.adminWorkers.subtitle', {
            defaultValue: '多机浏览器自动化 worker 自动注册到调度中心,领任务跑批。每 10 秒刷新。',
          })}
        </p>
      </div>

      {/* ── 引擎健康哨兵 ── */}
      {health.engines.length > 0 && (
        <div className="rounded-lg p-3 mb-4 flex flex-wrap items-center gap-2"
             style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
          <span className="text-xs text-secondary font-medium mr-1">
            {t('workbench.adminWorkers.healthTitle', { defaultValue: '引擎健康' })}
          </span>
          {health.engines.map(e => (
            <span key={e.engine}
                  className={`px-2 py-1 rounded-md text-xs ${e.ok ? 'text-emerald-500' : 'text-red-400'}`}
                  style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)' }}
                  title={e.error || ''}>
              {e.ok ? '✅' : '❌'} {e.engine}
              <span className="text-muted ml-1">
                {e.ok
                  ? t('workbench.adminWorkers.healthOk', { defaultValue: '答{{a}}/引{{c}}', a: e.ans_len, c: e.cites })
                  : (e.error || t('workbench.adminWorkers.healthFail', { defaultValue: '异常' }))}
              </span>
              {!e.ok && (
                <button type="button" onClick={() => doHeal(e.engine)}
                        className="ml-2 px-1.5 py-0.5 rounded text-[10px] text-amber-500"
                        style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
                  🔧 {t('workbench.adminWorkers.heal', { defaultValue: '自愈' })}
                </button>
              )}
            </span>
          ))}
          {health.checked_at && (
            <span className="text-[10px] text-muted ml-auto">
              {t('workbench.adminWorkers.healthCheckedAt', { defaultValue: '检测于' })} {fmtTime(health.checked_at, true)}
            </span>
          )}
        </div>
      )}

      {loading ? (
        <div className="text-xs text-muted text-center py-10">{t('common.loading')}</div>
      ) : err ? (
        <div className="text-xs text-red-500">{err}</div>
      ) : (
        <>
          {/* ── 任务队列概览 ── */}
          {stats && (
            <div className="rounded-lg overflow-hidden mb-5"
                 style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
              <div className="px-3 py-2 text-xs text-secondary font-medium border-b"
                   style={{ borderColor: 'var(--border-color)' }}>
                {t('workbench.adminWorkers.queueTitle', { defaultValue: '任务队列(按引擎)' })}
              </div>
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-muted">
                    <th className="text-left px-3 py-2">{t('workbench.adminWorkers.colEngine', { defaultValue: '引擎' })}</th>
                    <th className="text-right px-3 py-2">queued</th>
                    <th className="text-right px-3 py-2">claimed</th>
                    <th className="text-right px-3 py-2">done</th>
                    <th className="text-right px-3 py-2">failed</th>
                    <th className="text-right px-3 py-2">{t('workbench.adminWorkers.colToday', { defaultValue: '今日 / 上限' })}</th>
                  </tr>
                </thead>
                <tbody>
                  {engines.map(e => {
                    const q = stats.queue[e] || {};
                    const cap = stats.daily_cap[e];
                    return (
                      <tr key={e} className="border-t" style={{ borderColor: 'var(--border-color)' }}>
                        <td className="px-3 py-2 text-primary">{e}</td>
                        <td className="px-3 py-2 text-right tabular-nums">{q.queued || 0}</td>
                        <td className="px-3 py-2 text-right tabular-nums">{q.claimed || 0}</td>
                        <td className="px-3 py-2 text-right tabular-nums text-emerald-500">{q.done || 0}</td>
                        <td className="px-3 py-2 text-right tabular-nums text-red-400">{q.failed || 0}</td>
                        <td className="px-3 py-2 text-right tabular-nums text-secondary">
                          {stats.used_today[e] || 0}{cap == null ? '' : ` / ${cap}`}
                        </td>
                      </tr>
                    );
                  })}
                  {engines.length === 0 && (
                    <tr><td colSpan={6} className="px-3 py-4 text-center text-muted">
                      {t('workbench.adminWorkers.queueEmpty', { defaultValue: '队列为空' })}
                    </td></tr>
                  )}
                </tbody>
              </table>
            </div>
          )}

          {/* ── Worker 列表 ── */}
          <div className="rounded-lg overflow-hidden"
               style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
            <table className="w-full text-xs">
              <thead>
                <tr className="text-muted">
                  <th className="text-left px-3 py-2">{t('workbench.adminWorkers.colHost', { defaultValue: '主机' })}</th>
                  <th className="text-left px-3 py-2">{t('workbench.adminWorkers.colExitIp', { defaultValue: '出口 IP' })}</th>
                  <th className="text-left px-3 py-2">{t('workbench.adminWorkers.colEngines', { defaultValue: '引擎' })}</th>
                  <th className="text-left px-3 py-2">{t('workbench.adminWorkers.colStatus', { defaultValue: '状态' })}</th>
                  <th className="text-right px-3 py-2">{t('workbench.adminWorkers.colInflight', { defaultValue: '在跑' })}</th>
                  <th className="text-right px-3 py-2">{t('workbench.adminWorkers.colDoneToday', { defaultValue: '今日完成' })}</th>
                  <th className="text-right px-3 py-2">{t('workbench.adminWorkers.colActions', { defaultValue: '操作' })}</th>
                </tr>
              </thead>
              <tbody>
                {workers.map(w => {
                  const online = w.status === 'online';
                  const brokenEngines = Object.keys(w.breaker || {});
                  return (
                    <tr key={w.worker_uid} className="border-t" style={{ borderColor: 'var(--border-color)' }}>
                      <td className="px-3 py-2 text-primary">
                        {w.hostname || w.label || w.worker_uid.slice(0, 8)}
                        {!w.enabled && (
                          <span className="ml-1 text-[10px] text-red-400">
                            {t('workbench.adminWorkers.disabledBadge', { defaultValue: '已禁用' })}
                          </span>
                        )}
                        {w.raw_status === 'draining' && (
                          <span className="ml-1 text-[10px] text-amber-500">
                            {t('workbench.adminWorkers.drainingBadge', { defaultValue: '排空中' })}
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-secondary tabular-nums">{w.exit_ip || '—'}</td>
                      <td className="px-3 py-2 text-secondary">
                        {(w.engines || []).join(', ') || '—'}
                        {brokenEngines.length > 0 && (
                          <span className="ml-1 text-[10px] text-red-400">
                            ⚡{brokenEngines.join(',')}
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2">
                        <span className={online ? 'text-emerald-500' : 'text-muted'}>
                          ● {online
                            ? t('workbench.adminWorkers.online', { defaultValue: '在线' })
                            : t('workbench.adminWorkers.offline', { defaultValue: '离线' })}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">{w.in_flight}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{w.done_today}</td>
                      <td className="px-3 py-2 text-right whitespace-nowrap">
                        {w.enabled ? (
                          <>
                            <button type="button" disabled={busyUid === w.worker_uid}
                                    onClick={() => act(w.worker_uid, 'drain')}
                                    className="px-2 py-1 rounded-md mr-1 disabled:opacity-40"
                                    style={{ background: 'var(--bg-tertiary)' }}>
                              {t('workbench.adminWorkers.drain', { defaultValue: '排空' })}
                            </button>
                            <button type="button" disabled={busyUid === w.worker_uid}
                                    onClick={() => act(w.worker_uid, 'disable')}
                                    className="px-2 py-1 rounded-md text-red-400 disabled:opacity-40"
                                    style={{ background: 'var(--bg-tertiary)' }}>
                              {t('workbench.adminWorkers.disable', { defaultValue: '禁用' })}
                            </button>
                          </>
                        ) : (
                          <button type="button" disabled={busyUid === w.worker_uid}
                                  onClick={() => act(w.worker_uid, 'enable')}
                                  className="px-2 py-1 rounded-md text-emerald-500 disabled:opacity-40"
                                  style={{ background: 'var(--bg-tertiary)' }}>
                            {t('workbench.adminWorkers.enable', { defaultValue: '启用' })}
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
                {workers.length === 0 && (
                  <tr><td colSpan={7} className="px-3 py-6 text-center text-muted">
                    {t('workbench.adminWorkers.noWorkers', { defaultValue: '暂无 worker 接入' })}
                  </td></tr>
                )}
              </tbody>
            </table>
          </div>

          {/* ── 添加账号·密码授权 ── */}
          <div className="rounded-lg overflow-hidden mt-5 px-3 py-3"
               style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
            <div className="text-xs text-secondary font-medium mb-2">
              {t('workbench.adminWorkers.addAccount', { defaultValue: '添加账号 · 密码自动授权' })}
              <span className="text-muted ml-2">{t('workbench.adminWorkers.addAccountHint', { defaultValue: '(填账号密码,服务端自动登录抓登录态入池;目前支持 deepseek)' })}</span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <select value={authForm.engine}
                      onChange={e => setAuthForm(f => ({ ...f, engine: e.target.value }))}
                      className="px-2 py-1 rounded-md text-xs"
                      style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)' }}>
                <option value="deepseek">deepseek</option>
              </select>
              <input value={authForm.identifier} placeholder="账号(邮箱/手机号)"
                     onChange={e => setAuthForm(f => ({ ...f, identifier: e.target.value }))}
                     className="px-2 py-1 rounded-md text-xs" style={{ width: 220, background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)' }} />
              <input value={authForm.password} type="password" placeholder="密码"
                     onChange={e => setAuthForm(f => ({ ...f, password: e.target.value }))}
                     className="px-2 py-1 rounded-md text-xs" style={{ width: 160, background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)' }} />
              <button onClick={doAuthorize} disabled={authBusy || !authForm.identifier || !authForm.password}
                      className="px-3 py-1 rounded-md text-xs"
                      style={{ background: 'var(--accent-color, #2563eb)', color: '#fff', opacity: authBusy ? 0.6 : 1 }}>
                {authBusy
                  ? t('workbench.adminWorkers.authorizing', { defaultValue: '授权中…' })
                  : t('workbench.adminWorkers.authorize', { defaultValue: '授权' })}
              </button>
              {authMsg && <span className="text-xs text-muted">{authMsg}</span>}
            </div>
            <div className="flex flex-wrap items-center gap-2 mt-2">
              <span className="text-xs text-muted">{t('workbench.adminWorkers.qrAuth', { defaultValue: '扫码授权(qwen/文心/元宝):' })}</span>
              <select value={qr.engine}
                      onChange={e => setQr(s => ({ ...s, engine: e.target.value }))}
                      className="px-2 py-1 rounded-md text-xs"
                      style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)' }}>
                <option value="wenxin">wenxin</option>
                <option value="yuanbao">yuanbao</option>
                <option value="qwen">qwen</option>
              </select>
              <button onClick={startQr}
                      className="px-3 py-1 rounded-md text-xs"
                      style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }}>
                {t('workbench.adminWorkers.qrStart', { defaultValue: '扫码授权' })}
              </button>
            </div>
          </div>

          {/* ── 扫码授权弹窗 ── */}
          {qr.open && (
            <div onClick={() => setQr(s => ({ ...s, open: false }))}
                 style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.5)', zIndex: 50,
                          display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <div onClick={e => e.stopPropagation()} className="rounded-lg p-5 text-center"
                   style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)', width: 300 }}>
                <div className="text-sm text-primary mb-3">
                  {t('workbench.adminWorkers.qrScanTip', { defaultValue: '{{engine}} 扫码登录', engine: qr.engine })}
                </div>
                {qr.status === 'starting' && <div className="text-xs text-muted py-10">{t('workbench.adminWorkers.qrLoading', { defaultValue: '打开登录页、抓二维码中…' })}</div>}
                {qr.img && qr.status !== 'done' && qr.status !== 'expired' && (
                  <img src={qr.img} alt="qr" style={{ width: 200, height: 200, objectFit: 'contain', margin: '0 auto', background: '#fff', borderRadius: 8 }} />
                )}
                {qr.status === 'waiting' && <div className="text-xs text-muted mt-3">{t('workbench.adminWorkers.qrWaiting', { defaultValue: '请用手机 App 扫码并确认登录…' })}</div>}
                {qr.status === 'done' && <div className="text-emerald-500 py-10">✅ {t('workbench.adminWorkers.qrDone', { defaultValue: '授权成功,已入池' })}</div>}
                {qr.status === 'expired' && <div className="text-red-400 py-10">{t('workbench.adminWorkers.qrExpired', { defaultValue: '二维码已过期,请重新点击授权' })}</div>}
                {qr.status.startsWith('error') && <div className="text-red-400 py-10 text-xs">{qr.status}</div>}
                <button onClick={() => setQr(s => ({ ...s, open: false }))}
                        className="px-4 py-1 rounded-md text-xs mt-4"
                        style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)' }}>
                  {t('workbench.adminWorkers.close', { defaultValue: '关闭' })}
                </button>
              </div>
            </div>
          )}

          {/* ── 按出口 IP 分布 ── */}
          {ipGroups.length > 0 && (
            <div className="rounded-lg overflow-hidden mt-5"
                 style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
              <div className="px-3 py-2 text-xs text-secondary font-medium border-b"
                   style={{ borderColor: 'var(--border-color)' }}>
                {t('workbench.adminWorkers.byIpTitle', { defaultValue: '按出口 IP 分布(密度越高越易被风控)' })}
              </div>
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-muted">
                    <th className="text-left px-3 py-2">{t('workbench.adminWorkers.colExitIp', { defaultValue: '出口 IP' })}</th>
                    <th className="text-left px-3 py-2">{t('workbench.adminWorkers.colEngine', { defaultValue: '引擎' })}</th>
                    <th className="text-right px-3 py-2">{t('workbench.adminWorkers.colIpAccounts', { defaultValue: '该引擎账号数' })}</th>
                    <th className="text-right px-3 py-2">{t('workbench.adminWorkers.colUsedToday', { defaultValue: '今日' })}</th>
                    <th className="text-right px-3 py-2">{t('workbench.adminWorkers.colIpTotal', { defaultValue: '该IP总账号(密度)' })}</th>
                  </tr>
                </thead>
                <tbody>
                  {ipGroups.map((g, i) => (
                    <tr key={`${g.exit_ip}-${g.engine}-${i}`} className="border-t" style={{ borderColor: 'var(--border-color)' }}>
                      <td className="px-3 py-2 text-primary tabular-nums">{g.exit_ip}</td>
                      <td className="px-3 py-2 text-secondary">{g.engine}</td>
                      <td className="px-3 py-2 text-right tabular-nums text-secondary">{g.accounts}</td>
                      <td className="px-3 py-2 text-right tabular-nums text-secondary">{g.used_today}</td>
                      <td className={`px-3 py-2 text-right tabular-nums ${g.ip_account_total >= 6 ? 'text-amber-500' : 'text-secondary'}`}>
                        {g.ip_account_total}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* ── 账号池(登录态)── */}
          <div className="rounded-lg overflow-hidden mt-5"
               style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
            <div className="flex items-center px-3 py-2 text-xs text-secondary font-medium border-b"
                 style={{ borderColor: 'var(--border-color)' }}>
              {t('workbench.adminWorkers.poolTitle', { defaultValue: '账号池(登录态)' })}
              <span className="text-muted ml-2">
                {t('workbench.adminWorkers.poolActive', {
                  defaultValue: '可用 {{n}} / 共 {{total}}',
                  n: sessions?.active_total ?? 0,
                  total: sessions?.grand_total ?? 0,
                })}
              </span>
              {(sessions?.quarantined_total ?? 0) > 0 && (
                <span className="text-red-400 ml-2" title={Object.entries(sessions?.quarantined_by_engine ?? {}).map(([e, c]) => `${e}:${c}`).join(' ')}>
                  {t('workbench.adminWorkers.poolQuarantined', {
                    defaultValue: '⚠️ 掉线 {{n}} 需处理',
                    n: sessions?.quarantined_total ?? 0,
                  })}
                </span>
              )}
              <span className="ml-auto flex items-center gap-2 font-normal">
                <select value={sessEngine}
                        onChange={e => { setSessEngine(e.target.value); setSessPage(1); }}
                        className="px-2 py-1 rounded-md text-xs"
                        style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)' }}>
                  <option value="">{t('workbench.adminWorkers.filterAllEngines', { defaultValue: '全部引擎' })}</option>
                  {(sessions?.engines ?? []).map(e => <option key={e} value={e}>{e}</option>)}
                </select>
                <select value={sessStatus}
                        onChange={e => { setSessStatus(e.target.value); setSessPage(1); }}
                        className="px-2 py-1 rounded-md text-xs"
                        style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)' }}>
                  <option value="">{t('workbench.adminWorkers.filterAllStatus', { defaultValue: '全部状态' })}</option>
                  <option value="active">{t('workbench.adminWorkers.statusActive', { defaultValue: '可用' })}</option>
                  <option value="expired">{t('workbench.adminWorkers.statusExpired', { defaultValue: '已过期' })}</option>
                  <option value="quarantined">{t('workbench.adminWorkers.statusQuarantined', { defaultValue: '已隔离' })}</option>
                </select>
              </span>
            </div>
            <table className="w-full text-xs">
              <thead>
                <tr className="text-muted">
                  <th className="text-left px-3 py-2">{t('workbench.adminWorkers.colEngine', { defaultValue: '引擎' })}</th>
                  <th className="text-left px-3 py-2">{t('workbench.adminWorkers.colLabel', { defaultValue: '标识' })}</th>
                  <th className="text-left px-3 py-2">{t('workbench.adminWorkers.colStatus', { defaultValue: '状态' })}</th>
                  <th className="text-right px-3 py-2">{t('workbench.adminWorkers.colUseCount', { defaultValue: '用量' })}</th>
                  <th className="text-right px-3 py-2">{t('workbench.adminWorkers.colCaptcha', { defaultValue: '验证码' })}</th>
                  <th className="text-left px-3 py-2">{t('workbench.adminWorkers.colLastUsed', { defaultValue: '最后使用' })}</th>
                  <th className="text-left px-3 py-2">{t('workbench.adminWorkers.colExpires', { defaultValue: '过期' })}</th>
                  <th className="text-right px-3 py-2">{t('workbench.adminWorkers.colQuota', { defaultValue: '今日配额' })}</th>
                  <th className="text-left px-3 py-2">{t('workbench.adminWorkers.colAuth', { defaultValue: '授权' })}</th>
                  <th className="text-left px-3 py-2">{t('workbench.adminWorkers.colExitIp', { defaultValue: '出口 IP' })}</th>
                  <th className="text-right px-3 py-2">{t('workbench.adminWorkers.colPriority', { defaultValue: '优先级' })}</th>
                  <th className="text-left px-3 py-2">{t('workbench.adminWorkers.colActions', { defaultValue: '操作' })}</th>
                </tr>
              </thead>
              <tbody>
                {(sessions?.items ?? []).map(s => {
                  const color = s.status === 'active' ? 'text-emerald-500'
                    : s.status === 'quarantined' ? 'text-red-400' : 'text-muted';
                  const statusText = s.status === 'active'
                    ? t('workbench.adminWorkers.statusActive', { defaultValue: '可用' })
                    : s.status === 'expired'
                      ? t('workbench.adminWorkers.statusExpired', { defaultValue: '已过期' })
                      : s.status === 'quarantined'
                        ? t('workbench.adminWorkers.statusQuarantined', { defaultValue: '已隔离' })
                        : s.status;
                  const fmt = (d: string | null) => d ? fmtTime(d, false) : '—';
                  return (
                    <tr key={s.id} className="border-t" style={{ borderColor: 'var(--border-color)' }}>
                      <td className="px-3 py-2 text-primary">{s.engine}</td>
                      <td className="px-3 py-2 text-secondary">
                        {s.account_handle || s.label || `#${s.id}`}
                        {s.account_handle && s.label && (
                          <span className="text-[10px] text-muted ml-1">({s.label})</span>
                        )}
                      </td>
                      <td className={`px-3 py-2 ${color}`}>
                        {statusText}
                        {s.last_fail_type && s.status !== 'active' && (
                          <span className="text-[10px] text-muted ml-1">({s.last_fail_type})</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">{s.use_count}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{s.captcha_count}</td>
                      <td className="px-3 py-2 text-secondary tabular-nums">{fmt(s.last_used_at)}</td>
                      <td className="px-3 py-2 text-secondary tabular-nums">{fmt(s.expires_at)}</td>
                      <td className="px-3 py-2 text-right tabular-nums text-secondary">
                        {s.effective_cap === 0
                          ? `${s.used_today ?? 0} / ${t('workbench.adminWorkers.unlimited', { defaultValue: '不限' })}`
                          : `${s.remaining ?? 0} / ${s.effective_cap ?? 0}`}
                        {s.daily_cap != null && (
                          <span className="text-[10px] text-amber-500 ml-1">●</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-secondary">{s.auth_type || '—'}</td>
                      <td className="px-3 py-2 text-secondary tabular-nums">
                        {s.exit_ip || '—'}
                        {s.rate_limited && (
                          <span className="text-[10px] text-amber-500 ml-1">
                            {t('workbench.adminWorkers.cooling', { defaultValue: '冷却中' })}
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-secondary">{s.priority ?? 50}</td>
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-1">
                          <button type="button"
                            onClick={() => patchSession(s.id, { disabled: !s.disabled })}
                            className="px-1.5 py-0.5 rounded text-[11px]"
                            style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)' }}>
                            {s.disabled
                              ? t('workbench.adminWorkers.actEnable', { defaultValue: '启用' })
                              : t('workbench.adminWorkers.actDisable', { defaultValue: '停用' })}
                          </button>
                          <button type="button"
                            onClick={() => {
                              const cur = s.daily_cap != null ? String(s.daily_cap) : '';
                              const v = window.prompt(
                                t('workbench.adminWorkers.promptCap', { defaultValue: '单账号日上限(空=用引擎默认,0=不限)' }), cur);
                              if (v === null) return;
                              const n = v.trim() === '' ? -1 : parseInt(v, 10);
                              if (!Number.isNaN(n)) patchSession(s.id, { daily_cap: n });
                            }}
                            className="px-1.5 py-0.5 rounded text-[11px]"
                            style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)' }}>
                            {t('workbench.adminWorkers.actCap', { defaultValue: '改上限' })}
                          </button>
                          <button type="button"
                            onClick={() => {
                              const v = window.prompt(
                                t('workbench.adminWorkers.promptPriority', { defaultValue: '优先级(0-100,低值优先)' }), String(s.priority ?? 50));
                              if (v === null) return;
                              const n = parseInt(v, 10);
                              if (!Number.isNaN(n)) patchSession(s.id, { priority: n });
                            }}
                            className="px-1.5 py-0.5 rounded text-[11px]"
                            style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)' }}>
                            {t('workbench.adminWorkers.actPriority', { defaultValue: '优先级' })}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
                {(sessions?.total ?? 0) === 0 && (
                  <tr><td colSpan={12} className="px-3 py-6 text-center text-muted">
                    {(sessEngine || sessStatus)
                      ? t('workbench.adminWorkers.noFilterMatch', { defaultValue: '没有匹配当前筛选的账号' })
                      : t('workbench.adminWorkers.noSessions', { defaultValue: '账号池为空,用浏览器扩展上传登录态' })}
                  </td></tr>
                )}
              </tbody>
            </table>
            {(sessions?.total ?? 0) > SESSION_PAGE_SIZE && (
              <div className="flex items-center justify-end gap-2 px-3 py-2 text-xs border-t"
                   style={{ borderColor: 'var(--border-color)' }}>
                <button type="button" disabled={sessPage <= 1}
                        onClick={() => setSessPage(p => p - 1)}
                        className="px-2 py-1 rounded-md disabled:opacity-40"
                        style={{ background: 'var(--bg-tertiary)' }}>
                  {t('workbench.adminWorkers.prevPage', { defaultValue: '上一页' })}
                </button>
                <span className="text-muted tabular-nums">
                  {sessPage} / {Math.max(1, Math.ceil((sessions?.total ?? 0) / SESSION_PAGE_SIZE))}
                </span>
                <button type="button"
                        disabled={sessPage >= Math.ceil((sessions?.total ?? 0) / SESSION_PAGE_SIZE)}
                        onClick={() => setSessPage(p => p + 1)}
                        className="px-2 py-1 rounded-md disabled:opacity-40"
                        style={{ background: 'var(--bg-tertiary)' }}>
                  {t('workbench.adminWorkers.nextPage', { defaultValue: '下一页' })}
                </button>
              </div>
            )}
          </div>
        </>
      )}

      {/* ── 自愈提议弹窗 ── */}
      {heal.open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.5)' }}>
          <div className="rounded-lg p-5 max-w-[560px] w-full mx-4"
               style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
            <div className="flex items-center mb-3">
              <span className="text-sm font-medium text-primary">
                🔧 {t('workbench.adminWorkers.healTitle', { defaultValue: '引擎自愈' })} — {heal.engine}
              </span>
              <button onClick={() => setHeal(h => ({ ...h, open: false }))}
                      className="ml-auto text-muted text-xs">✕</button>
            </div>
            {heal.loading && <div className="text-xs text-muted py-6 text-center">{t('workbench.adminWorkers.healRunning', { defaultValue: '探测页面 + LLM 提议选择器中(约 1 分钟)…' })}</div>}
            {heal.msg && <div className="text-xs text-amber-500 mb-2">{heal.msg}</div>}
            {heal.proposal && (
              <div className="text-xs">
                <div className="text-muted mb-2">{t('workbench.adminWorkers.healProposalHint', { defaultValue: 'LLM 提议的新选择器(审阅后应用,将写入中心配置、全队生效):' })}</div>
                <pre className="rounded-md p-3 overflow-auto max-h-[240px] text-secondary"
                     style={{ background: 'var(--bg-tertiary)' }}>
                  {JSON.stringify(heal.proposal, null, 2)}
                </pre>
                {heal.valText && (
                  <div className={`mt-2 ${heal.validated ? 'text-emerald-500' : 'text-red-400'}`}>{heal.valText}</div>
                )}
                {!heal.validated && (
                  <div className="text-[10px] text-muted mt-1">
                    {t('workbench.adminWorkers.healNotValidated', { defaultValue: '未通过验证(用提议选择器跑 canary 没出答案),不建议应用' })}
                  </div>
                )}
                <div className="flex items-center gap-2 mt-3">
                  <button type="button" onClick={doHealApply} disabled={heal.loading || !heal.validated}
                          className="px-3 py-1 rounded-md text-xs text-emerald-500 disabled:opacity-40"
                          style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)' }}>
                    {t('workbench.adminWorkers.healApply', { defaultValue: '应用到中心配置' })}
                  </button>
                  <button type="button" onClick={() => setHeal(h => ({ ...h, open: false }))}
                          className="px-3 py-1 rounded-md text-xs text-muted"
                          style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)' }}>
                    {t('workbench.adminWorkers.close', { defaultValue: '关闭' })}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
