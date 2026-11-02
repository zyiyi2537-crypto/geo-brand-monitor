import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { BrowserProvider, randomBytes, hexlify } from 'ethers';
import { QRCodeSVG } from 'qrcode.react';
import { membershipApi, type Membership, formatTierPrice } from '../services/membershipApi';
import { paymentApi } from '../services/paymentApi';
import { useMembership } from '../hooks/useMembership';
import { useAuthModal } from '../contexts/AuthModalContext';
import { useTierModal } from '../components/TierModalContext';

type PayMethod = 'stripe' | 'usdc' | 'wechat';

const BASE_CHAIN_ID = 8453;
const USDC_CONTRACT = '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913';
const PAY_EXECUTE_URL = '/pay/execute';

// Resolve a single injected EIP-1193 provider in the presence of multiple
// wallet extensions. Passing `window.ethereum` directly to ethers
// `BrowserProvider` can recurse through a chain of proxies (MetaMask +
// Phantom / Coinbase / OKX etc. wrap each other on window.ethereum), which
// manifests as `Maximum call stack size exceeded` during `eth_requestAccounts`.
//
// Strategy:
//   1. EIP-6963: ask wallets to announce themselves, prefer MetaMask.
//   2. Legacy `window.ethereum.providers[]` array (MetaMask populates it when
//      it detects peers), prefer MetaMask.
//   3. Fall back to raw `window.ethereum`.
async function pickInjectedProvider(): Promise<any> {
  const discovered: Array<{ info: { rdns: string; name: string }; provider: any }> = [];
  const handler = (event: any) => {
    if (event?.detail?.provider) discovered.push(event.detail);
  };
  window.addEventListener('eip6963:announceProvider', handler as EventListener);
  window.dispatchEvent(new Event('eip6963:requestProvider'));
  // Give wallets a tick to respond. 100ms is enough in practice; we
  // unregister the handler afterwards so late announcers don't leak.
  await new Promise((r) => setTimeout(r, 100));
  window.removeEventListener('eip6963:announceProvider', handler as EventListener);

  const metaMaskAnnounced = discovered.find((p) => p.info?.rdns === 'io.metamask');
  if (metaMaskAnnounced) return metaMaskAnnounced.provider;
  if (discovered.length > 0) return discovered[0].provider;

  const legacy = (window as any).ethereum;
  if (legacy?.providers?.length) {
    const mm = legacy.providers.find((p: any) => p.isMetaMask && !p.isBraveWallet);
    if (mm) return mm;
    return legacy.providers[0];
  }
  return legacy ?? null;
}

