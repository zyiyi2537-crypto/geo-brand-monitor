import { useEffect, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { membershipApi, type Membership, formatTierPrice } from '../services/membershipApi';
import { useMembership } from '../hooks/useMembership';
import { AuthModal } from '../components/AuthModal';
import { useContactModal } from '../components/ContactModalContext';
import { PageHead } from '../components/PageHead';

type ContactFormState = {
  name: string;
  email: string;
  website: string;
  message: string;
};

const INITIAL_FORM: ContactFormState = {
  name: '',
  email: '',
  website: '',
  message: '',
};

// Use the shared formatter so currency symbols stay in lockstep with backend.

export function ProductsServices() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();

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
  const { isLoggedIn, refresh: refreshMembership } = useMembership();
  const { openContact } = useContactModal();
  const [memberships, setMemberships] = useState<Membership[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [form, setForm] = useState<ContactFormState>(INITIAL_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [feedbackKind, setFeedbackKind] = useState<'success' | 'error' | null>(null);
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [pendingTierSlug, setPendingTierSlug] = useState<string | null>(null);
  const [showContactModal, setShowContactModal] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    membershipApi
      .getMemberships()
      .then((data) => {
        if (cancelled) return;
        setMemberships(data);
      })
      .catch((err) => {
        if (cancelled) return;
        setLoadError(err instanceof Error ? err.message : t('common.errors.loadFailed'));
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleCTA = (tier: Membership) => {
    if (tier.slug === 'free') {
      navigate('/');
      return;
    }
    if (tier.tier_type === 'saas') {
      if (!isLoggedIn) {
        setPendingTierSlug(tier.slug);
        setAuthModalOpen(true);
        return;
      }
      navigate(`/checkout/pending?slug=${encodeURIComponent(tier.slug)}`);
      return;
    }
    // service tier: open shared contact modal
    openContact();
  };

  const closeContactModal = () => {
    if (submitting) return;
    setShowContactModal(false);
  };

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setFeedback(null);
    setFeedbackKind(null);
    try {
      const resp = await membershipApi.submitContactForm({
        name: form.name,
        email: form.email,
        website: form.website || undefined,
        message: form.message || undefined,
      });
      setFeedback(resp.message);
      setFeedbackKind('success');
      setForm(INITIAL_FORM);
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : t('productsServices.submitError'));
      setFeedbackKind('error');
    } finally {
      setSubmitting(false);
    }
  };

  const ctaLabelFor = (tier: Membership) => {
    if (tier.slug === 'free') return t('productsServices.cta.tryNow');
    if (tier.tier_type === 'saas') return t('productsServices.cta.subscribeNow');
    return t('productsServices.cta.contactSales');
  };

  const handleAuthSuccess = () => {
    refreshMembership();
    if (pendingTierSlug) {
      navigate(`/checkout/pending?slug=${encodeURIComponent(pendingTierSlug)}`);
      setPendingTierSlug(null);
    }
  };

  return (
    <div className="min-h-screen grid-background">
      <PageHead titleKey="pageMeta.productsServices.title" descriptionKey="pageMeta.productsServices.description" />
      <div className="bg-glow bg-glow-1"></div>
      <div className="bg-glow bg-glow-2"></div>
      <div className="bg-glow bg-glow-3"></div>

      <main className="flex-1 px-4 pt-24 pb-12 sm:py-24 hero-gradient relative z-10">
        <div className="w-full max-w-6xl mx-auto animate-fade-in">
          <section className="hero mb-16">
            <div className="max-w-3xl mx-auto text-center">
              <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold mb-6 leading-tight animate-slide-up">
                <span className="gradient-text">{t('productsServices.title')}</span>
              </h1>
              <p className="text-lg sm:text-xl text-secondary max-w-3xl mx-auto leading-relaxed animate-slide-up" style={{ animationDelay: '0.1s' }}>
                {t('productsServices.description')}
              </p>
            </div>
          </section>

          <section className="mb-20 animate-fade-in" style={{ animationDelay: '0.2s' }}>
            <h2 className="text-3xl font-bold mb-12 text-center">
              <span className="gradient-text">{t('productsServices.sections.ourServices')}</span>
            </h2>

            {isLoading && (
              <div className="text-center text-secondary">{t('productsServices.loadingMemberships')}</div>
            )}
            {loadError && (
              <div className="text-center text-rose-400">{loadError}</div>
            )}

            {!isLoading && !loadError && (
              <>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-3 sm:gap-6 mb-12 items-stretch">
                  {memberships.map((tier) => {
                    const text = tierText(tier);
                    return (
                      <div
                        key={tier.id}
                        className={`relative h-full bg-card border rounded-2xl p-6 hover:shadow-lg hover:shadow-accent-primary/10 transition-all duration-300 flex flex-col ${tier.popular
                          ? 'border-accent-primary shadow-lg shadow-accent-primary/20'
                          : 'border-border'
                          }`}
                      >
                        {tier.popular && (
                          <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-1 rounded-full bg-white bg-accent-primary text-[#000] text-[10px] uppercase tracking-[0.2em] font-semibold whitespace-nowrap">
                            {t('productsServices.cta.popular')}
                          </div>
                        )}
                        <h3 className="text-lg font-bold mb-2 min-h-[1.75rem]">{text.name}</h3>
                        <div className="flex items-baseline gap-1 mb-3 min-h-[2.5rem]">
                          <span className="text-3xl font-bold text-accent-primary">
                            {tier.slug === 'scale'
                              ? t('productsServices.cards.scale.getDemoPrice')
                              : formatTierPrice(tier)}
                          </span>
                          {tier.slug !== 'scale' && tier.tier_type === 'saas' && text.period && (
                            <span className="text-sm text-secondary font-medium">{text.period}</span>
                          )}
                          {tier.slug !== 'scale' && tier.tier_type === 'service' && (
                            <span className="text-xs text-secondary font-medium ml-1">{t('productsServices.perProject')}</span>
                          )}
                        </div>
                        <p className="text-xs text-secondary leading-relaxed mb-4 line-clamp-3 min-h-[3.4rem]">
                          {text.description}
                        </p>
                        <ul className="space-y-2 mb-6 flex-1">
                          {text.features.slice(0, 5).map((feature, idx) => (
                            <li key={idx} className="flex items-start gap-2 text-xs text-primary">
                              <svg
                                className="w-4 h-4 text-accent-primary shrink-0 mt-0.5"
                                fill="none"
                                stroke="currentColor"
                                viewBox="0 0 24 24"
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
                            onClick={() => handleCTA(tier)}
                            className="w-full justify-center !py-3 text-sm btn-primary"
                            style={
                              tier.popular
                                ? undefined
                                : {
                                  background: '#ffffff',
                                  border: '1px solid #ffffff',
                                  color: '#0a0a0f',
                                  boxShadow: '0 4px 12px rgba(0, 0, 0, 0.25)',
                                }
                            }
                          >
                            {ctaLabelFor(tier)}
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
                <div className="overflow-x-auto scrollbar-hide -mx-4 px-4 sm:mx-0 sm:px-0">
                  <table className="w-full border-collapse min-w-[640px]">
                    <thead>
                      <tr className="bg-card border-b border-border">
                        <th className="px-3 sm:px-4 py-3 text-left text-xs sm:text-sm font-semibold text-secondary">{t('productsServices.table.headers.number')}</th>
                        <th className="px-3 sm:px-4 py-3 text-left text-xs sm:text-sm font-semibold text-secondary">{t('productsServices.table.headers.feature')}</th>
                        <th className="px-3 sm:px-4 py-3 text-center text-xs sm:text-sm font-semibold text-secondary">{t('productsServices.table.headers.free')}</th>
                        <th className="px-3 sm:px-4 py-3 text-center text-xs sm:text-sm font-semibold text-secondary">{t('productsServices.table.headers.detector')}</th>
                        <th className="px-3 sm:px-4 py-3 text-center text-xs sm:text-sm font-semibold text-secondary">{t('productsServices.table.headers.starter')}</th>
                        <th className="px-3 sm:px-4 py-3 text-center text-xs sm:text-sm font-semibold text-secondary">{t('productsServices.table.headers.growth')}</th>
                        <th className="px-3 sm:px-4 py-3 text-center text-xs sm:text-sm font-semibold text-secondary">{t('productsServices.table.headers.scale')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {/* 价格行 */}
                      <tr className="border-b border-border">
                        <td className="px-4 py-3 text-sm text-secondary"></td>
                        <td className="px-4 py-3 text-sm font-medium">{t('productsServices.table.rows.price')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.free.price')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.detector.price')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.starter.price')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.growth.price')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.scale.price')}</td>
                      </tr>
                      {/* 形态行 */}
                      <tr className="border-b border-border">
                        <td className="px-4 py-3 text-sm text-secondary"></td>
                        <td className="px-4 py-3 text-sm font-medium">{t('productsServices.table.rows.type')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.free.type')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.detector.type')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.starter.type')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.growth.type')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.scale.type')}</td>
                      </tr>

                      {/* 权益项1 */}
                      <tr className="border-b border-border">
                        <td className="px-4 py-3 text-sm text-secondary">1</td>
                        <td className="px-4 py-3 text-sm">{t('productsServices.table.rows.checkItems')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.free.checkItems')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.detector.checkItems')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.starter.checkItems')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.growth.checkItems')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.scale.checkItems')}</td>
                      </tr>
                      {/* 权益项2 */}
                      <tr className="border-b border-border">
                        <td className="px-4 py-3 text-sm text-secondary">2</td>
                        <td className="px-4 py-3 text-sm">{t('productsServices.table.rows.subCheckItems')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.free.subCheckItems')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.detector.subCheckItems')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.starter.subCheckItems')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.growth.subCheckItems')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.scale.subCheckItems')}</td>
                      </tr>
                      {/* 权益项3 */}
                      <tr className="border-b border-border">
                        <td className="px-4 py-3 text-sm text-secondary">3</td>
                        <td className="px-4 py-3 text-sm">{t('productsServices.table.rows.monthlyChecks')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.free.monthlyChecks')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.detector.monthlyChecks')}</td>
                        <td className="px-4 py-3 text-center text-sm font-medium">{t('productsServices.table.values.starter.monthlyChecks')}</td>
                        <td className="px-4 py-3 text-center text-sm font-medium">{t('productsServices.table.values.growth.monthlyChecks')}</td>
                        <td className="px-4 py-3 text-center text-sm font-medium">{t('productsServices.table.values.scale.monthlyChecks')}</td>
                      </tr>
                      {/* 权益项4 */}
                      <tr className="border-b border-border">
                        <td className="px-4 py-3 text-sm text-secondary">4</td>
                        <td className="px-4 py-3 text-sm">{t('productsServices.table.rows.prioritySorting')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.free.prioritySorting')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.detector.prioritySorting')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.starter.prioritySorting')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.growth.prioritySorting')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.scale.prioritySorting')}</td>
                      </tr>
                      {/* 权益项5 */}
                      <tr className="border-b border-border">
                        <td className="px-4 py-3 text-sm text-secondary">5</td>
                        <td className="px-4 py-3 text-sm">{t('productsServices.table.rows.fullReport')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.free.fullReport')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.detector.fullReport')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.starter.fullReport')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.growth.fullReport')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.scale.fullReport')}</td>
                      </tr>
                      {/* 权益项6 */}
                      <tr className="border-b border-border">
                        <td className="px-4 py-3 text-sm text-secondary">6</td>
                        <td className="px-4 py-3 text-sm">{t('productsServices.table.rows.history')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.free.history')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.detector.history')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.starter.history')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.growth.history')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.scale.history')}</td>
                      </tr>
                      {/* 权益项7 */}
                      <tr className="border-b border-border">
                        <td className="px-4 py-3 text-sm text-secondary">7</td>
                        <td className="px-4 py-3 text-sm">{t('productsServices.table.rows.support')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.free.support')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.detector.support')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.starter.support')}</td>
                        <td className="px-4 py-3 text-center text-sm font-medium">{t('productsServices.table.values.growth.support')}</td>
                        <td className="px-4 py-3 text-center text-sm font-medium">{t('productsServices.table.values.scale.support')}</td>
                      </tr>
                      {/* 权益项8 */}
                      <tr className="border-b border-border">
                        <td className="px-4 py-3 text-sm text-secondary">8</td>
                        <td className="px-4 py-3 text-sm">{t('productsServices.table.rows.optimizationDetails')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.free.optimizationDetails')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.detector.optimizationDetails')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.starter.optimizationDetails')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.growth.optimizationDetails')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.scale.optimizationDetails')}</td>
                      </tr>
                      {/* 权益项9 */}
                      <tr className="border-b border-border">
                        <td className="px-4 py-3 text-sm text-secondary">9</td>
                        <td className="px-4 py-3 text-sm">{t('productsServices.table.rows.basicGeo')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.free.basicGeo')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.detector.basicGeo')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.starter.basicGeo')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.growth.basicGeo')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.scale.basicGeo')}</td>
                      </tr>
                      {/* 权益项10 */}
                      <tr className="border-b border-border">
                        <td className="px-4 py-3 text-sm text-secondary">10</td>
                        <td className="px-4 py-3 text-sm">{t('productsServices.table.rows.llmStandards')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.free.llmStandards')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.detector.llmStandards')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.starter.llmStandards')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.growth.llmStandards')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.scale.llmStandards')}</td>
                      </tr>
                      {/* 权益项11 */}
                      <tr className="border-b border-border">
                        <td className="px-4 py-3 text-sm text-secondary">11</td>
                        <td className="px-4 py-3 text-sm">{t('productsServices.table.rows.websiteCopy')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.free.websiteCopy')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.detector.websiteCopy')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.starter.websiteCopy')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.growth.websiteCopy')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.scale.websiteCopy')}</td>
                      </tr>
                      {/* 权益项12 */}
                      <tr className="border-b border-border">
                        <td className="px-4 py-3 text-sm text-secondary">12</td>
                        <td className="px-4 py-3 text-sm">{t('productsServices.table.rows.productInfo')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.free.productInfo')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.detector.productInfo')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.starter.productInfo')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.growth.productInfo')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.scale.productInfo')}</td>
                      </tr>
                      {/* 权益项13 */}
                      <tr className="border-b border-border">
                        <td className="px-4 py-3 text-sm text-secondary">13</td>
                        <td className="px-4 py-3 text-sm">{t('productsServices.table.rows.maintenance')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.free.maintenance')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.detector.maintenance')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.starter.maintenance')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.growth.maintenance')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.scale.maintenance')}</td>
                      </tr>
                      {/* 权益项14 */}
                      <tr className="border-b border-border">
                        <td className="px-4 py-3 text-sm text-secondary">14</td>
                        <td className="px-4 py-3 text-sm">{t('productsServices.table.rows.seoPlacement')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.free.seoPlacement')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.detector.seoPlacement')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.starter.seoPlacement')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.growth.seoPlacement')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.scale.seoPlacement')}</td>
                      </tr>
                      {/* 权益项15 */}
                      <tr className="border-b border-border">
                        <td className="px-4 py-3 text-sm text-secondary">15</td>
                        <td className="px-4 py-3 text-sm">{t('productsServices.table.rows.reputation')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.free.reputation')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.detector.reputation')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.starter.reputation')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.growth.reputation')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.scale.reputation')}</td>
                      </tr>
                      {/* 权益项16 */}
                      <tr className="border-b border-border">
                        <td className="px-4 py-3 text-sm text-secondary">16</td>
                        <td className="px-4 py-3 text-sm">{t('productsServices.table.rows.prSupport')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.free.prSupport')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.detector.prSupport')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.starter.prSupport')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.growth.prSupport')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.scale.prSupport')}</td>
                      </tr>
                      {/* 权益项17 */}
                      <tr className="border-b border-border">
                        <td className="px-4 py-3 text-sm text-secondary">17</td>
                        <td className="px-4 py-3 text-sm">{t('productsServices.table.rows.serviceCycle')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.free.serviceCycle')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.detector.serviceCycle')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.starter.serviceCycle')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.growth.serviceCycle')}</td>
                        <td className="px-4 py-3 text-center text-sm">{t('productsServices.table.values.scale.serviceCycle')}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </section>

        </div>
      </main>

      {showContactModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fade-in"
          onClick={closeContactModal}
          role="dialog"
          aria-modal="true"
        >
          <div
            className="relative w-full max-w-xl max-h-[90vh] overflow-y-auto bg-card border border-border rounded-2xl p-6 sm:p-8 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              type="button"
              onClick={closeContactModal}
              disabled={submitting}
              className="absolute top-4 right-4 w-8 h-8 rounded-full flex items-center justify-center text-secondary hover:text-primary hover:bg-white/5 transition-colors disabled:opacity-50"
              aria-label={t('productsServices.closeAria')}
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
            <h2 className="text-2xl font-bold mb-2 pr-10">
              <span className="gradient-text">{t('productsServices.sections.contactConsultation')}</span>
            </h2>
            <p className="text-sm text-secondary mb-6">{t('productsServices.contact.getCustomPlan')}</p>
            <form className="space-y-5" onSubmit={handleSubmit}>
              <div>
                <label htmlFor="name" className="block text-sm font-semibold mb-2">
                  {t('productsServices.contact.name')}
                </label>
                <input
                  type="text"
                  id="name"
                  name="name"
                  required
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  className="w-full px-4 py-3 rounded-lg bg-card border border-border text-white placeholder-gray-500 focus:outline-none focus:border-accent-primary transition-colors duration-200"
                  placeholder={t('productsServices.contact.namePlaceholder')}
                />
              </div>
              <div>
                <label htmlFor="email" className="block text-sm font-semibold mb-2">
                  {t('productsServices.contact.email')}
                </label>
                <input
                  type="email"
                  id="email"
                  name="email"
                  required
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                  className="w-full px-4 py-3 rounded-lg bg-card border border-border text-white placeholder-gray-500 focus:outline-none focus:border-accent-primary transition-colors duration-200"
                  placeholder={t('productsServices.contact.emailPlaceholder')}
                />
              </div>
              <div>
                <label htmlFor="website" className="block text-sm font-semibold mb-2">
                  {t('productsServices.contact.website')}
                </label>
                <input
                  type="url"
                  id="website"
                  name="website"
                  value={form.website}
                  onChange={(e) => setForm({ ...form, website: e.target.value })}
                  className="w-full px-4 py-3 rounded-lg bg-card border border-border text-white placeholder-gray-500 focus:outline-none focus:border-accent-primary transition-colors duration-200"
                  placeholder={t('productsServices.contact.websitePlaceholder')}
                />
              </div>
              <div>
                <label htmlFor="message" className="block text-sm font-semibold mb-2">
                  {t('productsServices.contact.message')}
                </label>
                <textarea
                  id="message"
                  name="message"
                  rows={4}
                  value={form.message}
                  onChange={(e) => setForm({ ...form, message: e.target.value })}
                  className="w-full px-4 py-3 rounded-lg bg-card border border-border text-white placeholder-gray-500 focus:outline-none focus:border-accent-primary transition-colors duration-200 resize-none"
                  placeholder={t('productsServices.contact.messagePlaceholder')}
                ></textarea>
              </div>
              {feedback && (
                <div
                  className={`text-sm px-4 py-3 rounded-lg ${feedbackKind === 'success'
                    ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30'
                    : 'bg-rose-500/10 text-rose-400 border border-rose-500/30'
                    }`}
                >
                  {feedback}
                </div>
              )}
              <button
                type="submit"
                disabled={submitting}
                className="w-full justify-center btn-primary !py-3.5 disabled:opacity-60 disabled:cursor-not-allowed"
              >
                {submitting ? t('productsServices.submitting') : t('productsServices.contact.submit')}
              </button>
            </form>
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
    </div>
  );
}
