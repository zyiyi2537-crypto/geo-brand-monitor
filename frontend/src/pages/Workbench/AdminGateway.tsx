import { Fragment, useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  aiTelemetryApi,
  type GatewayTenant,
  type GatewayJob,
} from '../../services/aiTelemetryApi';
import { fmtTime } from '../../utils/datetime';

const REFRESH_MS = 15000;
const ALL_ENGINES = ['deepseek', 'qwen', 'wenxin', 'yuanbao', 'doubao',
  'chatgpt', 'claude', 'gemini', 'copilot', 'grok'];

const card: React.CSSProperties = { background: 'var(--bg-card)', border: '1px solid var(--border-color)' };

export function AdminGateway() {
  const token = localStorage.getItem('token') || '';
  const { t } = useTranslation();
  const [tenants, setTenants] = useState<GatewayTenant[]>([]);
  const [jobs, setJobs] = useState<GatewayJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [issuedKey, setIssuedKey] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [openJob, setOpenJob] = useState<number | null>(null);  // 展开看返回内容的 job id

  // 新建租户表单
  const [name, setName] = useState('');
  const [tier, setTier] = useState('free');
  const [engines, setEngines] = useState<string[]>([]);
  const [quota, setQuota] = useState(20);

  const reload = useCallback(() => {
    Promise.all([
      aiTelemetryApi.adminGatewayTenants(token),
      aiTelemetryApi.adminGatewayJobs(token, undefined, 50),
    ])
      .then(([ts, js]) => { setTenants(ts.tenants); setJobs(js.jobs); setErr(null); })
      .catch(e => setErr(e?.message || 'failed'))
      .finally(() => setLoading(false));
  }, [token]);

  useEffect(() => {
    reload();
    const id = setInterval(reload, REFRESH_MS);
    return () => clearInterval(id);
  }, [reload]);

  const create = async () => {
    if (!name.trim()) return;
    try {
      const r = await aiTelemetryApi.adminGatewayCreateTenant(
        { name: name.trim(), tier, engines, daily_quota_default: quota }, token);
      setIssuedKey(r.api_key);
      setShowCreate(false); setName(''); setEngines([]); setTier('free'); setQuota(20);
      reload();
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };

  const topUp = async (tid: number) => {
    const v = window.prompt(t('workbench.adminGateway.topupPrompt', { defaultValue: '充值额度(credits),可填负数扣减:' }), '100');
    if (v == null) return;
    const amount = parseInt(v, 10);
    if (!Number.isFinite(amount) || amount === 0) return;
    try { await aiTelemetryApi.adminGatewayTopUp(tid, amount, token); reload(); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };

  const editQuota = async (tt: GatewayTenant) => {
    const v = window.prompt(t('workbench.adminGateway.quotaPrompt', { defaultValue: '每引擎默认日配额:' }), String(tt.daily_quota_default));
    if (v == null) return;
    const n = parseInt(v, 10);
    if (!Number.isFinite(n)) return;
    try { await aiTelemetryApi.adminGatewayUpdateTenant(tt.id, { daily_quota_default: n }, token); reload(); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };

  const toggleStatus = async (tt: GatewayTenant) => {
    const next = tt.status === 'active' ? 'suspended' : 'active';
    try { await aiTelemetryApi.adminGatewayUpdateTenant(tt.id, { status: next }, token); reload(); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };

  const reissue = async (tid: number) => {
    if (!window.confirm(t('workbench.adminGateway.reissueConfirm', { defaultValue: '给该租户新发一把 API Key?旧 key 仍有效。' }))) return;
    try { const r = await aiTelemetryApi.adminGatewayReissueKey(tid, token); setIssuedKey(r.api_key); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };

  const tierLabel = (x: string) => x === 'pro'
    ? t('workbench.adminGateway.tierPro', { defaultValue: '专业' })
    : t('workbench.adminGateway.tierFree', { defaultValue: '免费' });

  const totalCallsToday = tenants.reduce((s, x) => s + x.calls_today, 0);
  const totalCredits = tenants.reduce((s, x) => s + x.credit_balance, 0);

  return (
    <div className="max-w-[1200px] mx-auto p-6">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-primary">
            {t('workbench.adminGateway.heading', { defaultValue: '对外网关运营' })}
          </h1>
          <p className="text-xs text-muted mt-1">
            {t('workbench.adminGateway.subtitle', { defaultValue: '管理调用浏览器自动化能力的外部租户:配额、额度、调用流水。每 15 秒刷新。' })}
          </p>
        </div>
        <button className="text-xs px-3 py-1.5 rounded text-white" style={{ background: 'var(--accent, #2563eb)' }}
                onClick={() => setShowCreate(v => !v)}>
          {t('workbench.adminGateway.newTenant', { defaultValue: '+ 新建租户' })}
        </button>
      </div>

      {issuedKey && (
        <div className="rounded-lg p-3 mb-4 text-xs" style={{ background: 'var(--bg-card)', border: '1px solid var(--accent, #2563eb)' }}>
          <div className="text-primary font-medium mb-1">
            {t('workbench.adminGateway.keyOnce', { defaultValue: 'API Key 已生成(仅此一次显示,请复制保存):' })}
          </div>
          <code className="text-primary break-all">{issuedKey}</code>
          <div className="mt-2 flex gap-2">
            <button className="px-2 py-1 rounded" style={card} onClick={() => navigator.clipboard?.writeText(issuedKey)}>
              {t('common.copy', { defaultValue: '复制' })}
            </button>
            <button className="px-2 py-1 rounded" style={card} onClick={() => setIssuedKey(null)}>
              {t('common.close', { defaultValue: '关闭' })}
            </button>
          </div>
        </div>
      )}

      {showCreate && (
        <div className="rounded-lg p-4 mb-4 text-xs" style={card}>
          <div className="grid grid-cols-2 gap-3 mb-3">
            <label className="flex flex-col gap-1">
              <span className="text-muted">{t('workbench.adminGateway.colName', { defaultValue: '租户名称' })}</span>
              <input className="px-2 py-1 rounded text-primary" style={card} value={name} onChange={e => setName(e.target.value)} />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-muted">{t('workbench.adminGateway.colTier', { defaultValue: '档位' })}</span>
              <select className="px-2 py-1 rounded text-primary" style={card} value={tier} onChange={e => setTier(e.target.value)}>
                <option value="free">{tierLabel('free')}</option>
                <option value="pro">{tierLabel('pro')}</option>
              </select>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-muted">{t('workbench.adminGateway.colQuota', { defaultValue: '每引擎默认日配额' })}</span>
              <input type="number" className="px-2 py-1 rounded text-primary" style={card} value={quota} onChange={e => setQuota(parseInt(e.target.value, 10) || 0)} />
            </label>
          </div>
          <div className="mb-3">
            <span className="text-muted">{t('workbench.adminGateway.colEngines', { defaultValue: '引擎白名单(不选=全放开)' })}</span>
            <div className="flex flex-wrap gap-2 mt-1">
              {ALL_ENGINES.map(e => (
                <label key={e} className="flex items-center gap-1 text-primary">
                  <input type="checkbox" checked={engines.includes(e)}
                         onChange={ev => setEngines(prev => ev.target.checked ? [...prev, e] : prev.filter(x => x !== e))} />
                  {e}
                </label>
              ))}
            </div>
          </div>
          <button className="px-3 py-1.5 rounded text-white" style={{ background: 'var(--accent, #2563eb)' }} onClick={create}>
            {t('common.create', { defaultValue: '创建' })}
          </button>
        </div>
      )}

      {loading ? (
        <div className="text-xs text-muted text-center py-10">{t('common.loading')}</div>
      ) : err ? (
        <div className="text-xs text-red-500">{err}</div>
      ) : (
        <>
          {/* 概览卡片 */}
          <div className="grid grid-cols-3 gap-3 mb-5">
            <Stat label={t('workbench.adminGateway.statTenants', { defaultValue: '租户数' })} value={tenants.length} />
            <Stat label={t('workbench.adminGateway.statCallsToday', { defaultValue: '今日调用' })} value={totalCallsToday} />
            <Stat label={t('workbench.adminGateway.statCredits', { defaultValue: '余额合计(credits)' })} value={totalCredits} />
          </div>

          {/* 租户表 */}
          <div className="rounded-lg overflow-hidden mb-5" style={card}>
            <div className="px-3 py-2 text-xs font-medium text-primary" style={{ borderBottom: '1px solid var(--border-color)' }}>
              {t('workbench.adminGateway.tenantsTitle', { defaultValue: '租户' })}
            </div>
            <table className="w-full text-xs">
              <thead className="text-muted">
                <tr>
                  <th className="text-left px-3 py-2">{t('workbench.adminGateway.colName', { defaultValue: '名称' })}</th>
                  <th className="text-left px-3 py-2">{t('workbench.adminGateway.colTier', { defaultValue: '档位' })}</th>
                  <th className="text-left px-3 py-2">{t('workbench.adminGateway.colEngines', { defaultValue: '引擎' })}</th>
                  <th className="text-right px-3 py-2">{t('workbench.adminGateway.colQuota', { defaultValue: '日配额' })}</th>
                  <th className="text-right px-3 py-2">{t('workbench.adminGateway.colBalance', { defaultValue: '余额' })}</th>
                  <th className="text-right px-3 py-2">{t('workbench.adminGateway.colKeys', { defaultValue: '密钥' })}</th>
                  <th className="text-right px-3 py-2">{t('workbench.adminGateway.colCallsToday', { defaultValue: '今日调用' })}</th>
                  <th className="text-left px-3 py-2">{t('workbench.adminGateway.colStatus', { defaultValue: '状态' })}</th>
                  <th className="text-right px-3 py-2">{t('workbench.adminGateway.colActions', { defaultValue: '操作' })}</th>
                </tr>
              </thead>
              <tbody>
                {tenants.map(tt => (
                  <tr key={tt.id} style={{ borderTop: '1px solid var(--border-color)' }}>
                    <td className="px-3 py-2 text-primary">{tt.name}</td>
                    <td className="px-3 py-2 text-primary">{tierLabel(tt.tier)}</td>
                    <td className="px-3 py-2 text-muted">{tt.engines.length ? tt.engines.join(', ') : t('workbench.adminGateway.allEngines', { defaultValue: '全部' })}</td>
                    <td className="px-3 py-2 text-right text-primary">{tt.daily_quota_default}</td>
                    <td className="px-3 py-2 text-right" style={{ color: tt.credit_balance <= 0 ? '#ef4444' : 'var(--text-primary)' }}>{tt.credit_balance}</td>
                    <td className="px-3 py-2 text-right text-muted">{tt.active_keys}</td>
                    <td className="px-3 py-2 text-right text-primary">{tt.calls_today}</td>
                    <td className="px-3 py-2">
                      <span style={{ color: tt.status === 'active' ? '#22c55e' : '#ef4444' }}>
                        {tt.status === 'active'
                          ? t('workbench.adminGateway.active', { defaultValue: '正常' })
                          : t('workbench.adminGateway.suspended', { defaultValue: '已停用' })}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right whitespace-nowrap">
                      <button className="px-1.5 py-0.5 rounded mr-1" style={card} onClick={() => topUp(tt.id)}>{t('workbench.adminGateway.topup', { defaultValue: '充值' })}</button>
                      <button className="px-1.5 py-0.5 rounded mr-1" style={card} onClick={() => editQuota(tt)}>{t('workbench.adminGateway.editQuota', { defaultValue: '配额' })}</button>
                      <button className="px-1.5 py-0.5 rounded mr-1" style={card} onClick={() => reissue(tt.id)}>{t('workbench.adminGateway.reissue', { defaultValue: '发新Key' })}</button>
                      <button className="px-1.5 py-0.5 rounded" style={card} onClick={() => toggleStatus(tt)}>
                        {tt.status === 'active' ? t('workbench.adminGateway.suspend', { defaultValue: '停用' }) : t('workbench.adminGateway.enable', { defaultValue: '启用' })}
                      </button>
                    </td>
                  </tr>
                ))}
                {tenants.length === 0 && (
                  <tr><td colSpan={9} className="px-3 py-6 text-center text-muted">{t('workbench.adminGateway.noTenants', { defaultValue: '暂无租户' })}</td></tr>
                )}
              </tbody>
            </table>
          </div>

          {/* 最近调用 */}
          <div className="rounded-lg overflow-hidden" style={card}>
            <div className="px-3 py-2 text-xs font-medium text-primary" style={{ borderBottom: '1px solid var(--border-color)' }}>
              {t('workbench.adminGateway.jobsTitle', { defaultValue: '最近调用' })}
            </div>
            <table className="w-full text-xs">
              <thead className="text-muted">
                <tr>
                  <th className="text-left px-3 py-2">#</th>
                  <th className="text-left px-3 py-2">{t('workbench.adminGateway.colTenant', { defaultValue: '租户' })}</th>
                  <th className="text-left px-3 py-2">{t('workbench.adminGateway.colEngine', { defaultValue: '引擎' })}</th>
                  <th className="text-left px-3 py-2">{t('workbench.adminGateway.colQuery', { defaultValue: '问题' })}</th>
                  <th className="text-left px-3 py-2">{t('workbench.adminGateway.colStatus', { defaultValue: '状态' })}</th>
                  <th className="text-left px-3 py-2">{t('workbench.adminGateway.colTime', { defaultValue: '时间' })}</th>
                  <th className="text-right px-3 py-2">{t('workbench.adminGateway.colReturn', { defaultValue: '返回' })}</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map(j => (
                  <Fragment key={j.id}>
                    <tr style={{ borderTop: '1px solid var(--border-color)', cursor: 'pointer' }}
                        onClick={() => setOpenJob(openJob === j.id ? null : j.id)}>
                      <td className="px-3 py-2 text-muted">{j.id}</td>
                      <td className="px-3 py-2 text-muted">{j.tenant_id ?? '-'}</td>
                      <td className="px-3 py-2 text-primary">{j.engine}</td>
                      <td className="px-3 py-2 text-muted max-w-[320px] truncate">{j.query}</td>
                      <td className="px-3 py-2">
                        <span style={{ color: j.status === 'done' ? '#22c55e' : j.status === 'failed' ? '#ef4444' : 'var(--text-muted)' }}>{j.status}</span>
                      </td>
                      <td className="px-3 py-2 text-muted">{fmtTime(j.created_at)}</td>
                      <td className="px-3 py-2 text-right">
                        <button className="px-2 py-0.5 rounded text-xs" style={card}
                                onClick={(e) => { e.stopPropagation(); setOpenJob(openJob === j.id ? null : j.id); }}>
                          {openJob === j.id
                            ? t('workbench.adminGateway.collapse', { defaultValue: '收起' })
                            : t('workbench.adminGateway.view', { defaultValue: '查看' })}
                        </button>
                      </td>
                    </tr>
                    {openJob === j.id && (
                      <tr style={{ background: 'var(--bg-page, rgba(0,0,0,0.02))' }}>
                        <td colSpan={7} className="px-4 py-3">
                          {j.error
                            ? <div className="text-xs" style={{ color: '#ef4444' }}>
                                {t('workbench.adminGateway.retError', { defaultValue: '错误' })}:{j.error}
                              </div>
                            : <>
                                <div className="text-xs text-muted mb-1">{t('workbench.adminGateway.retAnswer', { defaultValue: '返回答案' })}:</div>
                                <div className="text-xs text-primary whitespace-pre-wrap mb-2" style={{ maxHeight: 320, overflow: 'auto' }}>
                                  {j.answer || t('workbench.adminGateway.retEmpty', { defaultValue: '(空)' })}
                                </div>
                                <div className="text-xs text-muted mb-1">
                                  {t('workbench.adminGateway.retCitations', { defaultValue: '引用来源' })}（{j.citations?.length || 0}）:
                                </div>
                                {(j.citations && j.citations.length > 0)
                                  ? <ul className="text-xs" style={{ listStyle: 'disc', paddingLeft: 18 }}>
                                      {j.citations.map((c, i) => (
                                        <li key={i}>
                                          <a href={c.url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent, #2563eb)' }}>
                                            {c.title || c.domain || c.url}
                                          </a>
                                          {c.domain ? <span className="text-muted">（{c.domain}）</span> : null}
                                        </li>
                                      ))}
                                    </ul>
                                  : <div className="text-xs text-muted">{t('workbench.adminGateway.retNoCite', { defaultValue: '(无引用)' })}</div>}
                              </>}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
                {jobs.length === 0 && (
                  <tr><td colSpan={7} className="px-3 py-6 text-center text-muted">{t('workbench.adminGateway.noJobs', { defaultValue: '暂无调用' })}</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg p-4" style={card}>
      <div className="text-2xl font-semibold text-primary">{value}</div>
      <div className="text-xs text-muted mt-1">{label}</div>
    </div>
  );
}
