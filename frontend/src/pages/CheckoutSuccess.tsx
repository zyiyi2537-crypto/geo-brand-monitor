import { useEffect, useState } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { paymentApi, type StripeSessionStatus } from '../services/paymentApi';
import { useTierModal } from '../components/TierModalContext';

type LoadState = 'loading' | 'paid' | 'pending' | 'error';

export function CheckoutSuccess() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { openTierModal } = useTierModal();
  const [params] = useSearchParams();
  const [state, setState] = useState<LoadState>('loading');
  const [status, setStatus] = useState<StripeSessionStatus | null>(null);
  const [error, setError] = useState<string>('');

  const sessionId = params.get('session_id');
  const provider = params.get('provider');

  useEffect(() => {
    // MoltsPay / WeChat: fulfillment already happened via webhook/callback
    if (provider === 'moltspay' || provider === 'wechat') {
      setState('paid');
      return;
    }

    // Stripe flow
    const token = localStorage.getItem('token');
    if (!sessionId) {
      setState('error');
      setError(t('checkout.missingSession', 'Missing session_id'));
      return;
    }
    if (!token) {
      setState('error');
      setError(t('checkout.mustLogin', 'You must be logged in'));
      return;
    }
    let cancelled = false;
    let attempts = 0;

    const poll = async () => {
      try {
        const resp = await paymentApi.getStripeSessionStatus(token, sessionId);
        if (cancelled) return;
        setStatus(resp);
        if (resp.status === 'paid') {
          setState('paid');
          return;
        }
        if (resp.status === 'expired' || resp.status === 'failed') {
          setState('error');
          setError(
            resp.status === 'expired'
              ? t('checkout.expired', 'Payment expired')
              : t('checkout.failed', 'Payment failed'),
          );
          return;
        }
        attempts += 1;
        if (attempts < 5) {
          setTimeout(poll, 1500);
        } else {
          setState('pending');
        }
      } catch (err) {
        if (cancelled) return;
        setState('error');
        setError(
          err instanceof Error
            ? err.message
            : t('checkout.verifyFailed', 'Failed to verify payment'),
        );
      }
    };

    void poll();
    return () => {
      cancelled = true;
    };
  }, [sessionId, provider, t]);

  return (
    <div className="min-h-[60vh] flex items-center justify-center px-6">
      <div className="max-w-md w-full bg-card border border-border rounded-2xl p-8 text-center">
        {state === 'loading' && (
          <>
            <div className="mx-auto mb-4 w-12 h-12 rounded-full border-4 border-accent-primary border-t-transparent animate-spin" />
            <h1 className="text-xl font-bold text-primary mb-2">
              {t('checkout.verifying', 'Verifying your payment…')}
            </h1>
            <p className="text-sm text-secondary">
              {t('checkout.verifyingHint', 'This usually takes a few seconds.')}
            </p>
          </>
        )}

        {state === 'paid' && (
          <>
            <div className="mx-auto mb-4 w-14 h-14 rounded-full bg-emerald-500/10 flex items-center justify-center">
              <svg
                className="w-8 h-8 text-emerald-500"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="3" d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <h1 className="text-2xl font-bold text-primary mb-2">
              {t('checkout.successTitle', 'Subscription activated')}
            </h1>
            <p className="text-sm text-secondary mb-6">
              {t(
                'checkout.successBody',
                'Thanks! Your membership is now active. You can start running full GEO checks right away.',
              )}
            </p>
            <div className="flex flex-col sm:flex-row gap-3 justify-center">
              <button
                type="button"
                onClick={() => navigate('/account/membership')}
                className="px-5 py-2.5 rounded-lg bg-accent-primary text-white font-semibold hover:bg-accent-primary/80 transition-colors"
              >
                {t('checkout.viewMembership', 'View membership')}
              </button>
              <button
                type="button"
                onClick={() => navigate('/')}
                className="px-5 py-2.5 rounded-lg border border-border text-secondary hover:text-primary hover:bg-border/40 transition-colors"
              >
                {t('checkout.runCheck', 'Run a check')}
              </button>
            </div>
          </>
        )}

        {state === 'pending' && (
          <>
            <h1 className="text-xl font-bold text-primary mb-2">
              {t('checkout.pendingTitle', 'Payment received — activating…')}
            </h1>
            <p className="text-sm text-secondary mb-4">
              {t(
                'checkout.pendingBody',
                'Payment is still confirming. Your membership will activate within a minute. Refresh this page or check the membership dashboard.',
              )}
            </p>
            <button
              type="button"
              onClick={() => navigate('/account/membership')}
              className="px-5 py-2.5 rounded-lg bg-accent-primary text-white font-semibold hover:bg-accent-primary/80 transition-colors"
            >
              {t('checkout.viewMembership', 'View membership')}
            </button>
          </>
        )}

        {state === 'error' && (
          <>
            <h1 className="text-xl font-bold text-rose-400 mb-2">
              {t('checkout.errorTitle', 'Payment verification failed')}
            </h1>
            <p className="text-sm text-secondary mb-4">{error}</p>
            <button
              type="button"
              onClick={openTierModal}
              className="px-5 py-2.5 rounded-lg border border-border text-secondary hover:text-primary hover:bg-border/40 transition-colors"
            >
              {t('checkout.backToPlans', 'Back to plans')}
            </button>
          </>
        )}

        {status?.payment_status && state !== 'loading' && (
          <p className="mt-6 text-xs text-muted">
            {t('checkout.stripeStatus', 'Stripe status')}:{' '}
            <span className="font-mono">{status.payment_status}</span>
          </p>
        )}
      </div>
    </div>
  );
}
