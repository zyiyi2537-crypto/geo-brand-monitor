import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { aiTelemetryApi, type AdminAccount } from '../../services/aiTelemetryApi';
import { authApi } from '../../services/authApi';

// 客户端分页:后端按 id desc 一次返回全量,前端在内存里切片.
// 现在量级在几十到几百,纯前端分页足够;过千再做后端 limit/offset.
const PAGE_SIZE = 20;

export function AdminAccounts() {
  const token = localStorage.getItem('token') || '';
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [accounts, setAccounts] = useState<AdminAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [page, setPage] = useState(1);

  // ── 新建客户弹窗 state ──
  const [modalOpen, setModalOpen] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [formErr, setFormErr] = useState<string | null>(null);

  const reload = useCallback(() => {
    setLoading(true);
    aiTelemetryApi.adminListAccounts(token)
      .then(setAccounts)
      .catch(e => setErr(e?.message || 'failed'))
      .finally(() => setLoading(false));
  }, [token]);

  useEffect(() => { reload(); }, [reload]);

  // 后端已经按 id desc 返回;前端 paginate.account 总数变化时回第一页.
  const totalPages = Math.max(1, Math.ceil(accounts.length / PAGE_SIZE));
  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);
  const pagedAccounts = useMemo(
    () => accounts.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
    [accounts, page],
  );

  // 弹窗打开时锁滚 + Esc 关
  useEffect(() => {
    if (!modalOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !submitting) closeModal();
    };
    window.addEventListener('keydown', onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener('keydown', onKey);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modalOpen, submitting]);

  const openModal = () => {
    setEmail(''); setPassword(''); setName(''); setFormErr(null);
    setModalOpen(true);
  };
  const closeModal = () => {
    if (submitting) return;
    setModalOpen(false);
  };

  const handleCreate = async () => {
    setFormErr(null);
    const e = email.trim().toLowerCase();
    const p = password;
    const n = name.trim();
    if (!e) { setFormErr(t('workbench.adminAccounts.createForm.emailRequired')); return; }
    if (p.length < 6) { setFormErr(t('workbench.adminAccounts.createForm.passwordTooShort')); return; }
    setSubmitting(true);
    try {
      const u = await authApi.register(e, p, n || undefined);
      // 注册成功 → 直接跳到这个新客户的"新建主题"页
      setModalOpen(false);
      navigate(`/workbench/accounts/${u.id}/topics?new=1`);
    } catch (ex: unknown) {
      setFormErr(ex instanceof Error ? ex.message : String(ex));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="max-w-[1100px] mx-auto p-6">
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <h1 className="text-xl font-semibold text-primary">
            {t('workbench.adminAccounts.heading')}
          </h1>
          <p className="text-xs text-muted mt-1">
            {t('workbench.adminAccounts.subtitle')}
          </p>
        </div>
        <button type="button" onClick={openModal}
                className="text-xs px-3 py-1.5 rounded-md text-white whitespace-nowrap"
                style={{ background: 'var(--accent-primary)' }}>
          + {t('workbench.adminAccounts.newCustomer')}
        </button>
      </div>

      {loading ? (
        <div className="text-xs text-muted text-center py-10">
          {t('common.loading')}
        </div>
      ) : err ? (
        <div className="text-xs text-red-500">{err}</div>
      ) : (
        <div className="rounded-lg overflow-hidden" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-muted">
                <th className="text-left px-3 py-2">{t('workbench.adminAccounts.colId')}</th>
                <th className="text-left px-3 py-2">{t('workbench.adminAccounts.colEmail')}</th>
                <th className="text-left px-3 py-2">{t('workbench.adminAccounts.colName')}</th>
                <th className="text-right px-3 py-2">{t('workbench.adminAccounts.colTopicCount')}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {pagedAccounts.map(a => (
                <tr key={a.id} className="border-t" style={{ borderColor: 'var(--border-color)' }}>
                  <td className="px-3 py-2 text-muted tabular-nums">{a.id}</td>
                  <td className="px-3 py-2 text-primary">
                    {a.email}
                    {a.is_admin && (
                      <span className="ml-1 text-[10px] text-amber-500">
                        {t('workbench.adminAccounts.adminBadge')}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-secondary">{a.brand_target || a.name || '—'}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{a.topic_count}</td>
                  <td className="px-3 py-2">
                    <Link to={`/workbench/accounts/${a.id}/topics`} className="text-accent hover:underline">
                      {t('workbench.adminAccounts.configureTopics')} →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {accounts.length > PAGE_SIZE && (
            <div className="flex items-center justify-between gap-3 px-3 py-2 border-t text-xs text-secondary"
                 style={{ borderColor: 'var(--border-color)' }}>
              <span className="tabular-nums">
                {t('workbench.adminAccounts.pagination.range', {
                  defaultValue: '{{from}}-{{to}} / {{total}}',
                  from: (page - 1) * PAGE_SIZE + 1,
                  to: Math.min(page * PAGE_SIZE, accounts.length),
                  total: accounts.length,
                })}
              </span>
              <div className="flex items-center gap-2">
                <button type="button"
                        disabled={page <= 1}
                        onClick={() => setPage(p => Math.max(1, p - 1))}
                        className="px-2 py-1 rounded-md disabled:opacity-40"
                        style={{ background: 'var(--bg-tertiary)' }}>
                  {t('workbench.adminAccounts.pagination.prev', { defaultValue: '上一页' })}
                </button>
                <span className="tabular-nums">
                  {page} / {totalPages}
                </span>
                <button type="button"
                        disabled={page >= totalPages}
                        onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                        className="px-2 py-1 rounded-md disabled:opacity-40"
                        style={{ background: 'var(--bg-tertiary)' }}>
                  {t('workbench.adminAccounts.pagination.next', { defaultValue: '下一页' })}
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── 注册新客户弹窗 ── */}
      {modalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
             style={{ background: 'rgba(0,0,0,0.55)', backdropFilter: 'blur(2px)' }}
             onClick={closeModal}>
          <div className="w-full max-w-md rounded-xl p-5 shadow-2xl"
               style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}
               onClick={(e) => e.stopPropagation()}>
            <div className="flex items-start justify-between gap-3 mb-4">
              <h2 className="text-base font-semibold text-primary">
                {t('workbench.adminAccounts.createForm.title')}
              </h2>
              <button type="button" onClick={closeModal} disabled={submitting}
                      className="text-muted hover:text-primary text-lg leading-none"
                      aria-label="close">×</button>
            </div>
            <div className="space-y-3">
              <label className="block text-xs text-secondary">
                <span className="block mb-1">
                  {t('workbench.adminAccounts.createForm.emailLabel')} *
                </span>
                <input type="email" autoFocus autoComplete="off" value={email}
                       onChange={e => setEmail(e.target.value)}
                       onKeyDown={e => { if (e.key === 'Enter') handleCreate(); }}
                       placeholder={t('workbench.adminAccounts.createForm.emailPlaceholder')}
                       className="w-full px-2 py-1.5 rounded-md text-xs text-primary"
                       style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)' }} />
              </label>
              <label className="block text-xs text-secondary">
                <span className="block mb-1">
                  {t('workbench.adminAccounts.createForm.passwordLabel')} *
                </span>
                <input type="text" autoComplete="off" value={password}
                       onChange={e => setPassword(e.target.value)}
                       onKeyDown={e => { if (e.key === 'Enter') handleCreate(); }}
                       placeholder={t('workbench.adminAccounts.createForm.passwordPlaceholder')}
                       className="w-full px-2 py-1.5 rounded-md text-xs text-primary"
                       style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)' }} />
              </label>
              <label className="block text-xs text-secondary">
                <span className="block mb-1">
                  {t('workbench.adminAccounts.createForm.nameLabel')}
                </span>
                <input type="text" autoComplete="off" value={name}
                       onChange={e => setName(e.target.value)}
                       onKeyDown={e => { if (e.key === 'Enter') handleCreate(); }}
                       placeholder={t('workbench.adminAccounts.createForm.namePlaceholder')}
                       className="w-full px-2 py-1.5 rounded-md text-xs text-primary"
                       style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)' }} />
              </label>
            </div>
            {formErr && (
              <div className="mt-3 text-xs text-red-500">{formErr}</div>
            )}
            <div className="mt-5 flex items-center justify-end gap-2">
              <button type="button" disabled={submitting} onClick={closeModal}
                      className="text-xs px-3 py-1.5 rounded-md"
                      style={{ background: 'var(--bg-tertiary)', color: 'var(--text-secondary)' }}>
                {t('workbench.adminAccounts.createForm.cancel')}
              </button>
              <button type="button" disabled={submitting} onClick={handleCreate}
                      className="text-xs px-3 py-1.5 rounded-md text-white"
                      style={{ background: 'var(--accent-primary)', opacity: submitting ? 0.5 : 1 }}>
                {submitting
                  ? t('workbench.adminAccounts.createForm.submitting')
                  : t('workbench.adminAccounts.createForm.submit')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
