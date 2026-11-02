import { useEffect, useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { accountApi, type PaymentRecord } from '../../services/accountApi';

const PAGE_SIZE = 10;

const cardStyle: React.CSSProperties = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border-color)',
};

const borderBottomStyle: React.CSSProperties = {
  borderBottom: '1px solid var(--border-color)',
};

function formatAmount(cents: number, currency: string): string {
  const symbol = currency.toLowerCase() === 'cny' ? '¥' : '$';
  return `${symbol}${(cents / 100).toFixed(2)}`;
}

const statusColors: Record<string, { bg: string; border: string; color: string }> = {
  paid: { bg: 'rgba(34, 197, 94, 0.1)', border: 'rgba(34, 197, 94, 0.3)', color: '#22c55e' },
  pending: { bg: 'rgba(234, 179, 8, 0.1)', border: 'rgba(234, 179, 8, 0.3)', color: '#eab308' },
  expired: { bg: 'rgba(107, 114, 128, 0.1)', border: 'rgba(107, 114, 128, 0.3)', color: '#6b7280' },
  failed: { bg: 'rgba(239, 68, 68, 0.1)', border: 'rgba(239, 68, 68, 0.3)', color: '#ef4444' },
};

// Build the "continue paying" URL for a pending row. Stripe has a hosted
// checkout URL we jump to directly; WeChat / Moltspay route back to our
// CheckoutPending page with the provider preselected, where the backend's
// pending-session reuse logic (<90min for WeChat, <30min for Moltspay) kicks in.
function pendingPayHref(row: PaymentRecord): string | null {
  if (row.status !== 'pending') return null;
  if (row.provider === 'stripe') return row.checkout_url || null;
  if (row.provider === 'wechat' || row.provider === 'moltspay') {
    return `/checkout/pending?slug=${encodeURIComponent(row.membership_slug)}&provider=${row.provider}`;
  }
  return null;
}