export function CheckoutPending() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const { openAuthModal } = useAuthModal();
  const { openTierModal } = useTierModal();
  const [params] = useSearchParams();
  const { token, isLoggedIn } = useMembership();

  const slug = params.get('slug') ?? '';
  // Optional ?provider= hint from PaymentsTab's "Pay" button on a pending row.
  // Lets the user drop back onto the same method they started the order with
  // so the backend's session-reuse path (<90min wechat / <30min moltspay) is hit.
  const providerHint = params.get('provider') ?? '';

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

  const [tier, setTier] = useState<Membership | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [payError, setPayError] = useState<string | null>(null);
  // All 3 methods available regardless of locale. Default to Stripe since it
  // works globally for both USD and RMB cardholders. Honor ?provider= hint
  // (moltspay → usdc card) when the user lands from a pending-row Pay link.
  const [payMethod, setPayMethodRaw] = useState<PayMethod>(() => {
    if (providerHint === 'wechat') return 'wechat';
    if (providerHint === 'moltspay') return 'usdc';
    return 'stripe';
  });
  const setPayMethod = (method: PayMethod) => {
    setPayMethodRaw(method);
    setPayError(null);
    // Reset WeChat state when switching away so the pay button reappears
    if (method !== 'wechat' && wechatStep === 'polling') {
      if (wechatPollRef.current) { clearInterval(wechatPollRef.current); wechatPollRef.current = null; }
      setWechatStep('idle');
      setWechatCodeUrl('');
    }
  };

  // USDC / Web3 state
  const [usdcAmount, setUsdcAmount] = useState<number>(0);
  const [walletAddr, setWalletAddr] = useState<string>('');
  const [usdcStep, setUsdcStep] = useState<'idle' | 'connecting' | 'paying' | 'verifying' | 'done'>('idle');
  // Track pending payment_id so user can cancel + re-initiate.
  const [usdcPaymentId, setUsdcPaymentId] = useState<number>(0);

  // WeChat Pay state
  const [wechatCodeUrl, setWechatCodeUrl] = useState<string>('');
  const [wechatPaymentId, setWechatPaymentId] = useState<number>(0);
  const [wechatAmount, setWechatAmount] = useState<number>(0);
  const [wechatStep, setWechatStep] = useState<'idle' | 'creating' | 'polling' | 'done'>('idle');
  const wechatPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!isLoggedIn) {
      openAuthModal('login');
      navigate('/', { replace: true });
      return;
    }
    if (!slug) {
      setLoadError(t('checkoutPending.missingSlug'));
      setIsLoading(false);
      return;
    }
    let cancelled = false;
    setIsLoading(true);
    membershipApi
      .getMemberships()
      .then((list) => {
        if (cancelled) return;
        const found = list.find((m) => m.slug === slug);
        if (!found) {
          setLoadError(t('checkoutPending.notFound'));
        } else if (found.tier_type !== 'saas') {
          setLoadError(t('checkoutPending.notSubscribable'));
        } else {
          setTier(found);
        }
      })
      .catch((err) => {
        if (cancelled) return;
        setLoadError(err instanceof Error ? err.message : t('common.errors.loadFailed'));
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => { cancelled = true; };
  }, [slug, isLoggedIn, navigate, t]);

  const tierInfo = useMemo(() => (tier ? tierText(tier) : null), [tier, i18n.language]);
  const features = useMemo(() => tierInfo?.features.slice(0, 6) ?? [], [tierInfo]);

  const handleStripePay = async () => {
    if (!tier || !token || submitting) return;
    setSubmitting(true);
    setPayError(null);
    try {
      const { checkout_url } = await paymentApi.createStripeCheckoutSession(token, tier.slug, i18n.language);
      window.location.href = checkout_url;
    } catch (err) {
      setPayError(err instanceof Error ? err.message : t('checkoutPending.payError'));
      setSubmitting(false);
    }
  };

  const slugToServiceId: Record<string, string> = {
    pro: 'membership-detector',
    starter: 'membership-starter',
    growth: 'membership-growth',
  };

  const handleUsdcPay = async () => {
    if (!tier || !token || submitting) return;

    const serviceId = slugToServiceId[tier.slug];
    if (!serviceId) {
      setPayError('USDC payment not available for this plan.');
      return;
    }

    setSubmitting(true);
    setPayError(null);
    try {
      // 1. Create backend order
      setUsdcStep('connecting');
      const order = await paymentApi.createMoltsPaySession(token, tier.slug);
      setUsdcAmount(order.amount_usdc);
      setUsdcPaymentId(order.payment_id);

      // 2. Pre-flight: request 402 from MoltsPayServer to get payment
      //    requirements BEFORE touching the wallet. If the payment service
      //    is down the user sees an error instantly — no stale wallet popup.
      // user_id comes from the backend response (JWT-derived) so it's
      // always present — localStorage['user'] only stores email.
      const executeBody = {
        service: serviceId,
        params: { user_id: order.user_id, membership_slug: tier.slug },
        chain: 'base',
      };

      const res402 = await fetch(PAY_EXECUTE_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(executeBody),
      });

      if (res402.status !== 402) {
        const errBody = await res402.text().catch(() => '');
        console.error(`/pay/execute: expected 402, got ${res402.status}`, errBody);
        throw new Error(t('checkoutPending.usdcServiceUnavailable', 'USDC payment service is temporarily unavailable. Please try another payment method.'));
      }

      const reqHeader = res402.headers.get('x-payment-required');
      if (!reqHeader) throw new Error('Missing x-payment-required header');

      let requirements: any[];
      try {
        const parsed = JSON.parse(atob(reqHeader));
        if (parsed.accepts && Array.isArray(parsed.accepts)) {
          requirements = parsed.accepts;
        } else if (Array.isArray(parsed)) {
          requirements = parsed;
        } else {
          requirements = [parsed];
        }
      } catch {
        throw new Error('Invalid payment requirements');
      }

      const req = requirements.find((r: any) => r.network === 'eip155:8453' && r.scheme === 'exact');
      if (!req) throw new Error('No Base chain payment requirement found');

      const payTo = req.payTo || req.resource;
      const amountRaw = req.amount || req.maxAmountRequired;
      if (!payTo || !amountRaw) throw new Error('Missing payTo or amount in requirements');

      const extra = req.extra && typeof req.extra === 'object' ? req.extra : { name: 'USD Coin', version: '2' };

      // 3. Now connect wallet — only after we know the payment service is up
      setUsdcStep('paying');
      const ethereum = await pickInjectedProvider();
      if (!ethereum) {
        throw new Error(t('checkoutPending.usdcNoWallet', 'Please install MetaMask or another Web3 wallet.'));
      }

      // ALL wallet RPC calls go through the native EIP-1193 `request` method
      // rather than ethers `BrowserProvider.send()`. BrowserProvider wraps the
      // provider's `request` in its own JSON-RPC layer which re-triggers the
      // proxy chain recursion (`Maximum call stack size exceeded`).
      // BrowserProvider is only used to obtain a Signer for signTypedData.
      const accounts: string[] = await ethereum.request({ method: 'eth_requestAccounts' });
      const fromAddr = accounts[0];

      const chainIdHex: string = await ethereum.request({ method: 'eth_chainId' });
      if (parseInt(chainIdHex, 16) !== BASE_CHAIN_ID) {
        try {
          await ethereum.request({
            method: 'wallet_switchEthereumChain',
            params: [{ chainId: '0x' + BASE_CHAIN_ID.toString(16) }],
          });
        } catch (switchErr: any) {
          if (switchErr.code === 4902) {
            await ethereum.request({
              method: 'wallet_addEthereumChain',
              params: [{
                chainId: '0x' + BASE_CHAIN_ID.toString(16),
                chainName: 'Base',
                nativeCurrency: { name: 'ETH', symbol: 'ETH', decimals: 18 },
                rpcUrls: ['https://mainnet.base.org'],
                blockExplorerUrls: ['https://basescan.org'],
              }],
            });
          } else {
            throw switchErr;
          }
        }
      }

      // Pass the known address to getSigner() so ethers does NOT call
      // eth_requestAccounts again internally (which would recurse).
      const provider = new BrowserProvider(ethereum);
      const signer = await provider.getSigner(fromAddr);
      setWalletAddr(fromAddr);

      // 3.5. Pre-flight USDC balance check. CDP's verifier reports
      // "contract execution reverted" as `invalid_payload`, which hides the
      // real cause (usually: not enough USDC). Checking first lets us fail
      // with a specific message *before* making the user sign anything.
      try {
        const balHex = await ethereum.request({
          method: 'eth_call',
          params: [
            {
              to: USDC_CONTRACT,
              // balanceOf(address) selector + 32-byte padded address
              data: '0x70a08231' + fromAddr.slice(2).toLowerCase().padStart(64, '0'),
            },
            'latest',
          ],
        });
        const balance = BigInt(balHex);
        const required = BigInt(amountRaw);
        if (balance < required) {
          // USDC = 6 decimals. Format with 2 decimals for user-facing message.
          const fmt = (v: bigint) => (Number(v) / 1e6).toFixed(2);
          throw new Error(
            t(
              'checkoutPending.usdcInsufficient',
              'Insufficient USDC balance on Base: you have ${{have}} USDC, need ${{need}} USDC. Top up your wallet and try again.',
              { have: fmt(balance), need: fmt(required) },
            ) as string,
          );
        }
      } catch (balErr: any) {
        // If balance check itself fails (RPC hiccup, unsupported method in
        // some wallet), don't block the flow — let the user still try, and
        // we'll surface a best-effort error after CDP rejects.
        if (balErr instanceof Error && balErr.message.includes('USDC balance on Base')) {
          throw balErr;
        }
        console.warn('USDC balance preflight failed, continuing:', balErr);
      }

      // 4. Sign EIP-3009 TransferWithAuthorization (gasless)
      const authorization = {
        from: fromAddr,
        to: payTo,
        value: amountRaw,
        validAfter: '0',
        validBefore: String(Math.floor(Date.now() / 1000) + 3600),
        nonce: hexlify(randomBytes(32)),
      };

      const domain = {
        name: extra.name || 'USD Coin',
        version: extra.version || '2',
        chainId: BASE_CHAIN_ID,
        verifyingContract: USDC_CONTRACT,
      };

      const types = {
        TransferWithAuthorization: [
          { name: 'from', type: 'address' },
          { name: 'to', type: 'address' },
          { name: 'value', type: 'uint256' },
          { name: 'validAfter', type: 'uint256' },
          { name: 'validBefore', type: 'uint256' },
          { name: 'nonce', type: 'bytes32' },
        ],
      };

      const signature = await signer.signTypedData(domain, types, authorization);

      // 5. Send paid request with X-Payment header
      setUsdcStep('verifying');
      const payload = {
        x402Version: 2,
        scheme: 'exact',
        network: 'eip155:8453',
        payload: { authorization, signature },
        accepted: {
          scheme: 'exact',
          network: 'eip155:8453',
          asset: USDC_CONTRACT,
          amount: amountRaw,
          payTo,
          maxTimeoutSeconds: 300,
          extra,
        },
      };

      const paymentHeader = btoa(JSON.stringify(payload));
      const paidRes = await fetch(PAY_EXECUTE_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Payment': paymentHeader,
        },
        body: JSON.stringify(executeBody),
      });

      if (!paidRes.ok) {
        const errData = await paidRes.json().catch(() => ({}));
        const rawErr: string = errData.error || '';
        // CDP classifies any on-chain revert of `transferWithAuthorization`
        // as `invalid_payload`. In practice the common cause is insufficient
        // USDC balance — rewrite to something actionable. (The proactive
        // balance check above usually catches this first, but the balance
        // might change between check and sign on a busy wallet.)
        if (/invalid_payload/i.test(rawErr) || /execution reverted/i.test(rawErr)) {
          throw new Error(
            t(
              'checkoutPending.usdcRevert',
              'On-chain verification failed. Most common cause: your USDC balance on Base is below the required amount. Please check the wallet and try again.',
            ) as string,
          );
        }
        throw new Error(rawErr || `Payment failed (${paidRes.status})`);
      }

      // 6. MoltsPayServer has called /fulfill — poll to confirm
      setUsdcStep('done');
      navigate('/checkout/success?provider=moltspay');
    } catch (err: any) {
      if (err?.code === 4001 || err?.code === 'ACTION_REJECTED') {
        setPayError(t('checkoutPending.usdcRejected', 'Transaction rejected by user.'));
      } else {
        setPayError(err instanceof Error ? err.message : t('checkoutPending.payError'));
      }
      setUsdcStep('idle');
    } finally {
      setSubmitting(false);
    }
  };

  // Cleanup WeChat polling on unmount
  useEffect(() => {
    return () => {
      if (wechatPollRef.current) clearInterval(wechatPollRef.current);
    };
  }, []);

  const handleWechatPay = async () => {
    if (!tier || !token || submitting) return;
    setSubmitting(true);
    setPayError(null);
    setWechatStep('creating');
    try {
      const order = await paymentApi.createWechatPaySession(token, tier.slug);
      setWechatCodeUrl(order.code_url);
      setWechatPaymentId(order.payment_id);
      setWechatAmount(order.amount_cny);
      setWechatStep('polling');
      setSubmitting(false);

      // Poll for payment completion every 3 seconds
      wechatPollRef.current = setInterval(async () => {
        try {
          const status = await paymentApi.getWechatPayStatus(token, order.payment_id);
          if (status.status === 'paid') {
            if (wechatPollRef.current) clearInterval(wechatPollRef.current);
            setWechatStep('done');
            navigate('/checkout/success?provider=wechat');
          }
        } catch {
          // Polling error — continue silently
        }
      }, 3000);
    } catch (err) {
      setPayError(err instanceof Error ? err.message : t('checkoutPending.payError'));
      setWechatStep('idle');
      setSubmitting(false);
    }
  };

  const handlePay = payMethod === 'stripe'
    ? handleStripePay
    : payMethod === 'wechat'
      ? handleWechatPay
      : handleUsdcPay;

  // Cancel the current pending session and start a fresh one. Used when the
  // QR code expired, the wallet flow stalled, or the user just wants a do-over.
  const handleReinitiate = async () => {
    if (!token || submitting) return;
    setSubmitting(true);
    setPayError(null);
    try {
      if (payMethod === 'wechat' && wechatPaymentId) {
        if (wechatPollRef.current) {
          clearInterval(wechatPollRef.current);
          wechatPollRef.current = null;
        }
        await paymentApi.cancelWechatPaySession(token, wechatPaymentId);
        setWechatStep('idle');
        setWechatCodeUrl('');
        setWechatPaymentId(0);
        setSubmitting(false);
        await handleWechatPay();
        return;
      }
      if (payMethod === 'usdc' && usdcPaymentId) {
        await paymentApi.cancelMoltsPaySession(token, usdcPaymentId);
        setUsdcStep('idle');
        setUsdcPaymentId(0);
        setWalletAddr('');
        setSubmitting(false);
        await handleUsdcPay();
        return;
      }
    } catch (err) {
      setPayError(err instanceof Error ? err.message : t('checkoutPending.payError'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-[60vh] flex items-center justify-center px-6 py-16">
      <div className="max-w-xl w-full bg-card border border-border rounded-2xl p-8">
        <div className="mb-6 flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-accent-primary/10 flex items-center justify-center">
            <svg className="w-5 h-5 text-accent-primary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <div>
            <h1 className="text-xl font-bold text-primary">{t('checkoutPending.title')}</h1>
            <p className="text-xs text-secondary">{t('checkoutPending.subtitle')}</p>
          </div>
        </div>

        {isLoading && (
          <div className="py-12 text-center text-sm text-secondary">{t('checkoutPending.loading')}</div>
        )}

        {!isLoading && loadError && (
          <div className="py-8">
            <p className="text-sm text-rose-400 mb-6">{loadError}</p>
            <button
              type="button"
              onClick={openTierModal}
              className="w-full justify-center btn-primary !py-3"
            >
              {t('checkoutPending.backToPlans')}
            </button>
          </div>
        )}

        {!isLoading && tier && (
          <>
            {/* Plan info */}
            <div className="rounded-xl border border-border p-5 mb-5 bg-[rgba(255,255,255,0.02)]">
              <div className="flex items-start justify-between gap-4 mb-3">
                <div>
                  <div className="text-sm text-secondary">{t('checkoutPending.planLabel')}</div>
                  <div className="text-lg font-bold text-primary mt-0.5">{tierInfo?.name || tier.name}</div>
                </div>
                {tier.popular && (
                  <span className="px-2 py-0.5 rounded-full bg-accent-primary/10 text-accent-primary text-[10px] font-semibold uppercase tracking-wider">
                    {t('checkoutPending.popular')}
                  </span>
                )}
              </div>
              <p className="text-xs text-secondary leading-relaxed mb-4">{tierInfo?.description || tier.description}</p>
              {features.length > 0 && (
                <ul className="space-y-2 mb-4">
                  {features.map((f, i) => (
                    <li key={i} className="flex items-start gap-2 text-xs text-primary">
                      <svg className="w-4 h-4 text-accent-primary shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M5 13l4 4L19 7" />
                      </svg>
                      <span className="leading-snug">{f}</span>
                    </li>
                  ))}
                </ul>
              )}
              <div className="flex items-end justify-between pt-4 border-t border-border">
                <span className="text-sm text-secondary">{t('checkoutPending.totalLabel')}</span>
                <span className="text-2xl font-bold text-accent-primary">
                  {formatTierPrice(tier)}
                  <span className="text-sm text-secondary font-medium ml-1">{tierInfo?.period || tier.period}</span>
                </span>
              </div>
            </div>

            {/* Payment method selector */}
            <div className="mb-5">
              <div className="flex items-center gap-2 mb-3">
                <svg className="w-4 h-4 text-accent-primary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                </svg>
                <span className="text-sm font-semibold text-primary">{t('checkoutPending.methodLabel')}</span>
              </div>

              {/* All 3 payment methods shown regardless of locale. Selection is
                  indicated purely via thick colored border + ring glow + bg tint
                  (no radio dot) so a single glance disambiguates the active card.  */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <button
                  type="button"
                  onClick={() => setPayMethod('stripe')}
                  disabled={submitting}
                  className={`relative rounded-xl p-4 text-left transition-all ${
                    payMethod === 'stripe'
                      ? 'border-4 border-[var(--accent-primary)] ring-2 ring-[var(--accent-primary)]/30 bg-[var(--accent-primary)]/5 opacity-100'
                      : 'border-2 border-transparent opacity-50 hover:opacity-80'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <span className="text-xl">💳</span>
                    <div>
                      <div className="text-sm font-semibold text-primary">{t('checkoutPending.methodStripeLabel', 'Credit Card')}</div>
                      <div className="text-[10px] text-secondary">Stripe</div>
                    </div>
                  </div>
                </button>
                <button
                  type="button"
                  onClick={() => setPayMethod('usdc')}
                  disabled={submitting}
                  className={`relative rounded-xl p-4 text-left transition-all ${
                    payMethod === 'usdc'
                      ? 'border-4 border-[var(--accent-primary)] ring-2 ring-[var(--accent-primary)]/30 bg-[var(--accent-primary)]/5 opacity-100'
                      : 'border-2 border-transparent opacity-50 hover:opacity-80'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <svg className="w-6 h-6 shrink-0" viewBox="0 0 32 32" fill="none">
                      <circle cx="16" cy="16" r="16" fill="#2775CA"/>
                      <path d="M20.5 18.5c0-2.1-1.3-2.8-3.8-3.1-1.8-.3-2.2-.7-2.2-1.4s.6-1.2 1.8-1.2c1.1 0 1.6.4 1.9 1.2.1.2.2.3.4.3h1c.2 0 .4-.2.3-.4-.3-1.2-1.1-2.1-2.4-2.4v-1.4c0-.2-.2-.4-.4-.4h-.9c-.2 0-.4.2-.4.4v1.3c-1.7.3-2.8 1.3-2.8 2.7 0 2 1.2 2.7 3.7 3.1 1.7.3 2.3.7 2.3 1.5s-.8 1.3-1.9 1.3c-1.5 0-2-.6-2.2-1.3-.1-.2-.2-.3-.4-.3h-1c-.2 0-.4.2-.3.4.4 1.4 1.2 2.2 2.7 2.5v1.4c0 .2.2.4.4.4h.9c.2 0 .4-.2.4-.4v-1.4c1.7-.2 2.9-1.3 2.9-2.8z" fill="#fff"/>
                    </svg>
                    <div>
                      <div className="text-sm font-semibold text-primary">USDC</div>
                      <div className="text-[10px] text-secondary">Moltspay / Base</div>
                    </div>
                  </div>
                </button>
                <button
                  type="button"
                  onClick={() => setPayMethod('wechat')}
                  disabled={submitting}
                  className={`relative rounded-xl p-4 text-left transition-all ${
                    payMethod === 'wechat'
                      ? 'border-4 border-[#07C160] ring-2 ring-[#07C160]/30 bg-[#07C160]/5 opacity-100'
                      : 'border-2 border-transparent opacity-50 hover:opacity-80'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <svg className="w-7 h-7 shrink-0" viewBox="0 0 48 48" fill="none">
                      <circle cx="24" cy="24" r="24" fill="#07C160"/>
                      <path d="M30.2 20.4c-.3 0-.6 0-.9.1.4-3.5-3-6.5-7.3-6.5-4.1 0-7.5 2.8-7.5 6.3 0 2 1.1 3.8 2.9 5l-.7 2.2 2.6-1.3c.8.2 1.5.3 2.3.3h.4c-.1-.4-.1-.8-.1-1.2 0-3.2 2.9-5.7 6.5-5.7.6 0 1.2.1 1.8.2zm-10-2.1c.6 0 1 .5 1 1s-.4 1-1 1-1-.5-1-1 .4-1 1-1zm-4.8 2c-.6 0-1-.5-1-1s.4-1 1-1 1 .5 1 1-.4 1-1 1z" fill="#fff"/>
                      <path d="M36 25.9c0-2.9-2.9-5.2-6.5-5.2s-6.5 2.3-6.5 5.2 2.9 5.2 6.5 5.2c.7 0 1.4-.1 2-.3l2.1 1.1-.6-1.8c1.6-1 2.5-2.5 2.5-4.2h.5zm-8.6-1c-.5 0-.8-.4-.8-.8s.4-.8.8-.8.8.4.8.8-.4.8-.8.8zm4.2 0c-.5 0-.8-.4-.8-.8s.4-.8.8-.8.8.4.8.8-.4.8-.8.8z" fill="#fff"/>
                    </svg>
                    <div>
                      <div className="text-sm font-semibold text-primary">{t('checkoutPending.methodWechatLabel')}</div>
                      <div className="text-[10px] text-secondary">WeChat Pay</div>
                    </div>
                  </div>
                </button>
              </div>
            </div>

            {/* WeChat Pay info */}
            {payMethod === 'wechat' && wechatStep === 'idle' && (
              <div className="rounded-lg bg-[rgba(255,255,255,0.02)] border border-border p-4 mb-5">
                <p className="text-xs text-secondary leading-relaxed">{t('checkoutPending.methodWechat')}</p>
              </div>
            )}

            {/* WeChat QR code panel */}
            {payMethod === 'wechat' && wechatStep === 'polling' && wechatCodeUrl && (
              <div className="rounded-lg bg-[#07C160]/5 border border-[#07C160]/30 p-5 mb-5">
                <div className="flex flex-col items-center gap-4">
                  <p className="text-sm font-medium text-primary">{t('checkoutPending.wechatScanQr')}</p>
                  <div className="bg-white p-3 rounded-lg">
                    <QRCodeSVG value={wechatCodeUrl} size={200} />
                  </div>
                  <div className="w-full space-y-2 text-xs">
                    <div className="flex justify-between">
                      <span className="text-secondary">{t('checkoutPending.wechatAmount')}</span>
                      <span className="font-mono text-primary font-semibold">¥{wechatAmount.toFixed(2)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-secondary">{t('checkoutPending.wechatStatus')}</span>
                      <span className="text-[#07C160] font-medium flex items-center gap-1.5">
                        <svg className="animate-spin h-3 w-3" fill="none" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                        </svg>
                        {t('checkoutPending.wechatWaiting')}
                      </span>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={handleReinitiate}
                    disabled={submitting}
                    className="mt-2 text-xs text-secondary hover:text-[#07C160] underline underline-offset-2 disabled:opacity-50"
                  >
                    {t('checkoutPending.reinitiate', '重新发起支付')}
                  </button>
                </div>
              </div>
            )}

            {/* WeChat creating spinner */}
            {payMethod === 'wechat' && wechatStep === 'creating' && (
              <div className="rounded-lg bg-[#07C160]/5 border border-[#07C160]/30 p-5 mb-5 text-center">
                <svg className="animate-spin h-6 w-6 mx-auto mb-2 text-[#07C160]" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                <p className="text-xs text-secondary">{t('checkoutPending.submitting')}</p>
              </div>
            )}

            {/* Stripe info */}
            {payMethod === 'stripe' && !submitting && (
              <div className="rounded-lg bg-[rgba(255,255,255,0.02)] border border-border p-4 mb-5">
                <p className="text-xs text-secondary leading-relaxed">{t('checkoutPending.methodStripe')}</p>
              </div>
            )}

            {/* USDC info */}
            {payMethod === 'usdc' && usdcStep === 'idle' && (
              <div className="rounded-lg bg-[rgba(255,255,255,0.02)] border border-border p-4 mb-5">
                <p className="text-xs text-secondary leading-relaxed">
                  {t('checkoutPending.methodUsdc', 'Pay with USDC on Base chain via your Web3 wallet (MetaMask, etc.). Click "Pay Now" to connect wallet and approve the transfer.')}
                </p>
                {!(window as any).ethereum && (() => {
                  // Mobile browsers don't have window.ethereum — the wallet
                  // app is a separate process. Give mobile users a deep link
                  // that opens MetaMask's in-app browser at this exact URL,
                  // where window.ethereum will be injected.
                  const isMobile = /android|iphone|ipad|ipod/i.test(navigator.userAgent);
                  if (isMobile) {
                    const host = window.location.host;
                    const path = window.location.pathname + window.location.search;
                    const mmDeepLink = `https://metamask.app.link/dapp/${host}${path}`;
                    return (
                      <div className="mt-3">
                        <p className="text-xs text-yellow-400 mb-2">
                          {t('checkoutPending.usdcMobileHint', 'Mobile browsers cannot access wallet extensions. Open in your wallet app:')}
                        </p>
                        <a
                          href={mmDeepLink}
                          className="inline-flex items-center gap-2 text-xs font-semibold text-[#F6851B] border border-[#F6851B]/50 rounded-lg px-3 py-2 hover:bg-[#F6851B]/10 transition-colors"
                        >
                          <svg className="w-4 h-4" viewBox="0 0 35 33" fill="none">
                            <path d="M32.96 1l-13.13 9.72 2.44-5.71L32.96 1z" fill="#E17726"/>
                            <path d="M2.04 1l13.02 9.81-2.33-5.8L2.04 1zM28.23 23.53l-3.5 5.34 7.49 2.05 2.15-7.28-6.14-.11zM.64 23.64l2.14 7.28 7.48-2.05-3.49-5.34-6.13.11z" fill="#E27625"/>
                          </svg>
                          {t('checkoutPending.usdcOpenMetaMask', 'Open in MetaMask')}
                        </a>
                      </div>
                    );
                  }
                  return (
                    <p className="text-xs text-yellow-400 mt-2">
                      {t('checkoutPending.usdcNoWallet', 'Please install MetaMask or another Web3 wallet.')}
                    </p>
                  );
                })()}
              </div>
            )}

            {/* USDC progress panel */}
            {payMethod === 'usdc' && usdcStep !== 'idle' && usdcStep !== 'done' && (
              <div className="rounded-lg bg-accent-primary/5 border border-accent-primary/30 p-5 mb-5">
                <div className="space-y-3 text-xs">
                  {walletAddr && (
                    <div className="flex justify-between">
                      <span className="text-secondary">{t('checkoutPending.usdcYourWallet', 'Your wallet')}</span>
                      <span className="font-mono text-primary">{walletAddr.slice(0, 8)}...{walletAddr.slice(-6)}</span>
                    </div>
                  )}
                  <div className="flex justify-between">
                    <span className="text-secondary">{t('checkoutPending.usdcAmount', 'Amount')}</span>
                    <span className="font-mono text-primary">{usdcAmount || '...'} USDC</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-secondary">{t('checkoutPending.usdcChain', 'Chain')}</span>
                    <span className="font-mono text-primary">Base</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-secondary">{t('checkoutPending.usdcStatus', 'Status')}</span>
                    <span className="text-yellow-400 font-medium flex items-center gap-1.5">
                      <svg className="animate-spin h-3 w-3" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                      </svg>
                      {usdcStep === 'connecting' && t('checkoutPending.usdcConnecting', 'Connecting wallet...')}
                      {usdcStep === 'paying' && t('checkoutPending.usdcSigning', 'Please approve in your wallet...')}
                      {usdcStep === 'verifying' && t('checkoutPending.usdcVerifying', 'Confirming on chain...')}
                    </span>
                  </div>
                  {/* Re-initiate is only safe before the user has signed the
                      EIP-3009 authorization. Once `verifying`, a canceled
                      session could strand a broadcast tx — hide the button. */}
                  {(usdcStep === 'connecting' || usdcStep === 'paying') && (
                    <button
                      type="button"
                      onClick={handleReinitiate}
                      disabled={submitting}
                      className="text-xs text-secondary hover:text-accent-primary underline underline-offset-2 disabled:opacity-50"
                    >
                      {t('checkoutPending.reinitiate', '重新发起支付')}
                    </button>
                  )}
                </div>
              </div>
            )}

            {payError && (
              <div className="mb-4 text-xs px-4 py-3 rounded-lg bg-rose-500/10 text-rose-400 border border-rose-500/30">
                {payError}
              </div>
            )}

            <div className="flex flex-col sm:flex-row gap-3">
              {usdcStep === 'idle' && wechatStep !== 'polling' && (
                <button
                  type="button"
                  onClick={handlePay}
                  disabled={submitting}
                  className="flex-1 justify-center btn-primary !py-3 disabled:opacity-60 disabled:cursor-not-allowed"
                >
                  {submitting
                    ? t('checkoutPending.submitting')
                    : payMethod === 'usdc'
                      ? t('checkoutPending.usdcPayNow', 'Connect Wallet & Pay')
                      : payMethod === 'wechat'
                        ? t('checkoutPending.wechatPayNow')
                        : t('checkoutPending.payNow')}
                </button>
              )}
              <button
                type="button"
                onClick={() => openTierModal()}
                disabled={submitting}
                className="px-5 py-3 rounded-lg border border-border text-secondary hover:text-primary hover:bg-border/40 transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
              >
                {t('checkoutPending.cancel')}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
