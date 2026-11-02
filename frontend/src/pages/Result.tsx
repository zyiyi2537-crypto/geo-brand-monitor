import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useLoadNs } from '../i18n/useLoadNs';
import { useAuthModal } from '../contexts/AuthModalContext';
import { PaymentModal } from '../components/PaymentModal';
import { Tooltip } from '../components/Tooltip';
import { useMembership } from '../hooks/useMembership';
import { useTierModal } from '../components/TierModalContext';
import { geoApi, ApiError } from '../services/geoApi';
import { resolveCategoryVisual } from '../components/result/CategoryVisual';
import { CheckProgress } from '../components/result/CheckProgress';
import { RerunModeDropdown } from '../components/result/RerunModeDropdown';
import { ADVANCED_MODES, type AdvancedMode, type RerunMode } from '../components/result/rerunModes';
import { ResultPanel as AdvancedResultPanel, type AnyAdvancedResult } from './Advanced';
import { exportPdfReport } from '../utils/exportPdfReport';
import { exportAdvancedPdfReport } from '../utils/exportAdvancedPdfReport';
import { validateUrl, normalizeUrl } from '../utils/validateUrl';
import type { GeoTestResult, CheckResult } from '../types/geo';

/**
 * Render a check's user-facing message. Prefers i18n key + params (emitted
 * via geo_checker.emit_check), falls back to the raw English `message`
 * for legacy un-migrated checks.
 */
function renderCheckMessage(
  check: CheckResult,
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  if (check.message_key) {
    return t(check.message_key, (check.message_params || {}) as Record<string, unknown>);
  }
  return check.message;
}

/**
 * Render a check's fix recommendation. Prefers `fix_key` + `fix_params`
 * (emitted via emit_fix), falls back to the raw English `fix` text.
 * Returns an empty string when no fix is available so callers can boolean-
 * check the result.
 */
function renderCheckFix(
  check: CheckResult,
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  if (check.fix_key) {
    return t(check.fix_key, (check.fix_params || {}) as Record<string, unknown>);
  }
  return (check.fix || '').trim();
}

// 25 categories split into 7 tabs (2 free + 5 paid) aligned with
// Free and paid category grouping. Free and paid
// groups do not cross over, so a whole paid tab can show 🔒 for non-members
// while free tabs are always visible.
// Labels MUST match the `--- X ---` section headers emitted by geo_checker.py —
// the backend parser sets `checks[].category` from those headers.
const categoryGroups: Record<string, string[]> = {
  // 🆓 基础协议与可抓取性
  infraProtocols: [
    'HTTPS',
    'robots.txt',
    'sitemap.xml',
  ],
  // 🆓 页面基础与移动体验
  pageBasics: [
    'Meta Tags',
    'Mobile-Friendliness & Page Weight',
  ],
  // 💎 AI 专属协议与抓取
  aiProtocols: [
    'llms.txt',
    '.well-known Discovery',
    'AI Crawl Readiness',
  ],
  // 💎 结构化与语义
  structuredSemantic: [
    'Structured Data',
    'Schema Breadcrumbs & Knowledge Panel',
    'URL Normalization',
  ],
  // 💎 内容质量与可读性
  contentQuality: [
    'Content Accessibility',
    'Content Quality for AI',
    'AI-Specific Optimization',
    'AI Answer Format Optimization',
  ],
  // 💎 技术健壮性与媒体
  techRobustness: [
    'Technical Crawlability',
    'Outbound Links & Media',
    'Multilingual Content Depth',
    'Multi-Page Sampling',
  ],
  // 💎 权威与外部信号
  authorityExternal: [
    'Search Engine & AI Platform Registration',
    'Authority & Trust Signals',
    'Brand Entity in Knowledge Graphs',
    'Trust & Safety Signals',
    'Social Signals',
    'Cross-Platform Content Distribution',
  ],
};

// Tabs in FREE_GROUPS render for everyone; all others are paid and show 🔒
// on the tab for non-members (i.e. when any of their categories are in the
// backend-provided `locked_categories` set).
const FREE_GROUPS = new Set(['infraProtocols', 'pageBasics']);

const TIER_RANK: Record<string, number> = {
  free: 0,
  pro: 1,
  starter: 2,
  growth: 3,
  scale: 4,
};

const STATUS_ORDER: Record<string, number> = { FAIL: 0, WARN: 1, INFO: 2, PASS: 3 };

const statusTheme = (status: string) => {
  switch (status) {
    case 'PASS':
      return {
        dot: 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.6)]',
        text: 'text-emerald-500',
        badge: 'bg-emerald-500/10 text-emerald-600 border-emerald-500/40',
        bar: 'from-emerald-400 to-emerald-500',
      };
    case 'WARN':
      return {
        dot: 'bg-amber-500 shadow-[0_0_8px_rgba(245,158,11,0.6)]',
        text: 'text-amber-500',
        badge: 'bg-amber-500/10 text-amber-600 border-amber-500/40',
        bar: 'from-amber-400 to-amber-500',
      };
    case 'FAIL':
      return {
        dot: 'bg-rose-500 shadow-[0_0_8px_rgba(244,63,94,0.6)]',
        text: 'text-rose-500',
        badge: 'bg-rose-500/10 text-rose-600 border-rose-500/40',
        bar: 'from-rose-500 to-pink-500',
      };
    default:
      return {
        dot: 'bg-cyan-500 shadow-[0_0_8px_rgba(6,182,212,0.6)]',
        text: 'text-cyan-500',
        badge: 'bg-cyan-500/10 text-cyan-600 border-cyan-500/40',
        bar: 'from-cyan-400 to-cyan-500',
      };
  }
};

