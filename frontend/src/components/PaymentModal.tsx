import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { membershipApi, currencySymbol } from '../services/membershipApi';
import { paymentApi } from '../services/paymentApi';

interface Membership {
  id: number;
  slug: string;
  name: string;
  price: number;
  currency: string;
  period: string;
  description: string;
  popular: boolean;
  tier_type: 'saas' | 'service';
  features: string[];
  not_included: string[];
  created_at: string;
  updated_at: string;
}

interface PaymentModalProps {
  token: string;
  userName?: string;
  onClose: () => void;
  onSuccess: () => void;
}

export function PaymentModal({ token, userName, onClose, onSuccess }: PaymentModalProps) {
  const { t, i18n } = useTranslation();
  const [memberships, setMemberships] = useState<Membership[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isPaying, setIsPaying] = useState(false);
  const [error, setError] = useState('');
  // Activation happens after the Stripe redirect on the CheckoutSuccess page,
  // not here — we redirect out of this modal before any state can change.
  void onSuccess;

  useEffect(() => {
    (async () => {
      try {
        const data = await membershipApi.getMemberships();
        const paid = data.filter(
          (m) => m.price > 0 && (m as Membership).tier_type === 'saas',
        );
        setMemberships(paid as Membership[]);
        const popular = paid.find((m) => m.popular);
        setSelectedId((popular ?? paid[0])?.id ?? null);
      } catch (err) {
        setError(err instanceof Error ? err.message : t('common.errors.loadFailed'));
      } finally {
        setIsLoading(false);
      }
    })();
  }, []);

  const handlePay = async () => {
    if (selectedId == null) return;
    const tier = memberships.find((m) => m.id === selectedId);
    if (!tier) return;
    setIsPaying(true);
    setError('');
    try {
      const { checkout_url } = await paymentApi.createStripeCheckoutSession(
        token,
        tier.slug,
        i18n.language,
      );
      window.location.href = checkout_url;
      // Navigation will unmount the modal; nothing else to do here.
    } catch (err) {
      setError(err instanceof Error ? err.message : t('common.errors.paymentFailed'));
      setIsPaying(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
      <div className="relative w-full max-w-3xl bg-card border border-border rounded-2xl shadow-2xl max-h-[90vh] overflow-y-auto">
        <button
          type="button"
          onClick={onClose}
          className="absolute top-4 right-4 text-secondary hover:text-primary transition-colors"
          aria-label="Close"
        >
          <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>

        <div className="p-8">
          <div className="text-center mb-8">
            <h2 className="text-2xl md:text-3xl font-bold text-primary mb-2">
              {userName
                ? t('payment.welcomeName', { name: userName })
                : t('payment.welcome')}
            </h2>
            <p className="text-secondary">{t('payment.subtitle')}</p>
          </div>

          {isLoading ? (
            <div className="py-16 text-center text-secondary">{t('common.loading')}</div>
          ) : error && memberships.length === 0 ? (
            <div className="py-12 text-center">
              <p className="text-red-400 mb-4">{error}</p>
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 bg-card border border-border rounded-lg text-primary hover:bg-border/40 transition-colors"
              >
                {t('payment.skip')}
              </button>
            </div>
          ) : (
            <>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
                {memberships.map((tier) => {
                  const selected = selectedId === tier.id;
                  return (
                    <button
                      type="button"
                      key={tier.id}
                      onClick={() => setSelectedId(tier.id)}
                      className={`relative text-left p-5 rounded-xl border-2 transition-all ${
                        selected
                          ? 'border-accent-primary bg-accent-primary/10'
                          : 'border-border hover:border-accent-primary/50'
                      }`}
                    >
                      {tier.popular && (
                        <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-0.5 bg-accent-primary text-white text-xs font-semibold rounded-full">
                          {t('payment.popular')}
                        </div>
                      )}

                      <div className="mb-3">
                        <span className="text-2xl font-bold text-primary">{currencySymbol(tier.currency)}{tier.price}</span>
                        <span className="text-sm text-secondary">{tier.period}</span>
                      </div>
                      <ul className="space-y-1.5">
                        {tier.features.slice(0, 4).map((feature, i) => (
                          <li key={i} className="flex items-start gap-2 text-xs text-secondary">
                            <svg className="w-3.5 h-3.5 text-green-500 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="3" d="M5 13l4 4L19 7" />
                            </svg>
                            <span>{feature}</span>
                          </li>
                        ))}
                      </ul>
                    </button>
                  );
                })}
              </div>

              {error && (
                <div className="bg-red-900/40 border border-red-800 text-red-300 p-3 rounded-md text-sm mb-4">
                  {error}
                </div>
              )}

              <div className="flex flex-col-reverse sm:flex-row gap-3 justify-end">
                <button
                  type="button"
                  onClick={onClose}
                  disabled={isPaying}
                  className="px-6 py-3 rounded-lg border border-border text-secondary hover:text-primary hover:bg-border/40 transition-colors disabled:opacity-50"
                >
                  {t('payment.skip')}
                </button>
                <button
                  type="button"
                  onClick={handlePay}
                  disabled={isPaying || selectedId == null}
                  className="px-6 py-3 rounded-lg bg-accent-primary hover:bg-accent-primary/80 text-white font-semibold transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                >
                  {isPaying && (
                    <svg className="animate-spin h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                    </svg>
                  )}
                  {isPaying ? t('payment.processing') : t('payment.confirm')}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
