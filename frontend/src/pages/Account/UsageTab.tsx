import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  membershipApi,
  type Membership as MembershipType,
  type UserMembership,
  type UsageResponse,
} from '../../services/membershipApi';

const ALL_CATEGORIES_TOTAL = 25;

const cardStyle: React.CSSProperties = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border-color)',
};

export function UsageTab() {
  const { t } = useTranslation();
  const [usage, setUsage] = useState<UsageResponse | null>(null);
  const [details, setDetails] = useState<MembershipType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    const token = localStorage.getItem('token');
    if (!token) return;
    let cancelled = false;
    (async () => {
      try {
        const [u, um, all] = await Promise.all([
          membershipApi.getUsage(token),
          membershipApi.getUserMembership(token),
          membershipApi.getMemberships(),
        ]);
        if (cancelled) return;
        setUsage(u);
        const found = all.find((m) => m.id === (um as UserMembership).membership_id) ?? null;
        setDetails(found);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : t('common.errors.loadFailed'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <div className="rounded-2xl p-10 text-center" style={cardStyle}>
        <div
          className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 mx-auto"
          style={{ borderColor: 'var(--accent-primary)' }}
        />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-2xl p-6" style={cardStyle}>
        <p className="text-sm" style={{ color: '#ff006e' }}>{error}</p>
      </div>
    );
  }

  const unlimited = usage && usage.quota === 0;
  const pct =
    usage && usage.quota > 0
      ? Math.min(100, Math.round((usage.used / usage.quota) * 100))
      : 0;

  const unlockedCount =
    details?.allowed_check_categories === null
      ? ALL_CATEGORIES_TOTAL
      : details?.allowed_check_categories?.length ?? 0;

  const unlockedPct = Math.round((unlockedCount / ALL_CATEGORIES_TOTAL) * 100);

  return (
    <div className="space-y-6">
      <div className="rounded-2xl p-6" style={cardStyle}>
        <div className="flex items-baseline justify-between mb-4">
          <h2 className="text-lg font-bold text-primary">
            {t('account.usage.monthlyUsage', '本月检测用量')}
          </h2>
          <span className="text-xs text-secondary">{usage?.year_month}</span>
        </div>

        <div className="flex items-baseline gap-2 mb-3">
          <span className="text-4xl font-bold text-primary">{usage?.used ?? 0}</span>
          <span className="text-secondary">
            / {unlimited ? '∞' : usage?.quota} {t('account.usage.times', '次')}
          </span>
        </div>

        {!unlimited && usage && usage.quota > 0 && (
          <div
            className="h-2 rounded-full overflow-hidden"
            style={{ background: 'var(--bg-tertiary)' }}
          >
            <div
              className="h-full transition-all duration-500"
              style={{ width: `${pct}%`, background: 'var(--accent-gradient)' }}
            />
          </div>
        )}

        <p className="text-sm text-secondary mt-3">
          {unlimited
            ? t('account.usage.unlimited', '您当前套餐无检测次数限制。')
            : t('account.usage.remaining', '剩余 {{n}} 次，月初自动重置。', {
                n: usage?.remaining ?? 0,
              })}
        </p>
      </div>

      <div className="rounded-2xl p-6" style={cardStyle}>
        <h2 className="text-lg font-bold text-primary mb-4">
          {t('account.usage.unlockedCategories', '已解锁检测类目')}
        </h2>
        <div className="flex items-baseline gap-2">
          <span className="text-4xl font-bold text-primary">{unlockedCount}</span>
          <span className="text-secondary">/ {ALL_CATEGORIES_TOTAL}</span>
        </div>
        <div
          className="mt-3 h-2 rounded-full overflow-hidden"
          style={{ background: 'var(--bg-tertiary)' }}
        >
          <div
            className="h-full transition-all duration-500"
            style={{
              width: `${unlockedPct}%`,
              background: 'linear-gradient(90deg, var(--success), var(--accent-primary))',
            }}
          />
        </div>
        <p className="text-sm text-secondary mt-3">
          {unlockedCount === ALL_CATEGORIES_TOTAL
            ? t('account.usage.allUnlocked', '您已解锁全部 25 项检测能力。')
            : t('account.usage.partialUnlocked', '升级套餐可解锁更多检测类目。')}
        </p>
      </div>
    </div>
  );
}
