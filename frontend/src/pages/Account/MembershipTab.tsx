import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useContactModal } from '../../components/ContactModalContext';
import { useTierModal } from '../../components/TierModalContext';
import {
  membershipApi,
  type Membership as MembershipType,
  type UserMembership,
  formatTierPrice,
} from '../../services/membershipApi';

const cardStyle: React.CSSProperties = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border-color)',
};

// Backend slug → i18n card key in `productsServices.cards.*`.
// Kept in sync with the identical map in ProductsServices.tsx.
const SLUG_TO_CARD_KEY: Record<string, string> = { pro: 'detector' };

export function MembershipTab() {
  const navigate = useNavigate();
  const { openContact } = useContactModal();
  const { openTierModal } = useTierModal();
  const { t, i18n } = useTranslation();
  const [userMembership, setUserMembership] = useState<UserMembership | null>(null);
  const [details, setDetails] = useState<MembershipType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = async () => {
    const token = localStorage.getItem('token');
    if (!token) return;
    setLoading(true);
    setError('');
    try {
      const [um, all] = await Promise.all([
        membershipApi.getUserMembership(token),
        membershipApi.getMemberships(),
      ]);
      setUserMembership(um);
      setDetails(all.find((m) => m.id === um.membership_id) ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('common.errors.loadFailed'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const tierText = (tier: MembershipType) => {
    const cardKey = SLUG_TO_CARD_KEY[tier.slug] ?? tier.slug;
    const base = `productsServices.cards.${cardKey}`;
    const name = i18n.exists(`${base}.name`) ? (t(`${base}.name`) as string) : tier.name;
    const description = i18n.exists(`${base}.description`)
      ? (t(`${base}.description`) as string)
      : tier.description;
    const period = i18n.exists(`${base}.period`) ? (t(`${base}.period`) as string) : tier.period;
    const translatedFeatures = i18n.exists(`${base}.features`)
      ? (t(`${base}.features`, { returnObjects: true }) as unknown)
      : null;
    const features = Array.isArray(translatedFeatures)
      ? (translatedFeatures as string[])
      : tier.features;
    return { name, description, period, features };
  };

  const handleRenew = () => {
    if (!details) return;
    if (details.tier_type === 'service') {
      openContact();
      return;
    }
    navigate(`/checkout/pending?slug=${encodeURIComponent(details.slug)}`);
  };

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

  const hasPaidPlan = !!(userMembership && userMembership.is_active && userMembership.id > 0);
  const endDate = userMembership ? new Date(userMembership.end_date) : null;
  const daysLeft =
    endDate && endDate.getFullYear() < 9999
      ? Math.max(0, Math.ceil((endDate.getTime() - Date.now()) / (1000 * 60 * 60 * 24)))
      : null;
  const localized = details ? tierText(details) : null;
  const isHighestTier = details?.slug === 'scale';

  return (
    <div className="space-y-6">
      <div className="rounded-2xl p-6" style={cardStyle}>
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-bold text-primary">
              {t('account.membership.currentPlan', '当前套餐')}
            </h2>
            {details && localized && (
              <div className="mt-3 space-y-2">
                <div className="flex items-baseline gap-3 flex-wrap">
                  <span className="text-2xl font-bold text-primary">{localized.name}</span>
                  <span
                    className="inline-flex items-center px-2 py-0.5 text-xs font-semibold rounded-full"
                    style={{
                      background: 'rgba(0, 240, 255, 0.1)',
                      border: '1px solid rgba(0, 240, 255, 0.3)',
                      color: 'var(--accent-primary)',
                    }}
                  >
                    {details.slug.charAt(0).toUpperCase() + details.slug.slice(1)}
                  </span>
                </div>
                <p className="text-sm text-secondary">
                  {details.tier_type === 'saas'
                    ? `${formatTierPrice(details)} ${localized.period}`
                    : t('account.membership.contactSales', '预约演示定制')}
                </p>
                <p className="text-sm text-secondary">{localized.description}</p>
              </div>
            )}
          </div>
        </div>

        <dl
          className="mt-5 grid grid-cols-1 sm:grid-cols-3 gap-4 pt-5 border-t"
          style={{ borderColor: 'var(--border-color)' }}
        >
          <div>
            <dt className="text-xs text-secondary">
              {t('account.membership.startDate', '开始时间')}
            </dt>
            <dd className="text-sm font-medium text-primary mt-1">
              {userMembership ? new Date(userMembership.start_date).toLocaleDateString() : '-'}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-secondary">
              {t('account.membership.endDate', '到期时间')}
            </dt>
            <dd className="text-sm font-medium text-primary mt-1">
              {endDate && endDate.getFullYear() < 9999
                ? endDate.toLocaleDateString()
                : t('account.membership.permanent', '长期有效')}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-secondary">
              {t('account.membership.daysLeft', '剩余天数')}
            </dt>
            <dd className="text-sm font-medium text-primary mt-1">
              {daysLeft === null ? '∞' : `${daysLeft} ${t('account.membership.days', '天')}`}
            </dd>
          </div>
        </dl>

        <div className="mt-5 flex flex-col sm:flex-row gap-3">
          {!isHighestTier && (
            <button
              onClick={openTierModal}
              className="btn-primary flex-1 justify-center !py-2.5"
            >
              {hasPaidPlan
                ? t('account.membership.upgrade', '升级套餐')
                : t('account.membership.browse', '浏览套餐')}
            </button>
          )}
          {hasPaidPlan && (
            <button
              onClick={handleRenew}
              className="btn-secondary flex-1 justify-center !py-2.5"
            >
              {t('account.membership.renew', '续费')}
            </button>
          )}
        </div>
      </div>

      {localized && localized.features.length > 0 && (
        <div className="rounded-2xl p-6" style={cardStyle}>
          <h3 className="text-base font-bold text-primary mb-3">
            {t('account.membership.features', '套餐权益')}
          </h3>
          <ul className="space-y-2 text-sm">
            {localized.features.map((f, i) => (
              <li key={i} className="flex items-start gap-2 text-secondary">
                <svg
                  className="w-4 h-4 mt-0.5 shrink-0"
                  style={{ color: 'var(--success)' }}
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
                {f}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
