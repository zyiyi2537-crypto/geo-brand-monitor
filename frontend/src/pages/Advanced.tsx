import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useLoadNs } from '../i18n/useLoadNs';
import { useAuthModal } from '../contexts/AuthModalContext';
import { geoApi } from '../services/geoApi';
import { useMembership } from '../hooks/useMembership';
import { validateUrl, normalizeUrl } from '../utils/validateUrl';
import { PaymentModal } from '../components/PaymentModal';
import type {
  AdvancedMode,
  AeoVisibilityResponse,
  CompareResponse,
  CrawlTestResponse,
  AuthorityAuditResponse,
  CitationCheckResponse,
  AiVisibilityResponse,
  EntityAuditResponse,
} from '../types/advanced';
import { SourceAnalysisPanel } from '../components/source-analysis/SourceAnalysisPanel';

// Must match backend MODE_MIN_TIER in app/models/advanced.py.
const MODE_MIN_TIER: Record<AdvancedMode, 'free' | 'pro' | 'starter'> = {
  aeo: 'free',
  compare: 'pro',
  crawlTest: 'pro',
  authority: 'pro',
  citation: 'pro',
  visibility: 'starter',
  entity: 'free',
};

const VALID_MODES: AdvancedMode[] = [
  'aeo',
  'compare',
  'crawlTest',
  'authority',
  'citation',
  'visibility',
  'entity',
];

interface ModeVisual {
  gradient: string;
  icon: ReactNode;
}

// Visual tokens per advanced mode. Display labels come from i18n via
// `home.advanced.cards.<mode>.title` — kept out of this table so the UI
// stays fully localizable.
const MODE_VISUALS: Record<AdvancedMode, ModeVisual> = {
  aeo: {
    gradient: 'linear-gradient(135deg, #10b981 0%, #06b6d4 100%)',
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
      </svg>
    ),
  },
  compare: {
    gradient: 'linear-gradient(135deg, #06b6d4 0%, #3b82f6 100%)',
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="10" width="5" height="11" rx="1" />
        <rect x="10" y="4" width="5" height="17" rx="1" />
        <rect x="17" y="7" width="5" height="14" rx="1" />
      </svg>
    ),
  },
  crawlTest: {
    gradient: 'linear-gradient(135deg, #8b5cf6 0%, #ec4899 100%)',
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="9" />
        <path d="M3 12h18" />
        <path d="M12 3a14 14 0 0 1 0 18" />
        <path d="M12 3a14 14 0 0 0 0 18" />
      </svg>
    ),
  },
  authority: {
    gradient: 'linear-gradient(135deg, #f59e0b 0%, #ef4444 100%)',
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
      </svg>
    ),
  },
  citation: {
    gradient: 'linear-gradient(135deg, #10b981 0%, #06b6d4 100%)',
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M7 7h3v3H7z" />
        <path d="M14 7h3v3h-3z" />
        <path d="M10 10c0 3-1.5 5-4 6" />
        <path d="M17 10c0 3-1.5 5-4 6" />
      </svg>
    ),
  },
  visibility: {
    gradient: 'linear-gradient(135deg, #06b6d4 0%, #a855f7 50%, #ec4899 100%)',
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
        <circle cx="12" cy="12" r="3" />
      </svg>
    ),
  },
  entity: {
    gradient: 'linear-gradient(135deg, #ec4899 0%, #f59e0b 100%)',
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="3" />
        <circle cx="5" cy="5" r="2" />
        <circle cx="19" cy="5" r="2" />
        <circle cx="5" cy="19" r="2" />
        <circle cx="19" cy="19" r="2" />
        <path d="M7 7l2.8 2.8M17 7l-2.8 2.8M7 17l2.8-2.8M17 17l-2.8-2.8" />
      </svg>
    ),
  },
};

export type AnyAdvancedResult =
  | AeoVisibilityResponse
  | CompareResponse
  | CrawlTestResponse
  | AuthorityAuditResponse
  | CitationCheckResponse
  | AiVisibilityResponse
  | EntityAuditResponse;