export function Result() {
  useLoadNs('result');
  const { t, i18n } = useTranslation();
  const [exportingPdf, setExportingPdf] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const { openAuthModal } = useAuthModal();
  const navState = location.state as
    | {
        result?: GeoTestResult;
        initialMode?: AdvancedMode;
        initialUrl?: string;
        // URL handed off from Home — Result kicks the default check on mount,
        // replacing state with { result } once it resolves. Lives here (not in
        // Home) so a user hitting back/refresh during the 30s+ detection just
        // cancels the request via AbortController instead of orphaning it.
        pendingUrl?: string;
      }
    | null;
  const result = navState?.result as GeoTestResult | undefined;
  const pendingUrl = navState?.pendingUrl;
  // "Empty advanced" entry — user clicked an advanced capability on the
  // homepage with no prior default check. We skip the score hero and
  // category tabs, and render a centered hero form pre-set to that mode.
  const initialAdvancedMode = navState?.initialMode;
  const initialAdvancedUrl = navState?.initialUrl || '';
  const isEmptyAdvancedMode = !result && !!initialAdvancedMode;
  const { token, isLoggedIn, refresh } = useMembership();
  const { openTierModal } = useTierModal();
  const [showPaymentModal, setShowPaymentModal] = useState(false);
  const [activeTab, setActiveTab] = useState<string>('infraProtocols');
  const [showContactModal, setShowContactModal] = useState(false);
  const [form, setForm] = useState({ name: '', email: '', website: '', service: '', message: '' });
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [feedbackKind, setFeedbackKind] = useState<'success' | 'error' | null>(null);

  // Rerun bar state — title-row URL input + optional advanced mode dropdown.
  // pendingUrl fallback keeps the input populated while the kickoff check
  // runs, so the user sees the URL they just submitted.
  const [rerunUrl, setRerunUrl] = useState<string>(result?.url || pendingUrl || initialAdvancedUrl);
  const [rerunMode, setRerunMode] = useState<RerunMode>(initialAdvancedMode || 'default');
  const [rerunKeywords, setRerunKeywords] = useState<string>('');
  const [rerunEntityName, setRerunEntityName] = useState<string>('');
  const [rerunEntityType, setRerunEntityType] = useState<'brand' | 'product' | 'person'>('brand');
  // Start true when Home handed off a pendingUrl so the first paint renders
  // <CheckProgress /> instead of the "no data" error card. Without this
  // initial value, React's first render (before useEffect runs) would briefly
  // show the error state.
  const [rerunLoading, setRerunLoading] = useState(!!pendingUrl && !result);
  const [rerunError, setRerunError] = useState<string>('');
  const [rerunQuotaExceeded, setRerunQuotaExceeded] = useState(false);
  const [downloadingFixPackage, setDownloadingFixPackage] = useState(false);

  // Inline advanced-mode result — when user reruns in a non-default mode,
  // render the result here instead of navigating to /advanced/{mode}.
  const [advancedResult, setAdvancedResult] = useState<
    { mode: AdvancedMode; data: AnyAdvancedResult } | null
  >(null);
  const rerunAbortRef = useRef<AbortController | null>(null);
  const advancedResultRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (advancedResult && advancedResultRef.current) {
      advancedResultRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }, [advancedResult]);

  // Guard against direct access to /result with no context (no result, no
  // pending detection, not empty-advanced). Redirect to Home to avoid
  // rendering an empty shell. Skip redirect while a rerun is in progress
  // to avoid cancelling the in-flight request.
  useEffect(() => {
    if (rerunLoading) return;
    if (!navState?.result && !navState?.pendingUrl && !navState?.initialMode && !advancedResult) {
      navigate('/', { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rerunLoading]);

  // Abort any in-flight rerun request on unmount.
  useEffect(() => {
    return () => { rerunAbortRef.current?.abort(); };
  }, []);

  // Home hands off a URL via `pendingUrl`; this effect owns the actual HTTP
  // call. Using AbortController means a user bouncing back to Home or hitting
  // F5 mid-detection cancels the request instead of leaving the backend
  // running for 2+ minutes. Reuses rerun* state so the existing CheckProgress
  // + error-band render path works without changes.
  useEffect(() => {
    if (!pendingUrl || result) return;
    const controller = new AbortController();
    setRerunLoading(true);
    setRerunError('');
    setRerunQuotaExceeded(false);
    setRerunMode('default');

    geoApi
      .checkGeo({ url: pendingUrl }, controller.signal)
      .then((fresh) => {
        // Replace state so a refresh / forward-nav doesn't re-trigger the
        // check, and so the rerun bar picks up the fresh result URL.
        setRerunLoading(false);
        navigate('.', { state: { result: fresh }, replace: true });
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        setRerunLoading(false);
        if (err instanceof ApiError && err.status === 429) {
          setRerunQuotaExceeded(true);
          setRerunError(err.message || (t('home.error.quotaExceeded') as string));
        } else {
          setRerunError(err instanceof Error ? err.message : (t('home.error.failed') as string));
        }
      });

    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const effectiveTier = result?.tier || 'free';
  const effectiveRank = TIER_RANK[effectiveTier] ?? 0;
  // Fix recommendations are a starter+ perk. Rank 2 = starter; growth/scale
  // are higher. Backend also force-filters fix text for lower tiers, so this
  // flag is purely a UI hint — data won't be present for non-eligible tiers.
  const canShowFix = effectiveRank >= TIER_RANK.starter;
  const isModeLocked = (mode: AdvancedMode): boolean => {
    const entry = ADVANCED_MODES.find((m) => m.key === mode);
    if (!entry) return true;
    // Empty-advanced entry: the user is here because Home already verified
    // they're an unlocked member. Skip the result-derived tier check; the
    // backend is the real gate.
    if (isEmptyAdvancedMode) return false;
    return effectiveRank < TIER_RANK[entry.minTier];
  };

  // The backend tells us which categories were locked for this check run.
  // Deriving from the response (rather than from the membership hook) means
  // anonymous free users and logged-in free users behave identically, and a
  // tier change on the server is reflected without a client reload.
  const lockedCategorySet = useMemo(
    () => new Set(result?.locked_categories ?? []),
    [result],
  );
  const isUnlocked = lockedCategorySet.size === 0;

  const handleUnlockClick = () => {
    if (!isLoggedIn) {
      openAuthModal('login');
      return;
    }
    setShowPaymentModal(true);
  };

  const handleContactClick = () => {
    setShowContactModal(true);
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
      // 这里可以添加表单提交逻辑
      // 暂时模拟成功
      setFeedback('Your message has been sent successfully! We will contact you soon.');
      setFeedbackKind('success');
      setForm({ name: '', email: '', website: '', service: '', message: '' });
    } catch (err) {
      setFeedback('Failed to send message. Please try again later.');
      setFeedbackKind('error');
    } finally {
      setSubmitting(false);
    }
  };

  const handlePaymentSuccess = () => {
    setShowPaymentModal(false);
    refresh();
  };

  const checksByCategory = useMemo(() => {
    if (!result?.checks) return {} as Record<string, CheckResult[]>;
    const map: Record<string, CheckResult[]> = {};
    for (const check of result.checks) {
      (map[check.category] ||= []).push(check);
    }
    for (const key of Object.keys(map)) {
      map[key].sort((a, b) => (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9));
    }
    return map;
  }, [result]);

  const groupKeys = useMemo(() => Object.keys(categoryGroups), []);

  const knownCategories = useMemo(() => new Set(groupKeys.flatMap((g) => categoryGroups[g])), [groupKeys]);

  const otherCategories = useMemo(
    () => Object.keys(checksByCategory).filter((c) => !knownCategories.has(c)),
    [checksByCategory, knownCategories],
  );

  const allTabs = useMemo(() => {
    const tabs = [...groupKeys];
    if (otherCategories.length > 0) tabs.push('other');
    return tabs;
  }, [groupKeys, otherCategories]);

  const categoriesForTab = (tab: string): string[] =>
    tab === 'other' ? otherCategories : categoryGroups[tab] || [];

  const groupStats = useMemo(() => {
    return allTabs.map((tab) => {
      const cats = categoriesForTab(tab);
      const checks = cats.flatMap((c) => checksByCategory[c] || []);
      const total = checks.length;
      const nameOf = (c: CheckResult) => renderCheckMessage(c, t);
      const namesByStatus = (status: string) =>
        checks.filter((c) => c.status === status).map(nameOf);
      const passedNames = namesByStatus('PASS');
      const failedNames = namesByStatus('FAIL');
      const warnedNames = namesByStatus('WARN');
      const infoNames = namesByStatus('INFO');
      const allNames = checks.map(nameOf);
      const passed = passedNames.length;
      const failed = failedNames.length;
      const warned = warnedNames.length;
      const info = infoNames.length;
      const passRate = total === 0 ? 0 : Math.round((passed / total) * 100);
      const lockedInTab = cats.filter((c) => lockedCategorySet.has(c)).length;
      // Paid tab is "locked" if not in FREE_GROUPS and any category is
      // in the backend-provided locked set. Free tabs are never locked.
      const isPaid = !FREE_GROUPS.has(tab) && tab !== 'other';
      const isTabLocked = isPaid && lockedInTab > 0;
      return {
        tab,
        total,
        passed,
        failed,
        warned,
        info,
        passRate,
        lockedInTab,
        isPaid,
        isTabLocked,
        passedNames,
        failedNames,
        warnedNames,
        infoNames,
        allNames,
      };
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allTabs, checksByCategory, lockedCategorySet, i18n.language]);

  // Explicit "verify after fix" path — always bypasses the 24h cache. Distinct
  // from the rerun bar's same-URL heuristic so users have a discoverable action
  // rather than relying on "type the same URL again". Reuses rerunLoading /
  // rerunError state because the visual loading + error rendering is identical
  // to a regular rerun.
  const handleForceRefresh = async () => {
    if (!result?.url || rerunLoading) return;
    setRerunError('');
    setRerunQuotaExceeded(false);
    setRerunLoading(true);
    const controller = new AbortController();
    rerunAbortRef.current = controller;
    try {
      const fresh = await geoApi.checkGeo(
        { url: result.url, force_refresh: true },
        controller.signal,
      );
      setAdvancedResult(null);
      navigate('/result', { state: { result: fresh }, replace: true });
    } catch (err) {
      if (controller.signal.aborted) return;
      if (err instanceof ApiError && err.status === 429) {
        setRerunQuotaExceeded(true);
        setRerunError(err.message || (t('home.error.quotaExceeded') as string));
      } else {
        setRerunError(err instanceof Error ? err.message : (t('home.error.failed') as string));
      }
    } finally {
      setRerunLoading(false);
    }
  };

  const handleRerunSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setRerunError('');
    setRerunQuotaExceeded(false);

    // Safety net — dropdown already disables locked modes, but double-check.
    if (rerunMode !== 'default' && isModeLocked(rerunMode)) {
      if (!isLoggedIn) {
        openAuthModal('login');
        return;
      }
      setShowPaymentModal(true);
      return;
    }

    // Per-mode validation
    if (rerunMode === 'entity') {
      if (!rerunEntityName.trim()) {
        setRerunError(t('home.error.empty'));
        return;
      }
    } else if (rerunMode === 'compare') {
      const parts = rerunUrl.split(/[,\s]+/).map((p) => p.trim()).filter(Boolean);
      if (parts.length < 2) {
        setRerunError(t('home.advanced.validation.minUrls'));
        return;
      }
      for (const p of parts) {
        if (!validateUrl(p)) {
          setRerunError(t('home.advanced.validation.invalidUrl', { url: p }));
          return;
        }
      }
    } else {
      const trimmed = rerunUrl.trim();
      if (!trimmed) {
        setRerunError(t('home.error.empty'));
        return;
      }
      if (!validateUrl(trimmed)) {
        setRerunError(t('home.error.invalid'));
        return;
      }
    }

    setRerunLoading(true);
    const controller = new AbortController();
    rerunAbortRef.current = controller;
    try {
      if (rerunMode === 'default') {
        const url = normalizeUrl(rerunUrl.trim());
        // Same-URL re-run = "verify after fix" intent → bypass 24h cache so the
        // user sees their fix reflected immediately. Different URL = casual
        // peer lookup, fine to use cache.
        const sameUrl = !!result?.url && normalizeUrl(result.url) === url;
        const fresh = await geoApi.checkGeo(
          { url, force_refresh: sameUrl },
          controller.signal,
        );
        setAdvancedResult(null);
        navigate('/result', { state: { result: fresh }, replace: true });
        return;
      }
      if (rerunMode === 'compare') {
        const urls = rerunUrl
          .split(/[,\s]+/)
          .map((p) => normalizeUrl(p.trim()))
          .filter(Boolean);
        const data = await geoApi.runAdvancedCheck('compare', { urls }, controller.signal);
        setAdvancedResult({ mode: 'compare', data });
        return;
      }
      if (rerunMode === 'visibility') {
        const url = normalizeUrl(rerunUrl.trim());
        const queries = rerunKeywords
          .split(/[,\n]/)
          .map((q) => q.trim())
          .filter(Boolean);
        const data = await geoApi.runAdvancedCheck('visibility', {
          url,
          custom_queries: queries.length ? queries : undefined,
        }, controller.signal);
        setAdvancedResult({ mode: 'visibility', data });
        return;
      }
      if (rerunMode === 'entity') {
        const data = await geoApi.runAdvancedCheck('entity', {
          entity_name: rerunEntityName.trim(),
          entity_type: rerunEntityType,
        }, controller.signal);
        setAdvancedResult({ mode: 'entity', data });
        return;
      }
      // crawlTest / authority / citation — single-URL advanced modes
      const url = normalizeUrl(rerunUrl.trim());
      const data = await geoApi.runAdvancedCheck(rerunMode, { url }, controller.signal);
      setAdvancedResult({ mode: rerunMode, data });
    } catch (err) {
      if (controller.signal.aborted) return;
      if (err instanceof ApiError && err.status === 429) {
        setRerunQuotaExceeded(true);
        setRerunError(err.message || t('home.error.quotaExceeded'));
      } else {
        setRerunError(err instanceof Error ? err.message : t('home.error.failed'));
      }
    } finally {
      setRerunLoading(false);
    }
  };

  // Renders the rerun bar in either compact (top-of-page) or hero (centered
  // empty-state) sizes. Captures all rerun state via closure so the two
  // call sites stay perfectly in sync.
  const renderRerunForm = ({ hero }: { hero: boolean }): ReactNode => {
    const formClass = hero
      ? 'w-full max-w-2xl mx-auto'
      : 'flex-1 min-w-0 lg:max-w-xl w-full';
    const capsuleClass = hero
      ? 'flex flex-col sm:flex-row sm:items-center bg-card border border-border rounded-2xl sm:rounded-full p-1.5 shadow-glow gap-1.5 sm:gap-0'
      : 'flex flex-col sm:flex-row sm:items-center bg-card border border-border rounded-2xl sm:rounded-full p-1.5 sm:p-1 shadow-glow gap-1.5 sm:gap-0';
    const inputClass = hero
      ? 'flex-1 min-w-0 py-3 px-5 text-base bg-transparent focus:outline-none text-primary placeholder-muted'
      : 'flex-1 min-w-0 py-2 px-3 text-xs sm:text-sm bg-transparent focus:outline-none text-primary placeholder-muted';
    const buttonClass = hero
      ? 'btn-solid px-5 py-3 rounded-xl sm:rounded-full flex items-center justify-center gap-2 font-semibold transition-all shrink-0 disabled:opacity-60 text-sm w-full sm:w-auto'
      : 'btn-solid px-4 py-2 rounded-xl sm:rounded-full flex items-center justify-center gap-1.5 font-semibold transition-all shrink-0 disabled:opacity-60 text-xs sm:text-sm w-full sm:w-auto';
    const iconSize = hero ? 'h-4 w-4' : 'h-3.5 w-3.5';
    const selectClass = hero
      ? 'appearance-none bg-transparent text-base text-primary pl-3 pr-2 py-3 focus:outline-none cursor-pointer shrink-0'
      : 'appearance-none bg-transparent text-xs sm:text-sm text-primary pl-3 pr-2 py-2 focus:outline-none cursor-pointer shrink-0';

    return (
      <form onSubmit={handleRerunSubmit} className={formClass}>
        <div className={capsuleClass}>
          <RerunModeDropdown
            mode={rerunMode}
            onSelect={setRerunMode}
            isModeLocked={isModeLocked}
          />
          {rerunMode === 'entity' ? (
            <>
              <input
                type="text"
                value={rerunEntityName}
                onChange={(e) => setRerunEntityName(e.target.value)}
                placeholder={t('result.header.placeholderEntity', { defaultValue: '品牌 / 产品 / 人物 名称' }) as string}
                className={inputClass}
                disabled={rerunLoading}
              />
              <div className="hidden sm:block w-px h-5 bg-border shrink-0" />
              <select
                value={rerunEntityType}
                onChange={(e) => setRerunEntityType(e.target.value as 'brand' | 'product' | 'person')}
                disabled={rerunLoading}
                title={t('result.header.entityTypeLabel', { defaultValue: '实体类型' }) as string}
                className={selectClass}
              >
                <option value="brand" className="bg-card">
                  {t('result.header.entityType.brand', { defaultValue: '品牌' }) as string}
                </option>
                <option value="product" className="bg-card">
                  {t('result.header.entityType.product', { defaultValue: '产品' }) as string}
                </option>
                <option value="person" className="bg-card">
                  {t('result.header.entityType.person', { defaultValue: '人物' }) as string}
                </option>
              </select>
            </>
          ) : rerunMode === 'visibility' ? (
            <>
              <input
                type="text"
                value={rerunUrl}
                onChange={(e) => setRerunUrl(e.target.value)}
                placeholder={t('result.header.rerunPlaceholder') as string}
                className={`flex-[2] ${inputClass.replace('flex-1 ', '')}`}
                disabled={rerunLoading}
              />
              <div className="hidden sm:block w-px h-5 bg-border shrink-0" />
              <input
                type="text"
                value={rerunKeywords}
                onChange={(e) => setRerunKeywords(e.target.value)}
                placeholder={t('result.header.placeholderKeywords', { defaultValue: '关键词（可选，逗号分隔）' }) as string}
                className={inputClass}
                disabled={rerunLoading}
              />
            </>
          ) : (
            <input
              type="text"
              value={rerunUrl}
              onChange={(e) => setRerunUrl(e.target.value)}
              placeholder={
                rerunMode === 'compare'
                  ? (t('result.header.placeholderCompare', { defaultValue: 'https://a.com, https://b.com' }) as string)
                  : (t('result.header.rerunPlaceholder') as string)
              }
              className={inputClass}
              disabled={rerunLoading}
            />
          )}
          <button
            type="submit"
            disabled={rerunLoading}
            title={t('result.header.rerun')}
            className={buttonClass}
          >
            {rerunLoading ? (
              <>
                <svg className={`animate-spin ${iconSize}`} xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth={4} />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                <span className="hidden sm:inline">{t('home.analyzing', { defaultValue: '检测中...' })}</span>
              </>
            ) : (
              t('result.startCheck')
            )}
          </button>
        </div>
        {(rerunMode === 'compare' || rerunMode === 'visibility' || rerunMode === 'entity') && (
          <p className={`mt-1.5 px-4 ${hero ? 'text-xs' : 'text-[11px]'} text-muted ${hero ? 'text-center' : ''}`}>
            {rerunMode === 'compare' &&
              (t('result.header.compareHint', {
                defaultValue: '用逗号或空格分隔 2-5 个网址',
              }) as string)}
            {rerunMode === 'visibility' &&
              (t('result.header.visibilityHint', {
                defaultValue: '关键词留空则自动生成；多个关键词用逗号分隔',
              }) as string)}
            {rerunMode === 'entity' &&
              (t('result.header.entityHint', {
                defaultValue: '输入要审计的品牌 / 产品 / 人物名称',
              }) as string)}
          </p>
        )}
        {rerunError && (
          <div className={`mt-2 px-3 flex flex-wrap items-center gap-2 ${hero ? 'justify-center' : ''}`}>
            <p className={`${hero ? 'text-xs' : 'text-[11px]'} text-rose-400 ${hero ? '' : 'flex-1 min-w-0'}`}>{rerunError}</p>
            {rerunQuotaExceeded && (
              <button
                type="button"
                onClick={openTierModal}
                className="text-[11px] font-semibold text-rose-200 bg-red-500/80 hover:bg-red-500 px-2.5 py-1 rounded-full transition-colors"
              >
                {t('home.error.quotaCta')}
              </button>
            )}
          </div>
        )}
      </form>
    );
  };

  const handleExportPDF = async () => {
    if (exportingPdf) return;
    setExportingPdf(true);
    try {
      if (advancedResult) {
        // Inline advanced result is the "current" report — export it
        // instead of the underlying default check.
        await exportAdvancedPdfReport({
          mode: advancedResult.mode,
          data: advancedResult.data,
          t,
          language: i18n.language || 'en',
        });
      } else if (result) {
        await exportPdfReport({
          result,
          t,
          language: i18n.language || 'en',
          groupStats,
          categoryGroups,
          checksByCategory,
          otherCategories,
        });
      }
    } catch (err) {
      console.error('PDF export failed', err);
      alert(t('result.error.noData'));
    } finally {
      setExportingPdf(false);
    }
  };

  const handleDownloadFixPackage = async () => {
    if (downloadingFixPackage || !result) return;
    setDownloadingFixPackage(true);
    try {
      await geoApi.downloadFixPackage(result.url);
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        openTierModal();
      } else {
        alert(err instanceof Error ? err.message : t('result.fixPackage.error'));
      }
    } finally {
      setDownloadingFixPackage(false);
    }
  };

  // ----- Early returns -----
  // No default check data yet. Either:
  //  (a) user landed here from a homepage advanced-card click → render the
  //      centered empty-advanced layout. The inline advanced result panel
  //      below the form takes over as soon as they hit Run.
  //  (b) something else — show the standard "no data" error.
  if (!result) {
    if (isEmptyAdvancedMode) {
      // Title tracks the live dropdown selection, not the entry mode — when
      // the user flips the rerun dropdown, the hero heading updates in sync.
      const modeTitle =
        rerunMode === 'default'
          ? (t('result.header.modeDefault', { defaultValue: '基础 GEO 检测' }) as string)
          : (t(`home.advanced.cards.${rerunMode}.title`) as string);
      const modeDesc =
        rerunMode === 'default'
          ? (t('home.description') as string)
          : (t(`home.advanced.cards.${rerunMode}.desc`) as string);
      return (
        <div className="min-h-screen grid-background">
          <div className="bg-glow bg-glow-1"></div>
          <div className="bg-glow bg-glow-2"></div>
          <div className="bg-glow bg-glow-3"></div>

          <main className="flex-1 px-4 py-16 sm:py-24 hero-gradient relative z-10">
            <div className="w-full max-w-3xl mx-auto animate-fade-in">
              <button
                type="button"
                onClick={() => navigate('/')}
                className="text-xs text-secondary hover:text-primary transition-colors inline-flex items-center gap-1 mb-8"
              >
                ← {t('result.buttons.checkAnother', { defaultValue: 'Back' })}
              </button>
            <div className="text-center">
              <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-surface border border-soft shadow-glow mb-6">
                <span className="w-1.5 h-1.5 rounded-full bg-cyan-500"></span>
                <span className="text-xs font-medium text-secondary">
                  {t('home.advanced.title', { defaultValue: 'Advanced Detection' })}
                </span>
              </div>
              <h1 className="text-3xl sm:text-4xl lg:text-5xl font-bold mb-5 leading-[1.15] tracking-tight">
                <span className="gradient-text">{modeTitle}</span>
              </h1>
              <p className="text-sm sm:text-base text-secondary max-w-xl mx-auto leading-relaxed mb-10">
                {modeDesc}
              </p>
              <div className="mt-2">{renderRerunForm({ hero: true })}</div>
            </div>
            </div>

            {advancedResult && (
              <div className="w-full max-w-5xl mx-auto mt-12">
                <section
                  ref={advancedResultRef}
                  className="bg-card border border-border rounded-2xl p-5 sm:p-6 animate-fade-in scroll-mt-24"
                >
                  <div className="flex items-center gap-2 mb-4 pb-3 border-b border-border">
                    <span className="w-1 h-4 rounded-full gradient-bg" />
                    <h2 className="text-base font-bold text-primary">
                      {t(`home.advanced.cards.${advancedResult.mode}.title`)}
                    </h2>
                    <button
                      type="button"
                      onClick={handleExportPDF}
                      disabled={exportingPdf}
                      title={t('result.shareExport.downloadReport') as string}
                      className="ml-auto h-8 px-3 rounded-lg bg-tertiary border border-border text-secondary hover:text-accent-primary hover:border-border-strong transition-colors flex items-center gap-1.5 text-xs font-semibold disabled:opacity-60"
                    >
                      <svg xmlns="http://www.w3.org/2000/svg" className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3M3 17V7a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V17a2 2 0 01-2 2H5a2 2 0 01-2-2z" />
                      </svg>
                      <span>{t('result.shareExport.downloadReport')}</span>
                    </button>
                    {canShowFix && (
                      <button
                        type="button"
                        onClick={handleDownloadFixPackage}
                        disabled={downloadingFixPackage}
                        title={t('result.fixPackage.title') as string}
                        className="h-8 px-3 rounded-lg bg-tertiary border border-border text-secondary hover:text-accent-primary hover:border-border-strong transition-colors flex items-center gap-1.5 text-xs font-semibold disabled:opacity-60"
                      >
                        {downloadingFixPackage ? (
                          <svg className="h-3.5 w-3.5 animate-spin" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth={4} />
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                          </svg>
                        ) : (
                          <svg xmlns="http://www.w3.org/2000/svg" className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                          </svg>
                        )}
                        <span>{downloadingFixPackage ? t('result.fixPackage.downloading') : t('result.fixPackage.download')}</span>
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => setAdvancedResult(null)}
                      title={t('common.close', { defaultValue: '关闭' }) as string}
                      className="text-secondary hover:text-primary transition-colors p-1 rounded-lg hover:bg-tertiary"
                      aria-label={t('common.close', { defaultValue: '关闭' }) as string}
                    >
                      <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  </div>
                  <AdvancedResultPanel mode={advancedResult.mode} result={advancedResult.data} />
                </section>
              </div>
            )}
          </main>
          {rerunLoading && <CheckProgress mode={rerunMode} />}
        </div>
      );
    }
    if (rerunLoading) {
      return <CheckProgress mode={rerunMode} />;
    }
    return (
      <div className="grid-background flex justify-center py-16 sm:py-20 px-4">
        <div className="bg-card border border-border rounded-2xl p-6 max-w-md w-full text-center">
          <div className="w-14 h-14 mx-auto rounded-full bg-rose-500/10 flex items-center justify-center mb-4">
            <svg xmlns="http://www.w3.org/2000/svg" className="h-7 w-7 text-rose-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-.633-1.964-.633-2.732 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
          </div>
          <h2 className="text-xl font-bold mb-3">{t('common.error')}</h2>
          <p className="text-secondary mb-5">
            {rerunError || (t('result.error.noData') as string)}
          </p>
          {rerunQuotaExceeded ? (
            <button
              onClick={openTierModal}
              className="w-full btn-solid rounded-xl py-3.5 font-semibold transition-all duration-300 flex items-center justify-center gap-2 shadow-glow"
            >
              {t('home.error.quotaCta')}
            </button>
          ) : (
            <button
              onClick={() => navigate('/')}
              className="w-full btn-solid rounded-xl py-3.5 font-semibold transition-all duration-300 flex items-center justify-center gap-2 shadow-glow"
            >
              {t('result.buttons.checkAnother')}
            </button>
          )}
        </div>
      </div>
    );
  }

  const score = result.score || 0;
  const grade = result.grade || 'F';

  const tabLabel = (tab: string) => t(`result.categories.${tab}`);

  const activeCategories = categoriesForTab(activeTab);

  return (
    <div className="min-h-screen grid-background">
      <div className="bg-glow bg-glow-1"></div>
      <div className="bg-glow bg-glow-2"></div>
      <div className="bg-glow bg-glow-3"></div>

      <main className="flex-1 px-4 py-5 hero-gradient relative z-10">
        <div className="w-full max-w-6xl mx-auto animate-fade-in">
          {/* Top bar: rerun input (left) + export button (right) */}
          <div className="flex flex-col gap-3 mb-5 sm:flex-row sm:items-center sm:justify-between">
            {advancedResult ? (
              <div className="min-w-0 sm:shrink-0 sm:max-w-sm">
                {renderAdvancedHero(advancedResult, t)}
              </div>
            ) : null}
            {renderRerunForm({ hero: false })}
            <div className="flex items-center gap-2 shrink-0">
              <button
                onClick={handleExportPDF}
                disabled={exportingPdf}
                title={exportingPdf ? t('result.shareExport.downloadReportLoading') : t('result.shareExport.downloadReport')}
                className="h-9 px-3 rounded-lg bg-card border border-border text-secondary hover:text-accent-primary hover:border-border-strong transition-colors flex items-center gap-2 text-xs font-semibold disabled:opacity-60 disabled:cursor-wait"
              >
                {exportingPdf ? (
                  <svg className="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth={4} />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                ) : (
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3M3 17V7a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V17a2 2 0 01-2 2H5a2 2 0 01-2-2z" />
                  </svg>
                )}
                <span className="hidden sm:inline">
                  {exportingPdf ? t('result.shareExport.downloadReportLoading') : t('result.shareExport.downloadReport')}
                </span>
              </button>
              {canShowFix && (
                <button
                  onClick={handleDownloadFixPackage}
                  disabled={downloadingFixPackage}
                  title={t('result.fixPackage.title') as string}
                  className="h-9 px-3 rounded-lg bg-card border border-border text-secondary hover:text-accent-primary hover:border-border-strong transition-colors flex items-center gap-2 text-xs font-semibold disabled:opacity-60 disabled:cursor-wait"
                >
                  {downloadingFixPackage ? (
                    <svg className="h-4 w-4 animate-spin" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth={4} />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                  ) : (
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                    </svg>
                  )}
                  <span className="hidden sm:inline">
                    {downloadingFixPackage ? t('result.fixPackage.downloading') : t('result.fixPackage.download')}
                  </span>
                </button>
              )}
            </div>
          </div>

          {/* ── Report Summary Card (like PDF first page) ── */}
          {!advancedResult && (
            <section className="bg-card border border-border rounded-2xl p-5 sm:p-6 mb-5 relative overflow-hidden">
              <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-accent-primary/30 to-transparent" />

              {/* Cover info row */}
              <div className="flex items-center gap-2 mb-4 pb-3 border-b border-border">
                <span className="text-[10px] font-bold tracking-[0.2em] uppercase" style={{ color: 'var(--accent-primary, #06b6d4)' }}>
                  {t('result.pdfReport.coverBadge')}
                </span>
              </div>

              {/* Score + Stats */}
              <div className="flex flex-col lg:flex-row gap-5 lg:gap-6 items-stretch">
                {/* Left: Score ring + grade + interpretation */}
                <div className="flex items-center gap-5 lg:gap-6 lg:w-[280px] shrink-0">
                  <div className="relative">
                    <svg width="100" height="100" viewBox="0 0 100 100" className="transform -rotate-90 shrink-0">
                      <defs>
                        <linearGradient id="hero-ring-grad" x1="0%" y1="0%" x2="100%" y2="0%">
                          <stop offset="0%" stopColor="var(--accent-primary, #06b6d4)" />
                          <stop offset="100%" stopColor="var(--accent-secondary, #3b82f6)" />
                        </linearGradient>
                      </defs>
                      <circle cx="50" cy="50" r="42" fill="none" stroke="var(--bg-tertiary, rgba(148,163,184,0.12))" strokeWidth="6" />
                      <circle
                        cx="50" cy="50" r="42"
                        fill="none"
                        stroke="url(#hero-ring-grad)"
                        strokeWidth="6"
                        strokeLinecap="round"
                        strokeDasharray={`${2 * Math.PI * 42}`}
                        strokeDashoffset={`${2 * Math.PI * 42 * (1 - Math.max(0, Math.min(100, score)) / 100)}`}
                        className="transition-all duration-700"
                      />
                      <text
                        x="50" y="50"
                        textAnchor="middle"
                        dominantBaseline="central"
                        className="transform rotate-90 origin-center"
                        fill="var(--text-primary, #e2e8f0)"
                        fontSize="26"
                        fontWeight="800"
                      >
                        {score}
                      </text>
                    </svg>
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <span className="text-[10px] uppercase tracking-[0.2em] text-muted font-semibold">
                      {t('result.pdfReport.overallScore')}
                    </span>
                    <span className="text-xs text-muted font-mono">/ 100</span>
                    <span className="text-sm font-bold px-2.5 py-1 rounded-lg bg-tertiary text-primary border border-border leading-none w-fit">
                      {grade}
                    </span>
                    <p className="text-[11px] text-secondary leading-relaxed mt-1 max-w-[180px]">
                      {score >= 90
                        ? t('result.pdfReport.scoreLevels.excellent')
                        : score >= 75
                          ? t('result.pdfReport.scoreLevels.good')
                          : score >= 60
                            ? t('result.pdfReport.scoreLevels.average')
                            : score >= 40
                              ? t('result.pdfReport.scoreLevels.poor')
                              : t('result.pdfReport.scoreLevels.critical')}
                    </p>
                  </div>
                </div>

                {/* Right: stat tiles + meta info */}
                <div className="flex-1 min-w-0 flex flex-col gap-4">
                  {/* 4 stat tiles */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    <div className="rounded-xl bg-emerald-500/10 border border-emerald-500/20 p-3 text-center">
                      <div className="text-2xl font-extrabold text-emerald-500">{result.summary.pass_count}</div>
                      <div className="text-[10px] font-semibold text-emerald-600 mt-1">{t('result.summary.passed')}</div>
                    </div>
                    <div className="rounded-xl bg-amber-500/10 border border-amber-500/20 p-3 text-center">
                      <div className="text-2xl font-extrabold text-amber-500">{result.summary.warn_count}</div>
                      <div className="text-[10px] font-semibold text-amber-600 mt-1">{t('result.summary.warnings')}</div>
                    </div>
                    <div className="rounded-xl bg-rose-500/10 border border-rose-500/20 p-3 text-center">
                      <div className="text-2xl font-extrabold text-rose-500">{result.summary.fail_count}</div>
                      <div className="text-[10px] font-semibold text-rose-600 mt-1">{t('result.summary.failed')}</div>
                    </div>
                    <div className="rounded-xl bg-cyan-500/10 border border-cyan-500/20 p-3 text-center">
                      <div className="text-2xl font-extrabold text-cyan-500">{result.summary.info_count}</div>
                      <div className="text-[10px] font-semibold text-cyan-600 mt-1">{t('result.summary.info')}</div>
                    </div>
                  </div>
                  {/* Meta info row */}
                  <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 text-[11px] text-muted">
                    <span>
                      <span className="text-secondary font-medium">{t('result.pdfReport.targetSite')}:</span>{' '}
                      <a href={result.url} target="_blank" rel="noopener noreferrer" className="text-accent-primary hover:text-primary transition-colors font-medium">
                        {result.url}
                      </a>
                    </span>
                    <span>
                      <span className="text-secondary font-medium">{t('result.pdfReport.generatedAt')}:</span>{' '}
                      {new Date().toLocaleString(i18n.language?.startsWith('zh') ? 'zh-CN' : 'en-US')}
                    </span>
                    {result.tier && (
                      <span>
                        <span className="text-secondary font-medium">{t('result.pdfReport.tier')}:</span>{' '}
                        {t(`result.pdfReport.tierLabels.${(result.tier || 'free').toLowerCase()}`, { defaultValue: (result.tier || 'free').toUpperCase() })}
                      </span>
                    )}
                    <button
                      type="button"
                      onClick={handleForceRefresh}
                      disabled={rerunLoading}
                      title={t('result.recheck.tooltip') as string}
                      className="ml-auto inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-accent-primary/10 hover:bg-accent-primary/20 disabled:opacity-50 disabled:cursor-not-allowed border border-accent-primary/30 text-accent-primary text-[11px] font-semibold transition-colors"
                    >
                      <span aria-hidden>↻</span>
                      {rerunLoading ? t('result.recheck.loading') : t('result.recheck.button')}
                    </button>
                  </div>
                </div>
              </div>
            </section>
          )}

          {advancedResult && (
            <section
              ref={advancedResultRef}
              className="mt-4 mb-6 bg-card border border-border rounded-2xl p-5 sm:p-6 animate-fade-in scroll-mt-24"
            >
              <div className="flex items-center gap-2 mb-4 pb-3 border-b border-border">
                <span className="w-1 h-4 rounded-full gradient-bg" />
                <h2 className="text-base font-bold text-primary">
                  {t(`home.advanced.cards.${advancedResult.mode}.title`)}
                </h2>
                <button
                  type="button"
                  onClick={() => setAdvancedResult(null)}
                  title={t('common.close', { defaultValue: '关闭' }) as string}
                  className="ml-auto text-secondary hover:text-primary transition-colors p-1 rounded-lg hover:bg-tertiary"
                  aria-label={t('common.close', { defaultValue: '关闭' }) as string}
                >
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
              <AdvancedResultPanel mode={advancedResult.mode} result={advancedResult.data} />
            </section>
          )}

          {!advancedResult && (<>
            {/* ── Overview grid ── */}
            {(() => {
              const totalPassed = groupStats.reduce((s, g) => s + g.passed, 0);
              const totalChecks = groupStats.reduce((s, g) => s + g.total, 0);
              const totalRate = totalChecks === 0 ? 0 : Math.round((totalPassed / totalChecks) * 100);
              return (
                <section className="bg-card border border-border rounded-2xl p-4 sm:p-5 mb-5 relative overflow-hidden">
                  <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-accent-primary/30 to-transparent" />
                  <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-2">
                      <span className="w-1 h-5 gradient-bg rounded-full shrink-0" />
                      <h2 className="text-sm sm:text-base font-bold text-primary">
                        {t('result.summary.overview')}
                      </h2>
                    </div>
                    <span className="text-[11px] font-mono text-muted tabular-nums">
                      {totalPassed}/{totalChecks} · {totalRate}%
                    </span>
                  </div>
                  <div className="space-y-2.5">
                    {groupStats.map((g) => {
                      if (g.isTabLocked) {
                        return (
                          <button
                            key={g.tab}
                            type="button"
                            onClick={() => setActiveTab(g.tab)}
                            className="w-full flex items-center gap-3 rounded-xl border border-border bg-tertiary/40 px-4 py-3 opacity-60 cursor-pointer hover:opacity-80 transition-all"
                          >
                            <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 text-muted shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                            </svg>
                            <span className="text-xs font-semibold text-muted truncate">
                              {tabLabel(g.tab)}
                            </span>
                          </button>
                        );
                      }
                      const barColor = g.passRate >= 80
                        ? 'from-emerald-400 to-emerald-500'
                        : g.passRate >= 50
                          ? 'from-amber-400 to-amber-500'
                          : 'from-rose-400 to-rose-500';
                      const pctColor = g.passRate >= 80
                        ? 'text-emerald-500'
                        : g.passRate >= 50
                          ? 'text-amber-500'
                          : 'text-rose-500';
                      return (
                        <button
                          key={g.tab}
                          type="button"
                          onClick={() => setActiveTab(g.tab)}
                          className={`w-full rounded-xl border px-4 py-3 cursor-pointer transition-all text-left ${
                            activeTab === g.tab
                              ? 'border-accent-primary bg-accent-primary/5 shadow-sm'
                              : 'border-border bg-card hover:border-border-strong hover:bg-tertiary/40'
                          }`}
                        >
                          <div className="flex items-center justify-between mb-2">
                            <span className="text-xs font-semibold text-primary truncate">
                              {tabLabel(g.tab)}
                            </span>
                            <div className="flex items-center gap-2.5 shrink-0 ml-3">
                              <span className="text-[10px] font-mono text-muted">
                                {g.passed}/{g.total}
                              </span>
                              {g.failed === 0 && g.warned === 0 ? (
                                <span className="text-[10px] text-emerald-500 font-semibold">{t('result.summary.allPassed')}</span>
                              ) : (
                                <span className="flex items-center gap-1.5 text-[10px] text-muted">
                                  {g.warned > 0 && <span className="text-amber-500">&#9888;{g.warned}</span>}
                                  {g.failed > 0 && <span className="text-rose-500">&#10007;{g.failed}</span>}
                                </span>
                              )}
                              <span className={`text-[11px] font-bold tabular-nums ${pctColor}`}>
                                {g.passRate}%
                              </span>
                            </div>
                          </div>
                          <div className="h-1.5 rounded-full bg-tertiary overflow-hidden">
                            <div
                              className={`h-full rounded-full bg-gradient-to-r ${barColor} transition-all duration-700`}
                              style={{ width: `${g.passRate}%` }}
                            />
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </section>
              );
            })()}

            {/* Tab navigation — card-style tabs. Inactive tabs carry their own
              border-b; the active tab drops its bottom border so it visually
              merges with the content panel below. Doing the bottom line
              per-tab (instead of a container border-b + cover hack) renders
              identically across Chrome / Safari / Firefox. */}
            <div
              role="tablist"
              className="flex items-end gap-1.5 mt-2 overflow-x-auto pb-px scrollbar-hide"
            >
              {groupStats.map((g) => {
                const isActive = activeTab === g.tab;
                const tabButton = (
                  <button
                    key={g.tab}
                    role="tab"
                    aria-selected={isActive}
                    onClick={() => setActiveTab(g.tab)}
                    className={`relative px-4 py-2.5 rounded-t-xl border text-left transition-all shrink-0 ${isActive
                      ? 'border-border border-b-transparent bg-card shadow-sm z-10'
                      : 'border-transparent border-b border-b-border bg-transparent hover:bg-tertiary'
                      }`}
                  >
                    {isActive && (
                      <span className="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-transparent via-accent-primary to-transparent opacity-70"></span>
                    )}
                    <div className="flex items-center gap-2 min-w-0">
                      {g.isTabLocked && (
                        <svg
                          xmlns="http://www.w3.org/2000/svg"
                          className="h-3 w-3 text-accent-primary shrink-0"
                          fill="none"
                          viewBox="0 0 24 24"
                          stroke="currentColor"
                        >
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                        </svg>
                      )}
                      <span
                        className={`text-xs font-semibold truncate ${isActive
                          ? 'text-primary'
                          : g.isTabLocked
                            ? 'text-muted'
                            : 'text-secondary hover:text-primary'
                          }`}
                      >
                        {tabLabel(g.tab)}
                      </span>
                      {g.total > 0 && (
                        <span
                          className={`text-[10px] font-mono px-1.5 py-0.5 rounded shrink-0 ${isActive
                            ? 'bg-tertiary text-primary border border-border'
                            : 'bg-tertiary text-muted'
                            }`}
                        >
                          {g.total}
                        </span>
                      )}
                    </div>
                  </button>
                );
                return (
                  <Tooltip
                    key={g.tab}
                    disabled={!g.isTabLocked}
                    content={
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); openTierModal(); }}
                        className="cursor-pointer hover:underline"
                      >
                        {t('result.paywall.unlockCategory')}
                      </button>
                    }
                  >
                    {tabButton}
                  </Tooltip>
                );
              })}
            </div>

            {/* Per-tab header card — scoped stats, pass-rate bar, optional unlock CTA. */}
            {(() => {
              const stat = groupStats.find((g) => g.tab === activeTab);
              if (!stat) return null;
              // Locked (member) tabs: the entire body is replaced with a frosted
              // glass overlay. The user cannot preview any data — they must upgrade.
              if (stat.isTabLocked) {
                const lockedCategories = categoriesForTab(activeTab);
                return (
                  <div className="relative mt-5 mb-5 rounded-b-2xl rounded-tr-2xl border border-border border-t-0 bg-card overflow-hidden">
                    {/* Blurred preview of the actual category list in this tab,
                      so non-members can see *what* they would get rather than
                      generic skeleton bars. */}
                    <div className="p-6 sm:p-8 blur-[6px] select-none pointer-events-none space-y-4">
                      {lockedCategories.map((cat) => (
                        <div key={cat}>
                          <div className="flex items-center gap-2 mb-2">
                            <span className="w-1 h-4 gradient-bg rounded-full"></span>
                            <h3 className="text-sm font-semibold text-primary">
                              {t(`result.categoryLabels.${cat}`, { defaultValue: cat })}
                            </h3>
                          </div>
                          <div className="bg-card border border-border rounded-xl divide-y divide-border">
                            {Array.from({ length: 3 }).map((_, i) => (
                              <div key={i} className="flex items-center gap-3 px-4 py-2.5">
                                <span className="w-1.5 h-1.5 rounded-full bg-muted"></span>
                                <span className="w-12 h-3 rounded bg-tertiary"></span>
                                <span className="flex-1 h-2.5 rounded bg-tertiary"></span>
                              </div>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                    {/* Frosted glass overlay sits above the blurred content,
                      letting users still perceive the category list underneath. */}
                    <div className="absolute inset-0 flex items-center justify-center backdrop-blur-[2px]">
                      <div className="flex flex-col items-center gap-4 px-6 py-8 max-w-sm text-center rounded-2xl bg-card border border-border shadow-glow">
                        <div className="w-14 h-14 rounded-full gradient-bg flex items-center justify-center">
                          <svg xmlns="http://www.w3.org/2000/svg" className="h-6 w-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                          </svg>
                        </div>
                        <div className="space-y-1">
                          <p className="text-sm font-semibold text-primary">
                            {t('result.paywall.memberOnly')}
                          </p>
                          <p className="text-xs text-secondary">
                            {t('result.paywall.subtitle')}
                          </p>
                        </div>
                        <button
                          onClick={openTierModal}
                          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-full gradient-bg text-white text-xs font-semibold hover:opacity-90 transition-all"
                        >
                          <svg xmlns="http://www.w3.org/2000/svg" className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" />
                          </svg>
                          {t('result.paywall.upgradePro')}
                        </button>
                      </div>
                    </div>
                  </div>
                );
              }
              return (
                <div className="bg-card border border-border rounded-2xl p-4 sm:p-5 mt-5 mb-5 relative overflow-hidden">
                  <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-accent-primary/30 to-transparent"></div>
                  <div className="flex items-center justify-between gap-3 mb-3">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="w-1 h-5 gradient-bg rounded-full shrink-0"></span>
                      <h2 className="text-sm sm:text-base font-bold text-primary truncate">
                        {tabLabel(activeTab)}
                      </h2>
                      {stat.isTabLocked && (
                        <span className="inline-flex items-center gap-1 text-[10px] font-mono px-1.5 py-0.5 rounded bg-tertiary text-accent-primary border border-border shrink-0">
                          <svg xmlns="http://www.w3.org/2000/svg" className="h-2.5 w-2.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                          </svg>
                          {t('result.paywall.locked', { defaultValue: 'Locked' })}
                        </span>
                      )}
                    </div>
                    <span className="text-[11px] font-mono text-muted tabular-nums shrink-0">
                      {stat.passed}/{stat.total} · {stat.passRate}%
                    </span>
                  </div>
                  {/* Pass-rate bar */}
                  <div className="h-1.5 rounded-full bg-tertiary overflow-hidden mb-4">
                    <div
                      className="h-full gradient-bg transition-all duration-700"
                      style={{ width: `${stat.passRate}%` }}
                    ></div>
                  </div>
                  {/* Group-scoped stat pills */}
                  <div className="grid grid-cols-3 sm:grid-cols-5 gap-2">
                    <StatPill color="emerald" value={stat.passed} label={t('result.summary.passed')} items={stat.passedNames} />
                    <StatPill color="amber" value={stat.warned} label={t('result.summary.warnings')} items={stat.warnedNames} />
                    <StatPill color="rose" value={stat.failed} label={t('result.summary.failed')} items={stat.failedNames} />
                    <StatPill color="cyan" value={stat.info} label={t('result.summary.info')} items={stat.infoNames} />
                    <StatPill color="muted" value={stat.total} label={t('result.summary.totalChecks')} items={stat.allNames} />
                  </div>
                  {stat.isTabLocked && (
                    <button
                      onClick={handleUnlockClick}
                      className="mt-4 w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl border border-dashed border-border bg-tertiary hover:bg-surface-hover transition-colors"
                    >
                      <svg xmlns="http://www.w3.org/2000/svg" className="h-3.5 w-3.5 text-accent-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                      </svg>
                      <span className="text-xs font-semibold text-accent-primary">
                        {t('result.paywall.unlockCategory', { defaultValue: '升级检测会员解锁本项检测 →' })}
                      </span>
                    </button>
                  )}
                </div>
              );
            })()}

            {/* Detailed table — skipped for locked tabs (the frosted overlay above
              already covers the full body for member-only tabs). */}
            <div className="space-y-5 mb-8">
              {(() => {
                const activeStat = groupStats.find((g) => g.tab === activeTab);
                if (activeStat?.isTabLocked) return null;
                const renderRow = (check: CheckResult, rowKey: string) => {
                  const theme = statusTheme(check.status);
                  const fixText = renderCheckFix(check, t);
                  const showFix = canShowFix && !!fixText && check.status !== 'PASS';
                  const displayMessage = renderCheckMessage(check, t);
                  return (
                    <div
                      key={rowKey}
                      className="px-4 py-3 hover:bg-tertiary/60 transition-colors"
                    >
                      <div className="flex items-start gap-3">
                        <span className={`mt-[7px] w-1.5 h-1.5 rounded-full shrink-0 ${theme.dot}`}></span>
                        <span className={`mt-0.5 px-1.5 py-0.5 rounded text-[9px] font-bold border shrink-0 w-12 text-center ${theme.badge}`}>
                          {check.status}
                        </span>
                        <p className="flex-1 min-w-0 text-xs sm:text-[13px] text-primary leading-snug break-words" title={displayMessage}>
                          {displayMessage}
                        </p>
                      </div>
                      {showFix && (
                        <div className="mt-2 ml-[4.25rem] rounded-lg border-l-2 border-accent-primary bg-accent-primary/5 px-3 py-2">
                          <div className="flex items-start gap-2 text-[12px] text-primary leading-relaxed">
                            <span className="mt-[2px] text-accent-primary shrink-0 font-bold" aria-hidden="true">→</span>
                            <span className="flex-1 min-w-0">
                              <span className="font-semibold text-accent-primary mr-1">
                                {t('result.fix')}
                              </span>
                              <span className="text-secondary whitespace-pre-line break-words">{fixText}</span>
                            </span>
                          </div>
                        </div>
                      )}
                      {/* Upgrade hint for FAIL/WARN items when user cannot see fixes */}
                      {!canShowFix && (check.status === 'FAIL' || check.status === 'WARN') && (
                        <button
                          onClick={() => {
                            if (!isLoggedIn) { openAuthModal('login'); return; }
                            openTierModal();
                          }}
                          className="mt-2 ml-[4.25rem] flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-dashed border-amber-500/40 bg-amber-500/5 hover:bg-amber-500/10 transition-colors group cursor-pointer"
                        >
                          <svg xmlns="http://www.w3.org/2000/svg" className="h-3 w-3 text-amber-500 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                          </svg>
                          <span className="text-[11px] text-amber-600 group-hover:text-amber-700 transition-colors">
                            {t('result.upgradeHint.fixPrompt', { defaultValue: 'Upgrade to get fix recommendations →' })}
                          </span>
                        </button>
                      )}
                    </div>
                  );
                };

                const renderCategoryBlock = (
                  categoryKey: string,
                  checksForCategory: CheckResult[],
                  rows: ReactNode,
                  visibleCount: number,
                  totalCount: number,
                ) => {
                  const lockedInCat = totalCount - visibleCount;
                  // For the handful of categories that render as a rich visual
                  // (robots.txt, Meta Tags, Platform grids), the visual itself
                  // doesn't surface check.fix. Collect fix text separately so
                  // starter+ tiers still see actionable recommendations.
                  const visualFixes = checksForCategory
                    .filter((c) => c.status !== 'PASS')
                    .map((c) => ({ status: c.status, text: renderCheckFix(c, t) }))
                    .filter((f) => !!f.text);
                  // Try the rich visual first. resolveCategoryVisual is a plain
                  // function — it returns a React element or null. If null, we
                  // fall back to the plain row list so every category always
                  // renders *something*. (This was previously a <Component/> ref
                  // which made `visual` always truthy and silently broke the
                  // fallback — the list never rendered for un-visualized
                  // categories like HTTPS / sitemap.xml / Mobile & Weight.)
                  const visual = resolveCategoryVisual(categoryKey, checksForCategory);
                  return (
                    <div key={categoryKey}>
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <span className="w-1 h-4 gradient-bg rounded-full"></span>
                          <h3 className="text-sm font-semibold text-primary">
                            {t(`result.categoryLabels.${categoryKey}`, { defaultValue: categoryKey })}
                          </h3>
                        </div>
                        <div className="flex items-center gap-2">
                          {lockedInCat > 0 && (
                            <span className="flex items-center gap-1 text-[10px] font-mono text-accent-primary">
                              <svg xmlns="http://www.w3.org/2000/svg" className="h-2.5 w-2.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                              </svg>
                              +{lockedInCat}
                            </span>
                          )}
                          <span className="text-[10px] font-mono text-muted">
                            {visibleCount}/{totalCount}
                          </span>
                        </div>
                      </div>
                      {visual ? (
                        visual
                      ) : (
                        <div className="bg-card border border-border rounded-xl overflow-hidden">
                          <div className="divide-y divide-border">{rows}</div>
                        </div>
                      )}
                      {visual && canShowFix && visualFixes.length > 0 && (
                        <div className="mt-2 space-y-2">
                          {visualFixes.map((f, idx) => {
                            const theme = statusTheme(f.status);
                            return (
                              <div
                                key={idx}
                                className="rounded-lg border-l-2 border-accent-primary bg-accent-primary/5 px-3 py-2 flex items-start gap-2 text-[12px] text-primary leading-relaxed"
                              >
                                <span className={`mt-0.5 px-1.5 py-0.5 rounded text-[9px] font-bold border shrink-0 w-12 text-center ${theme.badge}`}>
                                  {f.status}
                                </span>
                                <span className="mt-[2px] text-accent-primary shrink-0 font-bold" aria-hidden="true">→</span>
                                <span className="flex-1 min-w-0">
                                  <span className="font-semibold text-accent-primary mr-1">
                                    {t('result.fix')}
                                  </span>
                                  <span className="text-secondary whitespace-pre-line break-words">{f.text}</span>
                                </span>
                              </div>
                            );
                          })}
                        </div>
                      )}
                      {/* Upgrade hint for visual categories with issues when user cannot see fixes */}
                      {visual && !canShowFix && checksForCategory.some((c) => c.status === 'FAIL' || c.status === 'WARN') && (
                        <button
                          onClick={() => {
                            if (!isLoggedIn) { openAuthModal('login'); return; }
                            openTierModal();
                          }}
                          className="mt-2 w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg border border-dashed border-amber-500/40 bg-amber-500/5 hover:bg-amber-500/10 transition-colors group cursor-pointer"
                        >
                          <svg xmlns="http://www.w3.org/2000/svg" className="h-3 w-3 text-amber-500 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                          </svg>
                          <span className="text-[11px] text-amber-600 group-hover:text-amber-700 transition-colors">
                            {t('result.upgradeHint.fixPrompt', { defaultValue: 'Upgrade to get fix recommendations →' })}
                          </span>
                        </button>
                      )}
                    </div>
                  );
                };

                const renderLockedPlaceholder = (categoryKey: string) => (
                  <div key={`locked-${categoryKey}`}>
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <span className="w-1 h-4 gradient-bg rounded-full opacity-60"></span>
                        <h3 className="text-sm font-semibold text-secondary">
                          {t(`result.categoryLabels.${categoryKey}`, { defaultValue: categoryKey })}
                        </h3>
                      </div>
                      <span className="flex items-center gap-1 text-[10px] font-mono text-accent-primary">
                        <svg xmlns="http://www.w3.org/2000/svg" className="h-2.5 w-2.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                        </svg>
                        {t('result.paywall.locked')}
                      </span>
                    </div>
                    <button
                      onClick={handleUnlockClick}
                      className="w-full flex items-center gap-3 px-4 py-3 rounded-xl border border-dashed border-border bg-tertiary hover:bg-surface-hover transition-colors group"
                    >
                      <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 text-accent-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                      </svg>
                      <span className="text-xs text-secondary group-hover:text-primary transition-colors">
                        {t('result.paywall.unlockCategory', { defaultValue: '升级检测会员解锁本项检测 →' })}
                      </span>
                    </button>
                  </div>
                );

                const presentCategories = activeCategories.filter(
                  (c) => (checksByCategory[c]?.length ?? 0) > 0 || lockedCategorySet.has(c),
                );

                if (presentCategories.length === 0) {
                  return (
                    <div className="bg-card border border-border rounded-xl p-8 text-center text-secondary text-xs">
                      {t('result.error.noData')}
                    </div>
                  );
                }

                // Render each category either as a full block (unlocked / has data)
                // or as a 🔒 placeholder card (belongs to the tab but is in the
                // locked set for this tier).
                return presentCategories.map((categoryKey) => {
                  if (lockedCategorySet.has(categoryKey)) {
                    return renderLockedPlaceholder(categoryKey);
                  }
                  const checks = checksByCategory[categoryKey] || [];
                  return renderCategoryBlock(
                    categoryKey,
                    checks,
                    checks.map((check, idx) => renderRow(check, `${categoryKey}-${idx}`)),
                    checks.length,
                    checks.length,
                  );
                });
              })()}
            </div>

            {/* Footer actions */}
            <div className="flex flex-col sm:flex-row gap-3">
              {/* <button
              onClick={() => navigate('/')}
              className="flex-1 bg-card border border-border rounded-xl py-3 px-5 text-sm font-semibold text-primary hover:bg-tertiary hover:border-border-strong transition-all flex items-center justify-center gap-2"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
              </svg>
              {t('result.buttons.checkAnother')}
            </button> */}
              {!isUnlocked && (
                <button
                  onClick={handleUnlockClick}
                  className="flex-1 btn-solid rounded-xl py-3 px-5 text-sm font-semibold transition-all shadow-glow flex items-center justify-center gap-2"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                  </svg>
                  {t('result.paywall.viewAll')}
                </button>
              )}
              <button
                onClick={handleContactClick}
                className="flex-1 bg-card border border-border rounded-xl py-3 px-5 text-sm font-semibold text-primary hover:bg-tertiary hover:border-border-strong transition-all flex items-center justify-center gap-2"
              >
                <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 8h2a2 2 0 012 2v6a2 2 0 01-2 2h-2v4l-4-4H9a1.994 1.994 0 01-1.414-.586m0 0L11 14h4a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2v4l.586-.586z" />
                </svg>
                {t('result.buttons.getHelp')}
              </button>
            </div>
          </>)}
        </div>
      </main>

      {showPaymentModal && token && (
        <PaymentModal
          token={token}
          onClose={() => setShowPaymentModal(false)}
          onSuccess={handlePaymentSuccess}
        />
      )}

      {showContactModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 animate-fade-in"
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
              className="absolute top-4 right-4 w-8 h-8 rounded-full flex items-center justify-center text-secondary hover:text-primary hover:bg-tertiary transition-colors disabled:opacity-50"
              aria-label="关闭"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
            <h2 className="text-2xl font-bold mb-2 pr-10">
              <span className="gradient-text">{t('productsServices.sections.contactConsultation')}</span>
            </h2>
            <p className="text-sm text-secondary mb-6">{t('productsServices.contact.getCustomPlan')}</p>
            {feedback && (
              <div className={`mb-6 p-4 rounded-lg ${feedbackKind === 'success' ? 'bg-green-500/10 text-green-400' : 'bg-rose-500/10 text-rose-400'}`}>
                {feedback}
              </div>
            )}
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
                  className="w-full px-4 py-3 rounded-lg bg-card border border-border text-primary placeholder-muted focus:outline-none focus:border-accent-primary transition-colors duration-200"
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
                  className="w-full px-4 py-3 rounded-lg bg-card border border-border text-primary placeholder-muted focus:outline-none focus:border-accent-primary transition-colors duration-200"
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
                  required
                  value={form.website}
                  onChange={(e) => setForm({ ...form, website: e.target.value })}
                  className="w-full px-4 py-3 rounded-lg bg-card border border-border text-primary placeholder-muted focus:outline-none focus:border-accent-primary transition-colors duration-200"
                  placeholder={t('productsServices.contact.websitePlaceholder')}
                />
              </div>
              <div>
                <label htmlFor="service" className="block text-sm font-semibold mb-2">
                  {t('productsServices.contact.service')}
                </label>
                <select
                  id="service"
                  name="service"
                  required
                  value={form.service}
                  onChange={(e) => setForm({ ...form, service: e.target.value })}
                  className="w-full px-4 py-3 rounded-lg bg-card border border-border text-primary placeholder-muted focus:outline-none focus:border-accent-primary transition-colors duration-200"
                >
                  <option value="">{t('productsServices.contact.service')}</option>
                  <option value="Basic Detection Service">{t('productsServices.contact.serviceOptions.0')}</option>
                  <option value="Advanced Detection Service">{t('productsServices.contact.serviceOptions.1')}</option>
                  <option value="Custom GEO Optimization Service">{t('productsServices.contact.serviceOptions.2')}</option>
                </select>
              </div>
              <div>
                <label htmlFor="message" className="block text-sm font-semibold mb-2">
                  {t('productsServices.contact.message')}
                </label>
                <textarea
                  id="message"
                  name="message"
                  required
                  value={form.message}
                  onChange={(e) => setForm({ ...form, message: e.target.value })}
                  rows={4}
                  className="w-full px-4 py-3 rounded-lg bg-card border border-border text-primary placeholder-muted focus:outline-none focus:border-accent-primary transition-colors duration-200"
                  placeholder={t('productsServices.contact.messagePlaceholder')}
                ></textarea>
              </div>
              <button
                type="submit"
                disabled={submitting}
                className="w-full py-3 px-4 bg-gradient text-white rounded-lg font-semibold hover:opacity-90 transition-all shadow-glow disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {submitting ? 'Sending...' : t('productsServices.contact.submit')}
              </button>
            </form>
          </div>
        </div>
      )}

      {rerunLoading && <CheckProgress mode={rerunMode} />}
    </div>
  );
}

// Mode-aware hero for the top-left of the Result page when an advanced
// check has been run. Each mode picks its own headline number, suffix,
// grade pill, and progress bar — the layout matches the default hero so
// nothing else on the page shifts.
function renderAdvancedHero(
  state: { mode: AdvancedMode; data: AnyAdvancedResult },
  t: ReturnType<typeof useTranslation>['t'],
): ReactNode {
  const { mode, data } = state;
  const labelClass =
    'uppercase tracking-[0.15em] text-muted text-[10px] shrink-0';
  const subjectClass =
    'text-accent-primary hover:text-primary transition-colors font-medium truncate';

  // crawlTest is special: no /100 score; the headline is total_issues
  // colored by severity (0 = good, 1-3 = warn, >3 = bad).
  if (mode === 'crawlTest') {
    const d = data as import('../types/advanced').CrawlTestResponse;
    const issues = d.total_issues;
    const tone =
      issues === 0
        ? 'text-emerald-400'
        : issues > 3
          ? 'text-rose-400'
          : 'text-amber-400';
    return (
      <>
        <div className="flex items-center gap-2 text-xs sm:text-sm text-secondary min-w-0 mb-2">
          <span className={labelClass}>{t('home.advanced.cards.crawlTest.title')}</span>
          <a href={d.url} target="_blank" rel="noopener noreferrer" className={subjectClass}>
            {d.domain || d.url}
          </a>
        </div>
        <div className="flex items-end gap-3">
          <div className="flex items-baseline gap-1 leading-none">
            <span className={`text-5xl sm:text-6xl font-black tabular-nums tracking-tight ${tone}`}>{issues}</span>
            <span className="text-lg text-muted font-mono">
              {issues === 1 ? 'issue' : 'issues'}
            </span>
          </div>
          <div className="flex flex-col items-start gap-1 pb-1">
            <span className="text-[9px] uppercase tracking-[0.2em] text-muted font-semibold">
              {t('home.advanced.result.crawl.totalIssues')}
            </span>
            <span className="text-xs font-bold px-2 py-0.5 rounded bg-tertiary text-primary border border-border leading-none">
              {issues === 0
                ? t('home.advanced.result.crawl.allClear')
                : t('home.advanced.result.crawl.needsFix')}
            </span>
          </div>
        </div>
      </>
    );
  }

  // Score-bearing modes: shared layout, mode-specific fields.
  let topLabel = '';
  let subjectText = '';
  let subjectHref: string | null = null;
  let bigNum: string | number = '';
  let bigSuffix = '';
  let gradeText = '';
  let progressPct = 0;

  if (mode === 'visibility') {
    const d = data as import('../types/advanced').AiVisibilityResponse;
    topLabel = t('home.advanced.cards.visibility.title');
    subjectText = d.brand || d.domain;
    subjectHref = d.url;
    bigNum = d.total_score;
    bigSuffix = `/${d.max_score}`;
    gradeText = d.grade_label ? `${d.grade} · ${d.grade_label}` : d.grade;
    progressPct = d.max_score > 0 ? (d.total_score / d.max_score) * 100 : 0;
  } else if (mode === 'authority') {
    const d = data as import('../types/advanced').AuthorityAuditResponse;
    topLabel = t('home.advanced.cards.authority.title');
    subjectText = d.brand || d.domain;
    subjectHref = d.url;
    bigNum = Math.round(d.percent);
    bigSuffix = '%';
    gradeText = d.grade;
    progressPct = d.percent;
  } else if (mode === 'entity') {
    const d = data as import('../types/advanced').EntityAuditResponse;
    topLabel = t('home.advanced.cards.entity.title');
    subjectText = d.entity;
    bigNum = Math.round(d.percent);
    bigSuffix = '%';
    gradeText = d.grade;
    progressPct = d.percent;
  } else if (mode === 'citation') {
    const d = data as import('../types/advanced').CitationCheckResponse;
    topLabel = `${t('home.advanced.cards.citation.title')}${d.engine ? ` · ${d.engine}` : ''}`;
    subjectText = d.brand || d.domain;
    subjectHref = d.url;
    const ratePct = Math.round(d.citation_rate);
    bigNum = ratePct;
    bigSuffix = '%';
    gradeText = d.grade;
    progressPct = ratePct;
  } else if (mode === 'compare') {
    const d = data as import('../types/advanced').CompareResponse;
    topLabel = t('home.advanced.cards.compare.title');
    subjectText = d.winner
      ? `${t('result.advancedHero.winner', { defaultValue: 'Winner' })}: ${d.winner.domain}`
      : `${d.urls.length} URLs`;
    bigNum = d.winner?.score ?? 0;
    bigSuffix = '/100';
    gradeText = d.winner?.grade ?? '—';
    progressPct = d.winner?.score ?? 0;
  }

  return (
    <>
      <div className="flex items-center gap-2 text-xs sm:text-sm text-secondary min-w-0 mb-2">
        <span className={labelClass}>{topLabel}</span>
        {subjectHref ? (
          <a href={subjectHref} target="_blank" rel="noopener noreferrer" className={subjectClass}>
            {subjectText}
          </a>
        ) : (
          <span className="font-medium text-primary truncate">{subjectText}</span>
        )}
      </div>
      <div className="flex items-center gap-4">
        <svg width="72" height="72" viewBox="0 0 72 72" className="transform -rotate-90 shrink-0">
          <defs>
            <linearGradient id="adv-ring-grad" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="var(--accent-primary, #06b6d4)" />
              <stop offset="100%" stopColor="var(--accent-secondary, #3b82f6)" />
            </linearGradient>
          </defs>
          <circle cx="36" cy="36" r="30" fill="none" stroke="var(--bg-tertiary, rgba(148,163,184,0.12))" strokeWidth="5" />
          <circle
            cx="36" cy="36" r="30"
            fill="none"
            stroke="url(#adv-ring-grad)"
            strokeWidth="5"
            strokeLinecap="round"
            strokeDasharray={`${2 * Math.PI * 30}`}
            strokeDashoffset={`${2 * Math.PI * 30 * (1 - Math.max(0, Math.min(100, progressPct)) / 100)}`}
            className="transition-all duration-700"
          />
          <text
            x="36" y="36"
            textAnchor="middle"
            dominantBaseline="central"
            className="transform rotate-90 origin-center"
            fill="var(--text-primary, #e2e8f0)"
            fontSize="18"
            fontWeight="800"
          >
            {bigNum}
          </text>
        </svg>
        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted font-mono">{bigSuffix}</span>
          <span className="text-[9px] uppercase tracking-[0.2em] text-muted font-semibold">
            {t('result.scoreCard.title', { defaultValue: 'Score' })}
          </span>
          <span className="text-sm font-bold px-2 py-0.5 rounded bg-tertiary text-primary border border-border leading-none w-fit">
            {gradeText}
          </span>
        </div>
      </div>
    </>
  );
}

function StatPill({
  color,
  value,
  label,
  items = [],
}: {
  color: 'emerald' | 'amber' | 'rose' | 'cyan' | 'muted';
  value: number;
  label: string;
  items?: string[];
}) {
  const palette = {
    emerald: { text: 'text-emerald-500', dot: 'bg-emerald-500', border: 'border-emerald-500/30', bg: 'bg-emerald-500/10' },
    amber: { text: 'text-amber-500', dot: 'bg-amber-500', border: 'border-amber-500/30', bg: 'bg-amber-500/10' },
    rose: { text: 'text-rose-500', dot: 'bg-rose-500', border: 'border-rose-500/30', bg: 'bg-rose-500/10' },
    cyan: { text: 'text-cyan-500', dot: 'bg-cyan-500', border: 'border-cyan-500/30', bg: 'bg-cyan-500/10' },
    muted: { text: 'text-primary', dot: 'bg-muted', border: 'border-border', bg: 'bg-tertiary' },
  }[color];
  const hasItems = items.length > 0;
  const pill = (
    <div
      className={`flex items-center gap-2.5 px-3 py-2 rounded-lg border border-border-strong ${palette.border} ${palette.bg} ${hasItems ? 'cursor-help' : ''}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${palette.dot}`}></span>
      <div className="flex flex-col leading-tight min-w-0">
        <span className={`text-base font-bold tabular-nums ${palette.text}`}>{value}</span>
        <span className="text-[9px] uppercase tracking-wider text-muted truncate">{label}</span>
      </div>
    </div>
  );
  return (
    <Tooltip
      disabled={!hasItems}
      content={
        <ul className="space-y-1">
          {items.map((name, i) => (
            <li key={i} className="flex items-start gap-1.5">
              <span className={`mt-1 w-1 h-1 rounded-full shrink-0 ${palette.dot}`}></span>
              <span>{name}</span>
            </li>
          ))}
        </ul>
      }
    >
      {pill}
    </Tooltip>
  );
}
