import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { AuthModal } from './AuthModal';
import { useContactModal } from './ContactModalContext';
import { useTierModal } from './TierModalContext';
import { useMembership } from '../hooks/useMembership';
import {
  membershipApi,
  type Membership,
  formatTierPrice,
} from '../services/membershipApi';

export function TierModal() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const { isLoggedIn, refresh } = useMembership();
  const { openContact } = useContactModal();
  const { isOpen, closeTierModal } = useTierModal();

  const [memberships, setMemberships] = useState<Membership[]>([]);
  const [tiersLoading, setTiersLoading] = useState(false);
  const [tiersError, setTiersError] = useState<string | null>(null);
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [pendingTierSlug, setPendingTierSlug] = useState<string | null>(null);

  const tierText = (tier: Membership) => {
    const slugToCardKey: Record<string, string> = { pro: 'detector' };
    const cardKey = slugToCardKey[tier.slug] ?? tier.slug;
    const base = `productsServices.cards.${cardKey}`;
    const name = i18n.exists(`${base}.name`) ? (t(`${base}.name`) as string) : tier.name;
    const description = i18n.exists(`${base}.description`)
      ? (t(`${base}.description`) as string)
      : tier.description;
    const period = i18n.exists(`${base}.period`)
      ? (t(`${base}.period`) as string)
      : tier.period;
    const translatedFeatures = i18n.exists(`${base}.features`)
      ? (t(`${base}.features`, { returnObjects: true }) as unknown)
      : null;
    const features = Array.isArray(translatedFeatures)
      ? (translatedFeatures as string[])
      : tier.features;
    return { name, description, period, features };
  };

  const ctaLabelFor = (tier: Membership) => {
    if (tier.slug === 'free') return t('productsServices.cta.tryNow');
    if (tier.tier_type === 'saas') return t('productsServices.cta.subscribeNow');
    return t('productsServices.cta.contactSales');
  };

  // Load memberships when modal opens
  if (isOpen && memberships.length === 0 && !tiersLoading && !tiersError) {
    setTiersLoading(true);
    membershipApi
      .getMemberships()
      .then((data) => setMemberships(data))
      .catch((err) =>
        setTiersError(err instanceof Error ? err.message : t('common.errors.loadFailed')),
      )
      .finally(() => setTiersLoading(false));
  }

  const handleTierCTA = (tier: Membership) => {
    if (tier.slug === 'free') {
      closeTierModal();
      return;
    }
    if (tier.tier_type === 'saas') {
      if (!isLoggedIn) {
        setPendingTierSlug(tier.slug);
        closeTierModal();
        setAuthModalOpen(true);
        return;
      }
      closeTierModal();
      navigate(`/checkout/pending?slug=${encodeURIComponent(tier.slug)}`);
      return;
    }
    // Service tier — open contact modal.
    closeTierModal();
    openContact();
  };

  const handleAuthSuccess = () => {
    refresh();
    setAuthModalOpen(false);
    if (pendingTierSlug) {
      navigate(`/checkout/pending?slug=${encodeURIComponent(pendingTierSlug)}`);
      setPendingTierSlug(null);
    }
  };

  if (!isOpen && !authModalOpen) return null;

  return (
    <>
      {isOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 backdrop-blur-sm animate-fade-in"
          style={{ background: 'rgba(0, 0, 0, 0.6)' }}
          onClick={closeTierModal}
          role="dialog"
          aria-modal="true"
        >
          <div
            className="relative w-full max-w-6xl max-h-[85vh] sm:max-h-[90vh] overflow-y-auto bg-surface border border-soft rounded-2xl p-4 sm:p-6 md:p-8 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              type="button"
              onClick={closeTierModal}
              className="absolute top-4 right-4 w-8 h-8 rounded-full flex items-center justify-center text-secondary hover:bg-surface-hover transition-colors"
              style={{ color: 'var(--text-secondary)' }}
              aria-label={t('productsServices.closeAria')}
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                className="h-5 w-5"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
            <div className="text-center mb-6 sm:mb-8 pr-8 sm:pr-10">
              <h2 className="text-xl sm:text-2xl md:text-3xl font-bold mb-2 tracking-tight">
                <span className="gradient-text">{t('home.advanced.tierModal.title')}</span>
              </h2>
              <p className="text-sm text-secondary">
                {t('home.advanced.tierModal.subtitle')}
              </p>
            </div>

            {tiersLoading && (
              <div className="py-12 text-center text-secondary">
                {t('productsServices.loadingMemberships')}
              </div>
            )}
            {tiersError && (
              <div className="py-12 text-center" style={{ color: '#ef4444' }}>{tiersError}</div>
            )}

            {!tiersLoading && !tiersError && memberships.length > 0 && (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-3 sm:gap-4 items-stretch">
                {memberships.map((tier) => {
                  const text = tierText(tier);
                  return (
                    <div
                      key={tier.id}
                      className={`relative h-full card p-5 flex flex-col ${
                        tier.popular ? 'shadow-glow' : ''
                      }`}
                      style={
                        tier.popular
                          ? { borderColor: 'var(--accent-primary)' }
                          : undefined
                      }
                    >
                      {tier.popular && (
                        <div
                          className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-1 rounded-full text-[10px] uppercase tracking-[0.2em] font-semibold whitespace-nowrap"
                          style={{
                            background: 'var(--solid-btn-bg)',
                            color: 'var(--solid-btn-text)',
                          }}
                        >
                          {t('productsServices.cta.popular')}
                        </div>
                      )}
                      <h3 className="text-lg font-bold mb-2 min-h-[1.75rem] text-primary">{text.name}</h3>
                      <div className="flex items-baseline gap-1 mb-3 min-h-[2.5rem]">
                        <span className="text-3xl font-bold text-primary">
                          {tier.slug === 'scale'
                            ? t('productsServices.cards.scale.getDemoPrice')
                            : formatTierPrice(tier)}
                        </span>
                        {tier.slug !== 'scale' && tier.tier_type === 'saas' && text.period && (
                          <span className="text-sm text-secondary font-medium">{text.period}</span>
                        )}
                        {tier.slug !== 'scale' && tier.tier_type === 'service' && (
                          <span className="text-xs text-secondary font-medium ml-1">
                            {t('productsServices.perProject')}
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-secondary leading-relaxed mb-4 line-clamp-3 min-h-[3.4rem]">
                        {text.description}
                      </p>
                      <ul className="space-y-2 mb-6 flex-1">
                        {text.features.slice(0, 5).map((feature, idx) => (
                          <li key={idx} className="flex items-start gap-2 text-xs text-primary">
                            <svg
                              className="w-4 h-4 shrink-0 mt-0.5"
                              fill="none"
                              stroke="currentColor"
                              viewBox="0 0 24 24"
                              style={{ color: 'var(--accent-primary)' }}
                            >
                              <path
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                strokeWidth="2.5"
                                d="M5 13l4 4L19 7"
                              />
                            </svg>
                            <span className="leading-snug">{feature}</span>
                          </li>
                        ))}
                      </ul>
                      <div className="mt-auto">
                        <button
                          type="button"
                          onClick={() => handleTierCTA(tier)}
                          className={`w-full justify-center py-3 text-sm font-semibold rounded-lg transition-colors duration-200 ${
                            tier.popular ? 'btn-solid' : 'btn-secondary'
                          }`}
                        >
                          {ctaLabelFor(tier)}
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}

      <AuthModal
        isOpen={authModalOpen}
        onClose={() => {
          setAuthModalOpen(false);
          setPendingTierSlug(null);
        }}
        defaultTab="login"
        onSuccess={handleAuthSuccess}
      />
    </>
  );
}