export function Advanced() {
  useLoadNs('result');
  const { mode: modeParam } = useParams<{ mode: string }>();
  const navigate = useNavigate();
  const { openAuthModal } = useAuthModal();
  const location = useLocation();
  const { t } = useTranslation();
  const { token, isLoggedIn, isUnlocked, refresh } = useMembership();

  const mode = VALID_MODES.includes(modeParam as AdvancedMode)
    ? (modeParam as AdvancedMode)
    : null;

  const navState = location.state as
    | { url?: string; prefilledResult?: AnyAdvancedResult }
    | null;
  const initialUrl = navState?.url || '';
  const prefilledResult = navState?.prefilledResult ?? null;

  // Per-mode form state
  const [urlInput, setUrlInput] = useState<string>(initialUrl || '');
  const [compareUrls, setCompareUrls] = useState<string[]>(() => {
    if (initialUrl) return [initialUrl, 'https://example.org'];
    return ['', 'https://example.org'];
  });
  const [customQueries, setCustomQueries] = useState<string>('');
  const [entityName, setEntityName] = useState<string>('');
  const [entityType, setEntityType] = useState<'brand' | 'product' | 'person'>('brand');

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>('');
  const [result, setResult] = useState<AnyAdvancedResult | null>(prefilledResult);
  const [showPaymentModal, setShowPaymentModal] = useState(false);

  useEffect(() => {
    if (mode !== 'aeo' && !isLoggedIn) {
      openAuthModal('login');
    }
  }, [isLoggedIn, mode, openAuthModal]);

  if (!mode) {
    return (
      <div className="min-h-screen grid-background flex items-center justify-center p-6">
        <div className="bg-card border border-border-strong rounded-2xl p-8 max-w-md text-center">
          <h2 className="text-2xl font-bold mb-3 gradient-text">
            {t('common.error', { defaultValue: 'Error' })}
          </h2>
          <p className="text-secondary mb-6">Unknown advanced mode: {modeParam}</p>
          <button
            onClick={() => navigate('/')}
            className="btn-solid rounded-full py-2.5 px-6 font-semibold transition"
          >
            {t('result.buttons.checkAnother', { defaultValue: 'Back to home' })}
          </button>
        </div>
      </div>
    );
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');

    // Client-side validation per mode
    if (mode === 'compare') {
      const cleaned = compareUrls.map((u) => u.trim()).filter(Boolean);
      if (cleaned.length < 2) {
        setError(t('home.advanced.validation.minUrls'));
        return;
      }
      for (const u of cleaned) {
        if (!validateUrl(u)) {
          setError(t('home.advanced.validation.invalidUrl', { url: u }));
          return;
        }
      }
    } else if (mode === 'entity') {
      if (!entityName.trim()) {
        setError(t('home.advanced.validation.entityRequired'));
        return;
      }
    } else {
      if (!urlInput.trim()) {
        setError(t('home.error.empty', { defaultValue: 'URL is required' }));
        return;
      }
      if (!validateUrl(urlInput)) {
        setError(t('home.error.invalid', { defaultValue: 'Invalid URL format' }));
        return;
      }
    }

    if (mode !== 'aeo' && !isUnlocked) {
      setShowPaymentModal(true);
      return;
    }

    setLoading(true);
    setResult(null);
    try {
      let data: AnyAdvancedResult;
      if (mode === 'compare') {
        data = await geoApi.runAdvancedCheck('compare', {
          urls: compareUrls.map((u) => normalizeUrl(u)).filter(Boolean),
        });
      } else if (mode === 'visibility') {
        const queries = customQueries
          .split('\n')
          .map((q) => q.trim())
          .filter(Boolean);
        data = await geoApi.runAdvancedCheck('visibility', {
          url: normalizeUrl(urlInput),
          custom_queries: queries.length ? queries : undefined,
        });
      } else if (mode === 'entity') {
        data = await geoApi.runAdvancedCheck('entity', {
          entity_name: entityName.trim(),
          entity_type: entityType,
        });
      } else {
        data = await geoApi.runAdvancedCheck(mode, { url: normalizeUrl(urlInput) });
      }
      setResult(data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : t('home.advanced.validation.unexpected');
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const modeTitle = t(`home.advanced.cards.${mode}.title`);
  const modeDesc = t(`home.advanced.cards.${mode}.desc`);

  return (
    <div className="min-h-screen grid-background">
      <div className="bg-glow bg-glow-1"></div>
      <div className="bg-glow bg-glow-2"></div>
      <div className="bg-glow bg-glow-3"></div>

      <main className="flex-1 px-4 py-10 hero-gradient relative z-10">
        <div className="w-full max-w-5xl mx-auto animate-fade-in">
          <button
            onClick={() => navigate('/')}
            className="text-sm text-secondary hover:text-primary mb-4 inline-flex items-center gap-1"
          >
            ← {t('result.buttons.checkAnother', { defaultValue: 'Back' })}
          </button>

          <div className="relative overflow-hidden bg-card border border-border-strong rounded-3xl p-6 sm:p-7 mb-8">
            <div
              className="absolute -top-28 -right-24 w-72 h-72 rounded-full opacity-20 blur-3xl pointer-events-none"
              style={{ background: MODE_VISUALS[mode].gradient }}
            />
            <div className="relative flex items-start gap-4 sm:gap-5">
              <div
                className="w-14 h-14 sm:w-16 sm:h-16 shrink-0 rounded-2xl flex items-center justify-center text-white shadow-lg"
                style={{ background: MODE_VISUALS[mode].gradient }}
              >
                {MODE_VISUALS[mode].icon}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap items-center gap-1.5 mb-2">
                  <span className="inline-flex items-center px-2.5 py-0.5 rounded-full bg-accent-primary/10 border border-accent-primary/30 text-[10px] font-bold text-accent-primary uppercase tracking-[0.12em]">
                    {t('home.advanced.badge')}
                  </span>
                  <span className="inline-flex items-center px-2.5 py-0.5 rounded-full border border-border-strong text-[10px] font-bold text-secondary uppercase tracking-[0.12em]">
                    {MODE_MIN_TIER[mode]}+
                  </span>
                  <span className="inline-flex items-center px-2.5 py-0.5 rounded-full border border-border-strong text-[10px] font-mono text-secondary">
                    {t(`home.advanced.cards.${mode}.title`)}
                  </span>
                </div>
                <h1 className="text-2xl sm:text-3xl font-bold gradient-text mb-2 leading-tight">
                  {modeTitle}
                </h1>
                <p className="text-secondary text-sm sm:text-[15px] leading-relaxed max-w-3xl">
                  {modeDesc}
                </p>
              </div>
            </div>
          </div>

          {!isUnlocked && (
            <div className="mb-6 bg-amber-500/10 border border-amber-500/30 rounded-2xl p-5">
              <p className="text-amber-300 text-sm mb-3">
                This feature requires a <strong>{MODE_MIN_TIER[mode]}</strong> membership or higher.
              </p>
              <button
                onClick={() => setShowPaymentModal(true)}
                className="btn-solid rounded-full py-2 px-5 text-sm font-semibold"
              >
                {t('home.advanced.upgrade')}
              </button>
            </div>
          )}

          <form
            onSubmit={handleSubmit}
            className="bg-card border border-border-strong rounded-2xl p-6 mb-8"
          >
            <ModeForm
              mode={mode}
              urlInput={urlInput}
              setUrlInput={setUrlInput}
              compareUrls={compareUrls}
              setCompareUrls={setCompareUrls}
              customQueries={customQueries}
              setCustomQueries={setCustomQueries}
              entityName={entityName}
              setEntityName={setEntityName}
              entityType={entityType}
              setEntityType={setEntityType}
              loading={loading}
            />

            {error && (
              <div className="mt-4 bg-red-900/40 border border-red-800 rounded-xl p-3 text-sm text-red-300">
                {error}
              </div>
            )}

            <div className="mt-5 flex gap-3">
              <button
                type="submit"
                disabled={loading}
                className="btn-solid rounded-full py-2.5 px-6 font-semibold transition disabled:opacity-60"
              >
                {loading
                  ? t('home.analyzing', { defaultValue: 'Analyzing...' })
                  : t('home.button', { defaultValue: 'Run check' })}
              </button>
            </div>
          </form>

          {result && <ResultPanel mode={mode} result={result} />}
        </div>
      </main>

      {showPaymentModal && token && (
        <PaymentModal
          token={token}
          onClose={() => setShowPaymentModal(false)}
          onSuccess={() => {
            setShowPaymentModal(false);
            refresh();
          }}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Form per mode
// ---------------------------------------------------------------------------

interface ModeFormProps {
  mode: AdvancedMode;
  urlInput: string;
  setUrlInput: (v: string) => void;
  compareUrls: string[];
  setCompareUrls: (v: string[]) => void;
  customQueries: string;
  setCustomQueries: (v: string) => void;
  entityName: string;
  setEntityName: (v: string) => void;
  entityType: 'brand' | 'product' | 'person';
  setEntityType: (v: 'brand' | 'product' | 'person') => void;
  loading: boolean;
}

function ModeForm(props: ModeFormProps) {
  const { mode, urlInput, setUrlInput, compareUrls, setCompareUrls, loading } = props;

  const inputClass =
    'w-full bg-tertiary border border-border-strong rounded-xl px-4 py-3 text-primary placeholder-muted focus:outline-none focus:border-accent-primary';

  if (mode === 'compare') {
    return (
      <div>
        <label className="text-sm font-semibold text-primary mb-3 block">URLs to compare</label>
        {compareUrls.map((u, i) => (
          <div key={i} className="flex gap-2 mb-2">
            <input
              type="text"
              value={u}
              onChange={(e) => {
                const next = [...compareUrls];
                next[i] = e.target.value;
                setCompareUrls(next);
              }}
              placeholder="example.com"
              disabled={loading}
              className={inputClass}
            />
            {compareUrls.length > 2 && (
              <button
                type="button"
                onClick={() => setCompareUrls(compareUrls.filter((_, idx) => idx !== i))}
                className="text-rose-400 hover:text-rose-300 text-sm px-3"
              >
                ×
              </button>
            )}
          </div>
        ))}
        {compareUrls.length < 5 && (
          <button
            type="button"
            onClick={() => setCompareUrls([...compareUrls, ''])}
            className="text-sm text-accent-primary hover:text-primary mt-1"
          >
            + Add another URL
          </button>
        )}
      </div>
    );
  }

  if (mode === 'entity') {
    return (
      <div className="space-y-4">
        <div>
          <label className="text-sm font-semibold text-primary mb-2 block">Entity name</label>
          <input
            type="text"
            value={props.entityName}
            onChange={(e) => props.setEntityName(e.target.value)}
            placeholder="e.g. Tesla, iPhone, Elon Musk"
            disabled={loading}
            className={inputClass}
          />
        </div>
        <div>
          <label className="text-sm font-semibold text-primary mb-2 block">Entity type</label>
          <select
            value={props.entityType}
            onChange={(e) => props.setEntityType(e.target.value as 'brand' | 'product' | 'person')}
            disabled={loading}
            className={inputClass}
          >
            <option value="brand">Brand</option>
            <option value="product">Product</option>
            <option value="person">Person</option>
          </select>
        </div>
      </div>
    );
  }

  // Single-URL modes
  return (
    <div className="space-y-4">
      <div>
        <label className="text-sm font-semibold text-primary mb-2 block">Target URL</label>
        <input
          type="text"
          value={urlInput}
          onChange={(e) => setUrlInput(e.target.value)}
          placeholder="example.com"
          disabled={loading}
          className={inputClass}
        />
      </div>
      {mode === 'visibility' && (
        <div>
          <label className="text-sm font-semibold text-primary mb-2 block">
            Custom queries (optional, one per line)
          </label>
          <textarea
            value={props.customQueries}
            onChange={(e) => props.setCustomQueries(e.target.value)}
            placeholder={'best AI payment tools\nx402 alternatives'}
            disabled={loading}
            rows={3}
            className={inputClass}
          />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Result per mode
// ---------------------------------------------------------------------------

export function ResultPanel({ mode, result }: { mode: AdvancedMode; result: AnyAdvancedResult }) {
  switch (mode) {
    case 'aeo':
      return <AeoResult data={result as AeoVisibilityResponse} />;
    case 'compare':
      return <CompareResult data={result as CompareResponse} />;
    case 'crawlTest':
      return <CrawlTestResult data={result as CrawlTestResponse} />;
    case 'authority':
      return <AuthorityResult data={result as AuthorityAuditResponse} />;
    case 'citation':
      return <CitationResult data={result as CitationCheckResponse} />;
    case 'visibility':
      return <VisibilityResult data={result as AiVisibilityResponse} />;
    case 'entity':
      return <EntityResult data={result as EntityAuditResponse} />;
  }
}

function SectionCard({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <div className="bg-card border border-border-strong rounded-2xl p-5 sm:p-6 mb-6">
      <div className="flex items-center gap-2.5 mb-4 pb-3 border-b border-border">
        <span className="w-1 h-4 rounded-full gradient-bg" />
        <h3 className="text-base font-bold text-primary leading-tight">{title}</h3>
        {subtitle && (
          <span className="text-[11px] text-secondary ml-auto font-mono">{subtitle}</span>
        )}
      </div>
      {children}
    </div>
  );
}

function ScoreBar({ label, value, max }: { label: string; value: number; max: number }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  const color =
    pct >= 60
      ? 'from-emerald-400 to-emerald-500'
      : pct >= 30
        ? 'from-amber-400 to-amber-500'
        : 'from-rose-400 to-rose-500';
  return (
    <div className="mb-3 last:mb-0">
      <div className="flex justify-between text-xs mb-1.5">
        <span className="text-secondary">{label}</span>
        <span className="font-mono tabular-nums text-primary">
          {value}
          <span className="text-secondary">/{max}</span>
        </span>
      </div>
      <div className="h-2 bg-tertiary rounded-full overflow-hidden">
        <div
          className={`h-full bg-gradient-to-r ${color} transition-all duration-700`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

type StatAccent = 'default' | 'good' | 'warn' | 'bad' | 'gradient';

function StatTile({
  label,
  value,
  accent = 'default',
  hint,
}: {
  label: string;
  value: ReactNode;
  accent?: StatAccent;
  hint?: string;
}) {
  const accentClass =
    accent === 'good'
      ? 'text-emerald-400'
      : accent === 'warn'
        ? 'text-amber-400'
        : accent === 'bad'
          ? 'text-rose-400'
          : accent === 'gradient'
            ? 'gradient-text'
            : 'text-primary';
  return (
    <div className="bg-tertiary border border-border rounded-xl p-4 hover:border-border-strong transition-colors">
      <div className="text-[10px] uppercase tracking-[0.12em] text-secondary mb-1.5 font-semibold">
        {label}
      </div>
      <div className={`text-2xl font-bold tabular-nums leading-none ${accentClass}`}>{value}</div>
      {hint && <div className="text-[10px] text-secondary mt-1.5">{hint}</div>}
    </div>
  );
}

function MetricRing({
  value,
  max,
  suffix,
}: {
  value: number;
  max: number;
  suffix?: string;
}) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  const color = pct >= 70 ? '#34d399' : pct >= 40 ? '#fbbf24' : '#fb7185';
  const r = 42;
  const c = 2 * Math.PI * r;
  const offset = c - (pct / 100) * c;
  const isPercent = suffix === '%';
  return (
    <div className="relative w-28 h-28 shrink-0">
      <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
        <circle cx="50" cy="50" r={r} fill="none" stroke="var(--border-color)" strokeWidth="9" />
        <circle
          cx="50"
          cy="50"
          r={r}
          fill="none"
          stroke={color}
          strokeWidth="9"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={offset}
          className="transition-all duration-700"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <div className="text-2xl font-bold gradient-text leading-none tabular-nums">
          {value}
          {isPercent && <span className="text-lg">%</span>}
        </div>
        {!isPercent && (
          <div className="text-[10px] text-secondary mt-1">
            / {max}
            {suffix}
          </div>
        )}
      </div>
    </div>
  );
}

// --- AEO Visibility ---
function AeoResult({ data }: { data: AeoVisibilityResponse }) {
  const { t } = useTranslation();
  const catEntries = Object.entries(data.categories);
  return (
    <>
      {/* Score hero */}
      <SectionCard title={t('home.advanced.result.aeo.title', { defaultValue: 'AEO Score' })}>
        <div className="flex items-end gap-4 mb-4">
          <div>
            <div className="text-4xl font-bold gradient-text">
              {data.score}<span className="text-lg text-secondary font-normal">/100</span>
            </div>
            <div className="text-sm text-secondary">{data.grade}</div>
          </div>
          <div className="flex-1">
            <ScoreBar
              label={t('home.advanced.result.aeo.overall', { defaultValue: 'Overall AEO Score' })}
              value={data.score}
              max={data.max_score}
            />
          </div>
        </div>
      </SectionCard>

      {/* Category breakdown */}
      <SectionCard title={t('home.advanced.result.aeo.categoryBreakdown', { defaultValue: 'Category Breakdown' })}>
        {catEntries.map(([cat, { earned, max }]) => (
          <ScoreBar key={cat} label={cat} value={earned} max={max} />
        ))}
      </SectionCard>

      {/* Per-page scores */}
      {data.page_results.length > 0 && (
        <SectionCard
          title={t('home.advanced.result.aeo.pageScores', { defaultValue: 'Per-Page AEO Scores' })}
          subtitle={`${data.page_results.length} pages`}
        >
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-secondary text-xs border-b border-border">
                  <th className="text-left pb-2 font-medium">{t('home.advanced.result.aeo.pagePath', { defaultValue: 'Page' })}</th>
                  <th className="text-right pb-2 font-medium">{t('home.advanced.result.aeo.pageScore', { defaultValue: 'Score' })}</th>
                  <th className="text-left pb-2 pl-4 font-medium">{t('home.advanced.result.aeo.weakest', { defaultValue: 'Weakest Signal' })}</th>
                </tr>
              </thead>
              <tbody>
                {data.page_results.map((p) => {
                  const clr = p.score >= 70 ? 'text-emerald-400' : p.score >= 40 ? 'text-amber-400' : 'text-rose-400';
                  return (
                    <tr key={p.path} className="border-b border-border/50 last:border-0">
                      <td className="py-2 font-mono text-xs text-primary truncate max-w-[200px]">{p.path}</td>
                      <td className={`py-2 text-right font-mono font-semibold ${clr}`}>{p.score}</td>
                      <td className="py-2 pl-4 text-secondary text-xs">
                        <span className="text-primary font-medium">{p.weakest_signal}</span>: {p.weakest_detail}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </SectionCard>
      )}

      {/* Priority improvements */}
      {data.priority_improvements.length > 0 && (
        <SectionCard title={t('home.advanced.result.aeo.priorities', { defaultValue: 'Priority Improvements' })}>
          <p className="text-xs text-secondary mb-3">
            {t('home.advanced.result.aeo.prioritiesHint', { defaultValue: 'Categories scoring below 50% — focus here first.' })}
          </p>
          <div className="space-y-2">
            {data.priority_improvements.map((p) => (
              <div key={p.category} className="flex items-center justify-between bg-tertiary rounded-lg px-3 py-2">
                <span className="text-sm text-primary">{p.category}</span>
                <span className={`text-xs font-mono font-semibold ${p.percent < 25 ? 'text-rose-400' : 'text-amber-400'}`}>
                  {p.percent}%
                </span>
              </div>
            ))}
          </div>
        </SectionCard>
      )}
    </>
  );
}

// --- Compare ---
function CompareResult({ data }: { data: CompareResponse }) {
  const { t } = useTranslation();
  return (
    <>
      {data.winner && (
        <div className="relative overflow-hidden bg-card border border-emerald-500/30 rounded-2xl p-5 mb-6">
          <div className="absolute -top-16 -right-16 w-48 h-48 rounded-full bg-emerald-500/10 blur-3xl" />
          <div className="relative flex items-center gap-4">
            <div className="w-14 h-14 rounded-2xl bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center text-emerald-400 shrink-0">
              <svg
                width="28"
                height="28"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
              </svg>
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-[10px] uppercase tracking-[0.15em] text-emerald-400 font-bold mb-1">
                {t('home.advanced.result.compare.winner')}
              </div>
              <div className="flex items-baseline gap-2 flex-wrap">
                <span className="text-lg sm:text-xl font-bold text-primary truncate">
                  {data.winner.domain}
                </span>
                <span className="text-2xl font-bold gradient-text tabular-nums">
                  {data.winner.score}
                  <span className="text-base text-secondary">/100</span>
                </span>
                <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 uppercase tracking-wider">
                  {t('home.advanced.result.compare.gradePrefix')} {data.winner.grade}
                </span>
                {data.winner.lead > 0 && (
                  <span className="text-xs text-secondary">+{data.winner.lead} {t('home.advanced.result.lead')}</span>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
      <SectionCard
        title={t('home.advanced.result.compare.categoryCompare')}
        subtitle={t('home.advanced.result.compare.sitesCategories', { sites: data.results.length, categories: data.categories.length })}
      >
        <div className="overflow-x-auto -mx-5 px-5 sm:-mx-6 sm:px-6">
          <table className="w-full text-sm border-separate border-spacing-0 min-w-[520px]">
            <thead>
              <tr>
                <th className="sticky left-0 z-10 bg-card text-left py-2 pr-4 text-[10px] uppercase tracking-wider text-secondary font-semibold border-b border-border-strong">
                  {t('home.advanced.result.compare.category')}
                </th>
                {data.results.map((r) => (
                  <th
                    key={r.url}
                    className="py-2 px-3 text-primary font-semibold text-xs text-left border-b border-border-strong whitespace-nowrap max-w-[180px] truncate"
                    title={r.domain}
                  >
                    {r.domain}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.categories.map((cat) => {
                const cells = data.results.map((r) => {
                  const v = r.categories?.[cat];
                  const earned = v?.earned ?? 0;
                  const max = v?.max ?? 0;
                  const pct = max > 0 ? Math.round((earned / max) * 100) : 0;
                  return { domain: r.domain, earned, max, pct };
                });
                const topPct = Math.max(...cells.map((c) => c.pct));
                return (
                  <tr key={cat} className="group">
                    <td className="sticky left-0 z-10 bg-card group-hover:bg-surface-hover py-3 pr-4 text-secondary text-xs border-b border-border transition-colors">
                      {cat}
                    </td>
                    {cells.map((c, i) => {
                      const isWinner = c.pct === topPct && topPct > 0;
                      const barColor =
                        c.pct >= 60
                          ? 'bg-emerald-500/70'
                          : c.pct >= 30
                            ? 'bg-amber-500/70'
                            : 'bg-rose-500/70';
                      return (
                        <td
                          key={i}
                          className="py-3 px-3 border-b border-border group-hover:bg-surface-hover transition-colors"
                        >
                          <div className="flex items-center gap-2">
                            <div className="flex-1 h-1.5 bg-tertiary rounded-full overflow-hidden min-w-[40px]">
                              <div
                                className={`h-full ${barColor} transition-all duration-700`}
                                style={{ width: `${c.pct}%` }}
                              />
                            </div>
                            <span
                              className={`tabular-nums text-xs whitespace-nowrap ${isWinner ? 'text-emerald-400 font-bold' : 'text-primary'
                                }`}
                            >
                              {c.pct}%
                            </span>
                          </div>
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
              <tr>
                <td className="sticky left-0 z-10 bg-card py-4 pr-4 font-bold text-primary text-[10px] uppercase tracking-wider border-t-2 border-border-strong">
                  {t('home.advanced.result.compare.total')}
                </td>
                {data.results.map((r) => (
                  <td key={r.url} className="py-4 px-3 border-t-2 border-border-strong">
                    <div className="flex items-baseline gap-1 flex-wrap">
                      <span className="text-xl font-bold gradient-text tabular-nums">
                        {r.score}
                      </span>
                      <span className="text-xs text-secondary">/100</span>
                      <span className="ml-1 text-[10px] px-1.5 py-0.5 rounded bg-accent-primary/10 text-accent-primary border border-accent-primary/20 font-bold">
                        {r.grade}
                      </span>
                    </div>
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      </SectionCard>
    </>
  );
}

// --- Crawl test ---
function CrawlTestResult({ data }: { data: CrawlTestResponse }) {
  const { t } = useTranslation();
  const robotsAllowed = data.robots.bots.filter((b) => b.status !== 'blocked').length;
  const robotsTotal = data.robots.bots.length;
  const wafAllowed = data.waf.bots.filter((b) => b.result === 'allowed').length;
  const wafTotal = data.waf.bots.length;
  return (
    <>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
        <StatTile
          label={t('home.advanced.result.crawl.targetDomain')}
          value={<span className="text-base font-mono truncate block">{data.domain}</span>}
          hint={t(data.common_crawl.found ? 'home.advanced.result.crawl.ccFound' : 'home.advanced.result.crawl.ccNotFound')}
        />
        <StatTile
          label={t('home.advanced.result.crawl.totalIssues')}
          value={data.total_issues}
          accent={data.total_issues === 0 ? 'good' : 'bad'}
          hint={t(data.total_issues === 0 ? 'home.advanced.result.crawl.allClear' : 'home.advanced.result.crawl.needsFix')}
        />
        <StatTile
          label={t('home.advanced.result.crawl.robotsAllowed')}
          value={`${robotsAllowed}/${robotsTotal}`}
          accent={robotsAllowed === robotsTotal ? 'good' : 'warn'}
          hint={t('home.advanced.result.crawl.crawlerPermission')}
        />
        <StatTile
          label={t('home.advanced.result.crawl.wafAllowed')}
          value={`${wafAllowed}/${wafTotal}`}
          accent={wafAllowed === wafTotal ? 'good' : wafAllowed > 0 ? 'warn' : 'bad'}
          hint={t('home.advanced.result.crawl.liveAccess')}
        />
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <SectionCard
          title={t('home.advanced.result.crawl.robotsTitle')}
          subtitle={t(data.robots.found ? 'home.advanced.result.crawl.detected' : 'home.advanced.result.crawl.notFound')}
        >
          {!data.robots.found && (
            <p className="text-xs text-amber-400 mb-3 px-3 py-2 bg-amber-500/10 border border-amber-500/30 rounded-lg">
              {t('home.advanced.result.crawl.robotsMissingWarning')}
            </p>
          )}
          <ul className="space-y-1.5">
            {data.robots.bots.map((b) => {
              const blocked = b.status === 'blocked';
              return (
                <li
                  key={b.bot}
                  className="flex items-center justify-between px-3 py-2 rounded-lg bg-tertiary border border-border"
                >
                  <span className="text-sm text-primary font-mono">{b.bot}</span>
                  <span
                    className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full border ${blocked
                        ? 'bg-rose-500/15 text-rose-400 border-rose-500/30'
                        : 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
                      }`}
                  >
                    {blocked
                      ? t('home.advanced.result.crawl.blocked')
                      : t('home.advanced.result.crawl.allowed')}
                  </span>
                </li>
              );
            })}
          </ul>
        </SectionCard>
        <SectionCard
          title={t('home.advanced.result.crawl.wafTitle')}
          subtitle={t('home.advanced.result.crawl.wafBaseline', { status: data.waf.baseline_status ?? 'n/a', size: (data.waf.baseline_size / 1024).toFixed(1) })}
        >
          <ul className="space-y-1.5">
            {data.waf.bots.map((b) => {
              const tone =
                b.result === 'allowed'
                  ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
                  : b.result === 'suspicious'
                    ? 'bg-amber-500/15 text-amber-400 border-amber-500/30'
                    : 'bg-rose-500/15 text-rose-400 border-rose-500/30';
              return (
                <li
                  key={b.bot}
                  className="flex items-center justify-between px-3 py-2 rounded-lg bg-tertiary border border-border"
                >
                  <span className="text-sm text-primary font-mono">{b.bot}</span>
                  <span
                    className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full border whitespace-nowrap ${tone}`}
                  >
                    {t(`home.advanced.result.crawl.wafStatus.${b.result}`, { defaultValue: b.result })}
                    {b.status_code ? ` · ${b.status_code}` : ''}
                  </span>
                </li>
              );
            })}
          </ul>
        </SectionCard>
      </div>
      <SectionCard
        title={t('home.advanced.result.crawl.commonCrawlTitle')}
        subtitle={data.common_crawl.found ? t('home.advanced.result.crawl.pagesSuffix', { count: data.common_crawl.count }) : t('home.advanced.result.crawl.notIndexed')}
      >
        <div className="flex items-center gap-3 mb-3">
          <div
            className={`w-10 h-10 rounded-xl flex items-center justify-center ${data.common_crawl.found
                ? 'bg-emerald-500/15 border border-emerald-500/30 text-emerald-400'
                : 'bg-amber-500/15 border border-amber-500/30 text-amber-400'
              }`}
          >
            {data.common_crawl.found ? (
              <svg
                width="20"
                height="20"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M20 6L9 17l-5-5" />
              </svg>
            ) : (
              <svg
                width="20"
                height="20"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
            )}
          </div>
          {data.common_crawl.found ? (
            <p className="text-sm text-emerald-400">
              {t('home.advanced.result.crawl.foundInCcPrefix')}
              <span className="font-bold">{data.common_crawl.count}</span>
              {t('home.advanced.result.crawl.foundInCcSuffix')}
            </p>
          ) : (
            <p className="text-sm text-amber-400">
              {t('home.advanced.result.crawl.notIndexed')}{data.common_crawl.error ? ` · ${data.common_crawl.error}` : ''}
            </p>
          )}
        </div>
        {data.common_crawl.samples.length > 0 && (
          <ul className="space-y-1 text-xs text-secondary pt-3 border-t border-border">
            {data.common_crawl.samples.map((s, i) => (
              <li key={i} className="font-mono truncate" title={s}>
                → {s}
              </li>
            ))}
          </ul>
        )}
      </SectionCard>
    </>
  );
}

// --- Authority ---
function AuthorityResult({ data }: { data: AuthorityAuditResponse }) {
  const { t } = useTranslation();
  return (
    <>
      <SectionCard title={t('home.advanced.result.authority.title', { brand: data.brand })}>
        <div className="flex items-end gap-4 mb-4">
          <div>
            <div className="text-4xl font-bold gradient-text">
              {data.score}/{data.max_score}
            </div>
            <div className="text-sm text-secondary">{data.grade}</div>
          </div>
          <div className="flex-1">
            <ScoreBar label={t('home.advanced.result.authority.overall')} value={data.score} max={data.max_score} />
          </div>
        </div>
      </SectionCard>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <SectionCard title={t('home.advanced.result.authority.reviewsTitle')}>
          <p className="text-sm text-secondary mb-2">
            {t('home.advanced.result.authority.reviewSchema')}{' '}
            <span className={data.reviews.has_schema ? 'text-emerald-400' : 'text-amber-400'}>
              {data.reviews.has_schema
                ? t('home.advanced.result.authority.yes')
                : t('home.advanced.result.authority.no')}
            </span>
          </p>
          <p className="text-sm text-secondary mb-1">{t('home.advanced.result.authority.platformsFound')}</p>
          <ul className="text-sm">
            {data.reviews.platforms.length === 0 && (
              <li className="text-amber-400">{t('home.advanced.result.authority.none')}</li>
            )}
            {data.reviews.platforms.map((p) => (
              <li key={p} className="text-emerald-400">• {p}</li>
            ))}
          </ul>
        </SectionCard>
        <SectionCard title={t('home.advanced.result.authority.awardsTitle')}>
          <p className="text-sm text-secondary mb-2">
            {t('home.advanced.result.authority.signalCount')}{' '}
            <span className="text-primary font-semibold">{data.awards.signal_count}</span>
          </p>
          {data.awards.keywords.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-2">
              {data.awards.keywords.slice(0, 12).map((k) => (
                <span key={k} className="text-xs bg-tertiary border border-border-strong rounded-full px-2 py-0.5">
                  {k}
                </span>
              ))}
            </div>
          )}
        </SectionCard>
        <SectionCard title={t('home.advanced.result.authority.googleTitle')}>
          <p className="text-sm mb-1">
            <span className="text-secondary">{t('home.advanced.result.authority.indexedPages')} </span>
            <span className="text-primary">
              {data.google.indexed_pages ?? t('home.advanced.result.authority.unknown')}
            </span>
          </p>
          <p className="text-sm mb-1">
            <span className="text-secondary">{t('home.advanced.result.authority.orgSchemaFields')} </span>
            <span className="text-primary">{data.google.kg_schema_fields}/9</span>
          </p>
          <p className="text-sm">
            <span className="text-secondary">{t('home.advanced.result.authority.wikiLabel')} </span>
            <span className={data.google.wikipedia_or_wikidata ? 'text-emerald-400' : 'text-amber-400'}>
              {data.google.wikipedia_or_wikidata
                ? t('home.advanced.result.authority.yes')
                : t('home.advanced.result.authority.no')}
            </span>
          </p>
        </SectionCard>
        <SectionCard title={t('home.advanced.result.authority.mentionsTitle')}>
          <ul className="text-sm">
            {data.mentions.platforms.length === 0 && (
              <li className="text-amber-400">{t('home.advanced.result.authority.none')}</li>
            )}
            {data.mentions.platforms.map((p) => (
              <li key={p} className="text-emerald-400">• {p}</li>
            ))}
          </ul>
        </SectionCard>
      </div>
    </>
  );
}

// --- Citation ---
function CitationResult({ data }: { data: CitationCheckResponse }) {
  const { t } = useTranslation();
  return (
    <>
      <div className="relative overflow-hidden bg-card border border-border-strong rounded-2xl p-5 sm:p-6 mb-6">
        <div className="absolute -top-20 -right-20 w-56 h-56 rounded-full bg-emerald-500/10 blur-3xl" />
        <div className="relative flex flex-col sm:flex-row sm:items-center gap-5 sm:gap-6">
          <MetricRing value={Math.round(data.citation_rate)} max={100} suffix="%" />
          <div className="flex-1 min-w-0">
            <div className="text-[10px] uppercase tracking-[0.15em] text-secondary mb-1 font-semibold">
              {t('home.advanced.result.citation.rate')} · {data.engine}
            </div>
            <h3 className="text-xl font-bold text-primary mb-3 truncate">{data.domain}</h3>
            <div className="grid grid-cols-3 gap-2.5">
              <StatTile
                label={t('home.advanced.result.citation.questionsAsked')}
                value={data.valid_queries}
                hint={t('home.advanced.result.citation.questionsAskedHint')}
              />
              <StatTile
                label={t('home.advanced.result.citation.cited')}
                value={data.cited_queries}
                accent="good"
                hint={t('home.advanced.result.citation.citedHint', { total: data.valid_queries })}
              />
              <StatTile
                label={t('home.advanced.result.citation.grade')}
                value={data.grade}
                accent="gradient"
                hint={t('home.advanced.result.citation.overallScore')}
              />
            </div>
          </div>
        </div>
      </div>
      <SectionCard
        title={t('home.advanced.result.citation.perQuery')}
        subtitle={t('home.advanced.result.citation.queriesSuffix', { count: data.queries.length })}
      >
        <ul className="space-y-2">
          {data.queries.map((q, i) => {
            const status = q.error ? 'error' : q.cited ? 'cited' : 'not';
            const statusClass =
              status === 'cited'
                ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
                : status === 'error'
                  ? 'bg-amber-500/15 text-amber-400 border-amber-500/30'
                  : 'bg-rose-500/15 text-rose-400 border-rose-500/30';
            const statusLabel =
              status === 'cited'
                ? t('home.advanced.result.citation.statusCited')
                : status === 'error'
                  ? t('home.advanced.result.citation.statusError')
                  : t('home.advanced.result.citation.statusNot');
            return (
              <li
                key={i}
                className="bg-tertiary border border-border rounded-xl p-3.5 hover:border-border-strong transition-colors"
              >
                <div className="flex items-start justify-between gap-3 mb-1.5">
                  <span className="text-sm text-primary flex-1 leading-snug">"{q.query}"</span>
                  <span
                    className={`text-[10px] font-bold uppercase tracking-wider px-2 py-1 rounded-full border whitespace-nowrap ${statusClass}`}
                  >
                    {statusLabel}
                  </span>
                </div>
                {q.citations.length > 0 && (
                  <ul className="mt-2 pl-3 border-l-2 border-emerald-500/30 space-y-0.5">
                    {q.citations.slice(0, 3).map((c, j) => (
                      <li
                        key={j}
                        className="text-xs text-secondary font-mono truncate"
                        title={c}
                      >
                        → {c}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      </SectionCard>
    </>
  );
}

// --- Visibility ---
function VisibilityResult({ data }: { data: AiVisibilityResponse }) {
  const { t } = useTranslation();
  const categories = useMemo(
    () => [
      { label: t('home.advanced.result.visibility.categories.visibility'), value: data.scores.visibility },
      { label: t('home.advanced.result.visibility.categories.entity'), value: data.scores.entity },
      { label: t('home.advanced.result.visibility.categories.competitor'), value: data.scores.competitor },
      { label: t('home.advanced.result.visibility.categories.stability'), value: data.scores.stability },
      { label: t('home.advanced.result.visibility.categories.contentGap'), value: data.scores.content_gap },
    ],
    [data.scores, t],
  );
  const framingTotal = Object.values(data.framings).reduce((a, b) => a + b, 0);
  return (
    <>
      <div className="relative overflow-hidden bg-card border border-border-strong rounded-2xl p-5 sm:p-6 mb-6">
        <div
          className="absolute -top-24 -right-24 w-64 h-64 rounded-full opacity-20 blur-3xl"
          style={{ background: 'linear-gradient(135deg, #06b6d4, #a855f7, #ec4899)' }}
        />
        <div className="relative flex flex-col sm:flex-row sm:items-center gap-5 sm:gap-6 mb-6">
          <MetricRing value={data.total_score} max={data.max_score} />
          <div className="flex-1 min-w-0">
            <div className="text-[10px] uppercase tracking-[0.15em] text-secondary mb-1 font-semibold">
              {t('home.advanced.cards.visibility.title')}
            </div>
            <h3 className="text-xl font-bold text-primary mb-2 truncate">{data.brand}</h3>
            <div className="flex flex-wrap items-center gap-1.5 mb-2">
              <span className="text-[10px] font-bold px-2 py-0.5 rounded-full gradient-bg text-white uppercase tracking-wider">
                {data.grade_label}
              </span>
              {data.engines.map((e) => (
                <span
                  key={e}
                  className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-tertiary border border-border-strong text-secondary"
                >
                  {e}
                </span>
              ))}
            </div>
            <p className="text-xs text-secondary">
              {t('home.advanced.result.visibility.queryBreakdown', { count: data.query_count, runs: data.stability_runs })}
            </p>
          </div>
        </div>
        <div className="relative border-t border-border pt-4">
          {categories.map((c) => (
            <ScoreBar key={c.label} label={c.label} value={c.value} max={20} />
          ))}
        </div>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <SectionCard title={t('home.advanced.result.visibility.perEngineRate')}>
          <ul className="space-y-3">
            {Object.entries(data.per_engine_rates).map(([eng, rate]) => (
              <li key={eng}>
                <div className="flex justify-between mb-1.5">
                  <span className="text-sm text-primary capitalize font-medium">{eng}</span>
                  <span className="text-sm text-primary font-mono tabular-nums">
                    {rate.toFixed(0)}%
                  </span>
                </div>
                <div className="h-2 bg-tertiary rounded-full overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-cyan-400 via-purple-500 to-pink-500 transition-all duration-700"
                    style={{ width: `${rate}%` }}
                  />
                </div>
              </li>
            ))}
          </ul>
        </SectionCard>
        <SectionCard title={t('home.advanced.result.visibility.competitors')}>
          {data.top_competitors.length === 0 ? (
            <p className="text-sm text-secondary">{t('home.advanced.result.visibility.noCompetitors')}</p>
          ) : (
            <ul className="space-y-1.5">
              {data.top_competitors.slice(0, 10).map((c, i) => (
                <li
                  key={c.domain}
                  className="flex items-center justify-between px-3 py-2 rounded-lg bg-tertiary border border-border hover:border-border-strong transition-colors"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="text-[10px] font-mono text-secondary w-5">#{i + 1}</span>
                    <span className="text-sm text-primary truncate font-mono">{c.domain}</span>
                  </div>
                  <span className="text-xs text-accent-primary font-bold tabular-nums whitespace-nowrap">
                    {c.mentions}×
                  </span>
                </li>
              ))}
            </ul>
          )}
        </SectionCard>
        <SectionCard title={t('home.advanced.result.visibility.framings')}>
          <ul className="space-y-2.5">
            {Object.entries(data.framings).map(([f, n]) => {
              const pct = framingTotal > 0 ? (n / framingTotal) * 100 : 0;
              return (
                <li key={f}>
                  <div className="flex justify-between mb-1">
                    <span className="text-xs text-secondary capitalize">
                      {t(`home.advanced.result.entity.framings.${f}`, { defaultValue: f.replace('_', ' ') })}
                    </span>
                    <span className="text-xs text-primary font-mono tabular-nums">{n}</span>
                  </div>
                  <div className="h-1.5 bg-tertiary rounded-full overflow-hidden">
                    <div
                      className="h-full bg-accent-primary/70 transition-all duration-700"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </li>
              );
            })}
          </ul>
        </SectionCard>
        <SectionCard title={t('home.advanced.result.visibility.contentGaps')}>
          {data.content_gaps.length === 0 ? (
            <div className="flex items-center gap-2 text-sm text-emerald-400">
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M20 6L9 17l-5-5" />
              </svg>
              {t('home.advanced.result.visibility.noGaps')}
            </div>
          ) : (
            <ul className="space-y-1.5">
              {data.content_gaps.slice(0, 10).map((g, i) => (
                <li
                  key={i}
                  className="text-xs text-amber-400 px-2.5 py-1.5 rounded-lg bg-amber-500/5 border border-amber-500/20"
                >
                  • {g}
                </li>
              ))}
            </ul>
          )}
        </SectionCard>
      </div>
    </>
  );
}

// --- Entity ---
// Map backend-emitted English score-bar labels to frontend i18n slugs.
// Kept here rather than in i18n so we can fall back to the raw label when the
// backend adds a new one we haven't translated yet.
const ENTITY_SCORE_SLUG: Record<string, string> = {
  'Entity Recognition': 'entityRecognition',
  'Entity Clarity': 'entityClarity',
  'Category Association': 'categoryAssociation',
  'Competitive Position': 'competitivePosition',
  'Sentiment & Framing': 'sentimentFraming',
  'Content Gap': 'contentGap',
  'Knowledge Graph': 'knowledgeGraph',
  'Platform Footprint': 'platformFootprint',
};

function EntityResult({ data }: { data: EntityAuditResponse }) {
  const { t } = useTranslation();
  const totalPlatforms = data.platforms.found.length + data.platforms.not_found.length;
  const kgItems = [
    { key: t('home.advanced.result.entity.kgWikipedia'), found: data.knowledge_graph.wikipedia, sub: '' },
    {
      key: t('home.advanced.result.entity.kgWikidata'),
      found: data.knowledge_graph.wikidata,
      sub: data.knowledge_graph.wikidata_id || '',
    },
    { key: t('home.advanced.result.entity.kgGoogleKg'), found: data.knowledge_graph.google_kg, sub: '' },
    { key: t('home.advanced.result.entity.kgBaiduBaike'), found: data.knowledge_graph.baidu_baike, sub: '' },
  ];
  return (
    <>
      <div className="relative overflow-hidden bg-card border border-border-strong rounded-2xl p-5 sm:p-6 mb-6">
        <div
          className="absolute -top-24 -right-24 w-64 h-64 rounded-full opacity-20 blur-3xl"
          style={{ background: 'linear-gradient(135deg, #ec4899, #f59e0b)' }}
        />
        <div className="relative flex flex-col sm:flex-row sm:items-center gap-5 sm:gap-6 mb-6">
          <MetricRing value={data.total_score} max={data.max_score} />
          <div className="flex-1 min-w-0">
            <div className="text-[10px] uppercase tracking-[0.15em] text-secondary mb-1 font-semibold">
              {t('home.advanced.cards.entity.title')}
            </div>
            <h3 className="text-xl font-bold text-primary mb-2 truncate">{data.entity}</h3>
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-pink-500/15 text-pink-400 border border-pink-500/30">
                {t(`home.advanced.header.entityType.${data.entity_type}`, { defaultValue: data.entity_type })}
              </span>
              <span className="text-[10px] font-bold px-2 py-0.5 rounded-full gradient-bg text-white uppercase tracking-wider">
                {t('home.advanced.result.entity.gradePrefix')} {data.grade}
              </span>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded-full border border-border-strong text-secondary">
                {data.percent}%
              </span>
            </div>
          </div>
        </div>
        <div className="relative border-t border-border pt-4">
          {Object.entries(data.scores).map(([name, v]) => {
            const slug = ENTITY_SCORE_SLUG[name];
            const label = slug
              ? t(`home.advanced.result.entity.scoreLabels.${slug}`, { defaultValue: name })
              : name;
            return <ScoreBar key={name} label={label} value={v} max={20} />;
          })}
        </div>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <SectionCard title={t('home.advanced.result.entity.kgTitle')}>
          <ul className="space-y-2">
            {kgItems.map((kg) => (
              <li
                key={kg.key}
                className="flex items-center justify-between px-3 py-2.5 rounded-xl bg-tertiary border border-border"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <div
                    className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${kg.found
                        ? 'bg-emerald-500/15 border border-emerald-500/30 text-emerald-400'
                        : 'bg-rose-500/10 border border-rose-500/30 text-rose-400'
                      }`}
                  >
                    {kg.found ? (
                      <svg
                        width="16"
                        height="16"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2.5"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <path d="M20 6L9 17l-5-5" />
                      </svg>
                    ) : (
                      <svg
                        width="16"
                        height="16"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2.5"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <line x1="18" y1="6" x2="6" y2="18" />
                        <line x1="6" y1="6" x2="18" y2="18" />
                      </svg>
                    )}
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm text-primary font-medium">{kg.key}</div>
                    {kg.sub && (
                      <div className="text-[10px] text-secondary font-mono truncate">
                        {kg.sub}
                      </div>
                    )}
                  </div>
                </div>
                <span
                  className={`text-[10px] font-bold uppercase tracking-wider ${kg.found ? 'text-emerald-400' : 'text-rose-400'
                    }`}
                >
                  {kg.found
                    ? t('home.advanced.result.entity.found')
                    : t('home.advanced.result.entity.missing')}
                </span>
              </li>
            ))}
          </ul>
        </SectionCard>
        <SectionCard title={t('home.advanced.result.entity.platforms')} subtitle={`${data.platforms.found.length}/${totalPlatforms}`}>
          <div className="flex flex-wrap gap-1.5">
            {data.platforms.found.map((p) => (
              <span
                key={p}
                className="text-xs bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 rounded-full px-2.5 py-1 font-medium"
              >
                ✓ {p}
              </span>
            ))}
            {data.platforms.not_found.map((p) => (
              <span
                key={p}
                className="text-xs bg-rose-500/10 text-rose-400 border border-rose-500/30 rounded-full px-2.5 py-1 font-medium"
              >
                ✕ {p}
              </span>
            ))}
          </div>
        </SectionCard>
        <SectionCard title={t('home.advanced.result.entity.sentimentTitle')}>
          <div className="space-y-3">
            <div className="flex items-center justify-between px-3 py-2.5 rounded-lg bg-tertiary border border-border">
              <span className="text-[10px] text-secondary uppercase tracking-wider font-semibold">
                {t('home.advanced.result.entity.overallSentiment')}
              </span>
              <span className="text-sm text-primary font-bold">
                {t(`home.advanced.result.entity.sentiments.${data.per_engine ? Object.values(data.per_engine).find(d => d.recognized)?.sentiment || data.sentiment : data.sentiment}`, { defaultValue: data.sentiment || 'unknown' })}
              </span>
            </div>
            <div className="flex items-center justify-between px-3 py-2.5 rounded-lg bg-tertiary border border-border">
              <span className="text-[10px] text-secondary uppercase tracking-wider font-semibold">
                {t('home.advanced.result.entity.bestFraming')}
              </span>
              <span className="text-sm text-primary font-bold">
                {t(`home.advanced.result.entity.framings.${data.per_engine ? Object.values(data.per_engine).find(d => d.recognized)?.framing || data.best_framing : data.best_framing}`, { defaultValue: (data.best_framing || 'unknown').replace('_', ' ') })}
              </span>
            </div>
            <div className="flex items-center justify-between px-3 py-2.5 rounded-lg bg-tertiary border border-border">
              <span className="text-[10px] text-secondary uppercase tracking-wider font-semibold">
                {t('home.advanced.result.entity.recognitionRate')}
              </span>
              <span className="text-sm gradient-text font-bold tabular-nums">
                {data.recognition_rate}%
              </span>
            </div>
          </div>
        </SectionCard>
        <SectionCard title={t('home.advanced.result.entity.contentGaps')}>
          {data.content_gaps.length === 0 ? (
            <div className="flex items-center gap-2 text-sm text-emerald-400">
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M20 6L9 17l-5-5" />
              </svg>
              {t('home.advanced.result.entity.noGaps')}
            </div>
          ) : (
            <ul className="space-y-1.5">
              {data.content_gaps.map((g, i) => (
                <li
                  key={i}
                  className="text-xs text-rose-500 px-2.5 py-1.5 rounded-lg bg-rose-500/5 border border-rose-500/20"
                >
                  • {g}
                </li>
              ))}
            </ul>
          )}
        </SectionCard>
      </div>
      {data.source_trace && data.source_preference && (
        <SectionCard
          title={t('home.advanced.result.entity.sourceAnalysis')}
          subtitle={
            data.source_trace.total_sources > 0
              ? t('home.advanced.result.entity.sourceStats', {
                  sources: data.source_trace.total_sources,
                  citations: data.source_trace.total_citations,
                })
              : undefined
          }
        >
          <SourceAnalysisPanel
            sourceTrace={data.source_trace}
            sourcePreference={data.source_preference}
            engines={data.engines_used || []}
          />
        </SectionCard>
      )}
    </>
  );
}