export function PaymentsTab() {
  const { t } = useTranslation();
  const [items, setItems] = useState<PaymentRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async (targetPage: number) => {
    const token = localStorage.getItem('token');
    if (!token) return;
    setLoading(true);
    setError('');
    try {
      const data = await accountApi.listPayments(token, targetPage, PAGE_SIZE);
      setItems(data.items);
      setTotal(data.total);
      setPage(data.page);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('common.errors.loadFailed'));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    load(1);
  }, [load]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="space-y-4">
      <div className="rounded-2xl overflow-hidden" style={cardStyle}>
        <div
          className="px-6 py-4 flex items-center justify-between"
          style={borderBottomStyle}
        >
          <h2 className="text-lg font-bold text-primary">
            {t('account.payments.title')}
          </h2>
          <span className="text-sm text-secondary">
            {t('account.payments.total', { n: total })}
          </span>
        </div>

        {loading ? (
          <div className="p-10 text-center">
            <div
              className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 mx-auto"
              style={{ borderColor: 'var(--accent-primary)' }}
            />
          </div>
        ) : error ? (
          <div className="p-6 text-sm" style={{ color: '#ff006e' }}>
            {error}
          </div>
        ) : items.length === 0 ? (
          <div className="p-10 text-center">
            <p className="text-secondary">
              {t('account.payments.empty')}
            </p>
          </div>
        ) : (
          <>
            {/* Mobile card layout */}
            <div className="sm:hidden divide-y" style={{ borderColor: 'var(--border-color)' }}>
              {items.map((row) => {
                const sc = statusColors[row.status] || statusColors.pending;
                return (
                  <div key={row.id} className="px-4 py-4 space-y-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium text-primary">
                        {t(`productsServices.cards.${row.membership_slug === 'pro' ? 'detector' : row.membership_slug}.name`, row.membership_slug)}
                      </span>
                      <span
                        className="inline-flex items-center px-2 py-0.5 text-xs font-medium rounded-full shrink-0"
                        style={{ background: sc.bg, border: `1px solid ${sc.border}`, color: sc.color }}
                      >
                        {t(`account.payments.statuses.${row.status}`, row.status)}
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-lg font-bold text-primary">
                        {formatAmount(row.amount_cents, row.currency)}
                      </span>
                      <span className="text-xs text-secondary">
                        {row.provider === 'moltspay' ? 'Base USDC' : row.provider === 'wechat' ? 'WeChat Pay' : 'Stripe'}
                      </span>
                    </div>
                    <div className="flex items-center gap-4 text-xs text-secondary">
                      <span>{new Date(row.created_at).toLocaleString()}</span>
                      {row.completed_at && (
                        <span>{new Date(row.completed_at).toLocaleString()}</span>
                      )}
                    </div>
                    {(() => {
                      const href = pendingPayHref(row);
                      if (!href) return null;
                      return (
                        <a
                          href={href}
                          className="inline-flex text-xs font-medium px-3 py-1.5 rounded-lg transition-colors mt-1"
                          style={{ color: 'var(--accent-primary)', border: '1px solid var(--accent-primary)', background: 'rgba(0,240,255,0.05)' }}
                        >
                          {t('account.payments.retry', 'Pay')}
                        </a>
                      );
                    })()}
                  </div>
                );
              })}
            </div>

            {/* Desktop table layout */}
            <div className="hidden sm:block overflow-x-auto">
              <table className="w-full text-sm">
                <thead style={{ background: 'var(--bg-tertiary)' }}>
                  <tr className="text-secondary">
                    <th className="px-4 py-3 text-left font-medium">
                      {t('account.payments.time')}
                    </th>
                    <th className="px-4 py-3 text-left font-medium">
                      {t('account.payments.plan')}
                    </th>
                    <th className="px-4 py-3 text-left font-medium">
                      {t('account.payments.amount')}
                    </th>
                    <th className="px-4 py-3 text-left font-medium">
                      {t('account.payments.provider', 'Method')}
                    </th>
                    <th className="px-4 py-3 text-left font-medium">
                      {t('account.payments.status')}
                    </th>
                    <th className="px-4 py-3 text-left font-medium">
                      {t('account.payments.completedAt')}
                    </th>
                    <th className="px-4 py-3 text-right font-medium">
                      {t('account.payments.actions', 'Actions')}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((row, idx) => {
                    const sc = statusColors[row.status] || statusColors.pending;
                    return (
                      <tr
                        key={row.id}
                        style={idx < items.length - 1 ? borderBottomStyle : undefined}
                        className="transition-colors hover:bg-white/5"
                      >
                        <td className="px-4 py-3 text-secondary whitespace-nowrap">
                          {new Date(row.created_at).toLocaleString()}
                        </td>
                        <td className="px-4 py-3 text-primary">
                          {t(`productsServices.cards.${row.membership_slug === 'pro' ? 'detector' : row.membership_slug}.name`, row.membership_slug)}
                        </td>
                        <td className="px-4 py-3 text-primary font-medium">
                          {formatAmount(row.amount_cents, row.currency)}
                        </td>
                        <td className="px-4 py-3 text-xs text-secondary">
                          {row.provider === 'moltspay' ? 'Base USDC' : row.provider === 'wechat' ? 'WeChat Pay' : 'Stripe'}
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className="inline-flex items-center px-2 py-0.5 text-xs font-medium rounded-full"
                            style={{ background: sc.bg, border: `1px solid ${sc.border}`, color: sc.color }}
                          >
                            {t(`account.payments.statuses.${row.status}`, row.status)}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-secondary whitespace-nowrap">
                          {row.completed_at
                            ? new Date(row.completed_at).toLocaleString()
                            : '-'}
                        </td>
                        <td className="px-4 py-3 text-right whitespace-nowrap">
                          {(() => {
                            const href = pendingPayHref(row);
                            if (!href) return null;
                            return (
                              <a
                                href={href}
                                className="text-xs font-medium px-3 py-1 rounded-lg transition-colors"
                                style={{ color: 'var(--accent-primary)', border: '1px solid var(--accent-primary)', background: 'rgba(0,240,255,0.05)' }}
                              >
                                {t('account.payments.retry', 'Pay')}
                              </a>
                            );
                          })()}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {totalPages > 1 && (
              <div
                className="px-6 py-3 flex items-center justify-between"
                style={{ borderTop: '1px solid var(--border-color)' }}
              >
                <span className="text-xs text-secondary">
                  {t('account.payments.pageOf', { page, pages: totalPages })}
                </span>
                <div className="flex gap-2">
                  <button
                    disabled={page <= 1}
                    onClick={() => load(page - 1)}
                    className="btn-secondary !py-1.5 !px-3 text-sm disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    {t('account.payments.prev')}
                  </button>
                  <button
                    disabled={page >= totalPages}
                    onClick={() => load(page + 1)}
                    className="btn-secondary !py-1.5 !px-3 text-sm disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    {t('account.payments.next')}
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
