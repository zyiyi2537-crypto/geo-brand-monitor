import { useState, type ReactNode } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useContactModal } from '../components/ContactModalContext';
import { useAuthModal } from '../contexts/AuthModalContext';
import { useTierModal } from '../components/TierModalContext';
import { useMembership } from '../hooks/useMembership';
import { PageHead } from '../components/PageHead';
import { TestimonialsCarousel } from '../components/TestimonialsCarousel';
import { validateUrl, normalizeUrl } from '../utils/validateUrl';

type AdvancedKey = 'aeo' | 'compare' | 'crawlTest' | 'authority' | 'citation' | 'visibility' | 'entity';
type CardKey = AdvancedKey | 'sentiment';

const advancedCards: { key: CardKey; icon: ReactNode; isNew?: boolean }[] = [
  {
    key: 'aeo',
    icon: (
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
    ),
  },
  {
    key: 'compare',
    icon: (
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
    ),
  },
  {
    key: 'crawlTest',
    icon: (
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
    ),
  },
  {
    key: 'authority',
    icon: (
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
    ),
  },
  {
    key: 'citation',
    icon: (
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 8h10M7 12h4m1 8l-4-4H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-3l-4 4z" />
    ),
  },
  {
    key: 'visibility',
    icon: (
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
    ),
  },
  {
    key: 'entity',
    icon: (
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
    ),
  },
  {
    key: 'sentiment',
    isNew: true,
    icon: (
      <>
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064" />
        <circle cx="12" cy="12" r="9" strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} />
      </>
    ),
  },
];

// Pipeline step icons (Heroicons outline style, single path each).
// Indexed by step position 0–7, ordered to match home.pipeline.steps i18n.
const pipelineIconPaths: string[] = [
  // 01 种子提示 — sparkles
  'M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z',
  // 02 意图扩展 — share / branching nodes
  'M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z',
  // 03 提示聚类 — users group
  'M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z',
  // 04 内容生成 — pencil + paper
  'M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z',
  // 05 媒介分发 — wifi broadcast arc
  'M8.111 16.404a5.5 5.5 0 017.778 0M12 20h.01m-7.08-7.071c3.904-3.905 10.236-3.905 14.141 0M1.394 9.393c6.05-6.05 15.858-6.05 21.908 0',
  // 06 引擎抓取 — magnifier search
  'M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z',
  // 07 遥测采集 — chart bars
  'M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z',
  // 08 强化闭环 — refresh / cyclic
  'M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15',
];

export function Home() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const metaKey = location.pathname === '/checker' ? 'checker' : 'home';
  const isEn = (i18n.language || 'en').startsWith('en');
  const { isLoggedIn, isUnlocked } = useMembership();
  const { openContact } = useContactModal();
  const { openAuthModal } = useAuthModal();
  const { openTierModal } = useTierModal();
  const [url, setUrl] = useState('');
  const [error, setError] = useState('');

  // Home doesn't call the API itself — it hands the URL off to the Result
  // page and lets that page own the request lifecycle. This avoids the
  // 499 cascade we saw when users hit back/refresh while Home was still
  // awaiting a response (component unmount → axios cancel → nginx 499).
  // Server errors (quota, upstream failures, timeouts) now surface in
  // Result's rerun-error band, not here.
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!url.trim()) {
      setError(t('home.error.empty'));
      return;
    }
    if (!validateUrl(url)) {
      setError(t('home.error.invalid'));
      return;
    }

    navigate('/result', { state: { pendingUrl: normalizeUrl(url) } });
  };

  const handleAdvancedClick = (key: CardKey) => {
    // 舆情监测是订阅式服务,跳工作台而不是单次检测的 Result 页
    if (key === 'sentiment') {
      if (!isLoggedIn) {
        openAuthModal('login');
        return;
      }
      if (!isUnlocked) {
        openTierModal();
        return;
      }
      navigate('/sentiment');
      return;
    }
    if (!isLoggedIn || !isUnlocked) {
      openTierModal();
      return;
    }
    // Member — jump straight to the Result page in "empty advanced" mode:
    // the rerun bar is centered, the dropdown is pre-selected to `key`, and
    // running it renders the result inline (no /advanced/{mode} hop).
    const initialUrl = url && validateUrl(url) ? normalizeUrl(url) : undefined;
    navigate('/result', { state: { initialMode: key, initialUrl } });
  };

  return (
    <div className="min-h-screen grid-background">
      <PageHead titleKey={`pageMeta.${metaKey}.title`} descriptionKey={`pageMeta.${metaKey}.description`} />
      <div className="bg-glow bg-glow-1"></div>
      <div className="bg-glow bg-glow-2"></div>
      <div className="bg-glow bg-glow-3"></div>

      <main className="flex-1 px-4 pt-10 pb-12 sm:pt-14 sm:pb-28 relative z-10">
        <div className="w-full max-w-6xl mx-auto animate-fade-in">
          <section className="hero text-center">
            <h1
              className={`text-3xl sm:text-5xl lg:text-6xl font-bold ${isEn ? 'italic' : ''} gradient-text mb-6 animate-fade-in leading-[1.05] tracking-tight`}
            >
              {t('home.slogan.cta')}
            </h1>

            <p className="text-2xl sm:text-3xl lg:text-4xl font-bold mb-6 leading-tight tracking-tight animate-slide-up text-center">
              <span className="gradient-text">{t('home.title')}</span>
            </p>

            <p
              className="text-base sm:text-lg text-secondary max-w-2xl mx-auto leading-relaxed animate-slide-up text-center"
              style={{ animationDelay: '0.1s' }}
            >
              {t('home.description')}
            </p>

            <div className="transition-all duration-300 animate-scale-in max-w-2xl mx-auto mt-8 sm:mt-10">
              <form id="geo-form" onSubmit={handleSubmit}>
                <div className="flex flex-col sm:flex-row sm:items-center bg-surface border border-soft rounded-2xl sm:rounded-full p-1.5 shadow-glow transition-shadow gap-1.5 sm:gap-0">
                  <input
                    type="text"
                    id="url"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    placeholder={t('home.placeholder')}
                    className="flex-1 py-3 px-4 sm:px-5 text-sm sm:text-base bg-transparent focus:outline-none text-primary border-none min-w-0"
                    style={{ color: 'var(--text-primary)' }}
                  />
                  <button
                    type="submit"
                    className="btn-solid px-6 py-3 font-semibold flex items-center justify-center rounded-xl sm:rounded-full disabled:opacity-60 text-sm sm:text-base"
                  >
                    {t('home.button')}
                  </button>
                </div>

                {error && (
                  <div
                    className="mt-4 rounded-xl p-4 flex items-start gap-3 animate-fade-in"
                    style={{
                      background: 'rgba(239, 68, 68, 0.08)',
                      border: '1px solid rgba(239, 68, 68, 0.25)',
                    }}
                  >
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      className="h-5 w-5 text-rose-500 flex-shrink-0 mt-0.5"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-.633-1.964-.633-2.732 0L3.34 16c-.77 1.333.192 3 1.732 3z"
                      />
                    </svg>
                    <span className="text-sm font-medium" style={{ color: '#ef4444' }}>{error}</span>
                  </div>
                )}
              </form>

              <div className="mt-8 text-center">
                <p className="text-sm text-muted font-medium">{t('home.poweredBy')}</p>
                <p className="mt-2">
                  <button
                    type="button"
                    onClick={openContact}
                    className="text-sm font-medium underline underline-offset-4 transition-colors duration-200 bg-transparent border-none cursor-pointer"
                    style={{ color: 'var(--text-primary)', textDecorationColor: 'var(--border-strong)' }}
                  >
                    {t('home.contactLink')}
                  </button>
                </p>
              </div>
            </div>
          </section>

          {/* 8-step GEO Automation Pipeline — monochrome, matches page B&W style */}
          <section className="mt-10 sm:mt-30">
            <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4 mb-6 sm:mb-10">
              <div>
                <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-surface border border-soft shadow-glow mb-3">
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-3.5 w-3.5 text-secondary"
                       fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                          d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
                  </svg>
                  <span className="text-xs font-semibold text-secondary">
                    {t('home.pipeline.badge')}
                  </span>
                </div>
                <h2 className="text-2xl sm:text-3xl font-bold mb-2 tracking-tight">
                  <span className="gradient-text">{t('home.pipeline.title')}</span>
                </h2>
                <p className="text-secondary text-sm sm:text-base max-w-2xl">
                  {t('home.pipeline.subtitle')}
                </p>
              </div>
            </div>

            {/* Phase breadcrumb — text-only, no color encoding */}
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 mb-6 sm:mb-8 text-xs sm:text-sm">
              {(t('home.pipeline.phases', { returnObjects: true }) as { id: string; label: string }[]).map(
                (p, i, arr) => (
                  <span key={p.id} className="inline-flex items-center gap-2">
                    <span className="font-semibold tracking-wide text-primary">{p.label}</span>
                    {i < arr.length - 1 && (
                      <svg className="w-3.5 h-3.5 text-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                      </svg>
                    )}
                  </span>
                ),
              )}
            </div>

            {/* 8-step grid — uniform monochrome cards, Advanced-Detection style */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
              {(() => {
                const phases = t('home.pipeline.phases', { returnObjects: true }) as {
                  id: string;
                  label: string;
                }[];
                const phaseLabel = (id: string) =>
                  phases.find((p) => p.id === id)?.label ?? id;
                const steps = t('home.pipeline.steps', { returnObjects: true }) as {
                  id: string;
                  phase: string;
                  title: string;
                  desc: string;
                  output: string;
                }[];
                return steps.map((step, idx) => {
                  const iconPath = pipelineIconPaths[idx];
                  return (
                    <div
                      key={step.id}
                      className="card p-5 sm:p-6 hover:-translate-y-0.5 transition-all duration-200 flex flex-col h-full"
                    >
                      <div className="flex items-center justify-between mb-4">
                        <div className="icon-tile w-10 h-10 rounded-xl flex items-center justify-center">
                          <svg
                            xmlns="http://www.w3.org/2000/svg"
                            className="w-5 h-5"
                            fill="none"
                            viewBox="0 0 24 24"
                            stroke="currentColor"
                            strokeWidth={1.8}
                          >
                            <path strokeLinecap="round" strokeLinejoin="round" d={iconPath} />
                          </svg>
                        </div>
                        <span className="text-xs font-semibold tracking-[0.12em] text-muted">
                          {step.id} · {phaseLabel(step.phase)}
                        </span>
                      </div>

                      <div className="flex-1">
                        <h3 className="text-sm sm:text-base font-bold text-primary leading-tight mb-1.5">
                          {step.title}
                        </h3>
                        <p className="text-xs sm:text-sm text-secondary leading-relaxed m-0">
                          {step.desc}
                        </p>
                      </div>

                      <div
                        className="mt-3 sm:mt-4 pt-3 border-t text-[11px] leading-relaxed text-muted"
                        style={{ borderColor: 'var(--border-color)' }}
                      >
                        {step.output}
                      </div>
                    </div>
                  );
                });
              })()}
            </div>
          </section>

          {/* Brand Growth Engine Section — section header + 单卡(对仗「高级检测能力」结构) */}
          <section className="mt-10 sm:mt-30">
            <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4 mb-6 sm:mb-10">
              <div>
                <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-surface border border-soft shadow-glow mb-3">
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-3.5 w-3.5 text-secondary"
                       fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                          d="M13 10V3L4 14h7v7l9-11h-7z" />
                  </svg>
                  <span className="text-xs font-semibold text-secondary">
                    {t('home.brandGrowth.badge')}
                  </span>
                </div>
                <h2 className="text-2xl sm:text-3xl font-bold mb-2 tracking-tight">
                  <span className="gradient-text">{t('home.brandGrowth.title')}</span>
                </h2>
                <p className="text-secondary text-sm sm:text-base max-w-2xl">
                  {t('home.brandGrowth.subtitle')}
                </p>
              </div>
            </div>

            <div
              role="button"
              onClick={() => {
                if (!isLoggedIn) { openAuthModal('login'); return; }
                navigate('/dashboard');
              }}
              className="card p-6 sm:p-8 hover:-translate-y-0.5 transition-all duration-200 cursor-pointer text-left flex flex-col sm:flex-row sm:items-center gap-6"
            >
              <div className="icon-tile w-14 h-14 sm:w-16 sm:h-16 rounded-2xl flex items-center justify-center flex-shrink-0">
                <svg xmlns="http://www.w3.org/2000/svg" className="h-7 w-7 sm:h-8 sm:w-8"
                     fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                        d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-secondary text-sm sm:text-base leading-relaxed">
                  {t('home.brandGrowth.cardDesc')}
                </p>
              </div>
              <div className="shrink-0">
                <span className="btn-solid inline-flex items-center gap-1.5 rounded-full py-2.5 px-5 text-sm font-semibold whitespace-nowrap">
                  {isLoggedIn ? t('home.brandGrowth.cta') : t('home.brandGrowth.ctaUnauth')}
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                  </svg>
                </span>
              </div>
            </div>
          </section>

          {/* Advanced Detection Section */}
          <section className="mt-10 sm:mt-30">
            <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4 mb-6 sm:mb-10">
              <div>
                <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-surface border border-soft shadow-glow mb-3">
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    className="h-3.5 w-3.5 text-secondary"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"
                    />
                  </svg>
                  <span className="text-xs font-semibold text-secondary">
                    {t('home.advanced.badge')}
                  </span>
                </div>
                <h2 className="text-2xl sm:text-3xl font-bold mb-2 tracking-tight">
                  <span className="gradient-text">{t('home.advanced.title')}</span>
                </h2>
                <p className="text-secondary text-sm sm:text-base max-w-2xl">
                  {t('home.advanced.subtitle')}
                </p>
              </div>
              {!isUnlocked && (
                <button
                  type="button"
                  onClick={openTierModal}
                  className="btn-solid self-start sm:self-end rounded-full py-2.5 px-5 text-sm font-semibold transition-all duration-200 whitespace-nowrap"
                >
                  {t('home.advanced.upgrade')}
                </button>
              )}
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 sm:gap-6">
              {advancedCards.map(({ key, icon, isNew }) => (
                <div
                  role="button"
                  key={key}
                  onClick={() => handleAdvancedClick(key)}
                  className="group flex gap-4 relative text-left card p-6 hover:-translate-y-0.5"
                >
                  {isNew && (
                    <div
                      className="absolute top-4 right-4 px-2 py-0.5 rounded-full text-[10px] font-bold tracking-wide"
                      style={{
                        background: 'linear-gradient(90deg, #7c3aed, #ec4899)',
                        color: '#ffffff',
                      }}
                    >
                      NEW
                    </div>
                  )}
                  {!isNew && !isUnlocked && (
                    <div className="absolute top-4 right-4 w-8 h-8 rounded-full flex items-center justify-center bg-surface border border-soft">
                      <svg
                        xmlns="http://www.w3.org/2000/svg"
                        className="h-4 w-4 text-secondary"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2}
                          d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"
                        />
                      </svg>
                    </div>
                  )}
                  <div className="icon-tile w-12 h-12 rounded-xl flex items-center justify-center mb-5 group-hover:scale-105 transition-transform duration-200 flex-shrink-0">
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      className="h-6 w-6"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                    >
                      {icon}
                    </svg>
                  </div>
                  <div className='flex-1'>
                    <h3 className="text-lg font-bold mb-2 text-primary">
                      {t(`home.advanced.cards.${key}.title`)}
                    </h3>
                    <p className="text-sm text-secondary leading-relaxed m-0">
                      {t(`home.advanced.cards.${key}.desc`)}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* AI Engines Covered — 10 大引擎,2×5 网格(放在 8 步工作流下面) */}
          <section className="mt-10 sm:mt-30">
            <div className="text-center mb-6 sm:mb-8">
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-surface border border-soft shadow-glow mb-3">
                <svg xmlns="http://www.w3.org/2000/svg"
                     className="h-3.5 w-3.5 text-secondary"
                     fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                        d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                </svg>
                <span className="text-xs font-semibold text-secondary">
                  {t('home.engines.badge')}
                </span>
              </div>
              <h2 className="text-2xl sm:text-3xl font-bold mb-2 tracking-tight">
                <span className="gradient-text">{t('home.engines.title')}</span>
              </h2>
              <p className="text-secondary text-sm sm:text-base max-w-2xl mx-auto">
                {t('home.engines.subtitle')}
              </p>
            </div>
            {/* 2 行 × 5 列(响应式:mobile 2 列、tablet 3 / 4 列、desktop 5 列).
                每张卡居中纵向布局:大 logo 在上、引擎名在下;参考截图风格. */}
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3 sm:gap-4 max-w-5xl mx-auto">
              {(t('home.engines.items', { returnObjects: true }) as {
                name: string; sub: string; slug: string; ext?: string;
              }[]).map((eng, idx) => (
                <div key={idx}
                     className="rounded-2xl flex flex-col items-center justify-center text-center gap-3 px-3 py-6 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md"
                     style={{
                       background: '#ffffff',
                       boxShadow: '0 1px 2px rgba(0,0,0,0.04)',
                       border: '1px solid rgba(0,0,0,0.08)',
                     }}>
                  <div className="shrink-0 rounded-xl overflow-hidden flex items-center justify-center"
                       style={{ width: 56, height: 56, background: '#fff', border: '1px solid rgba(0,0,0,0.06)' }}>
                    <img src={`/image/engines/${eng.slug}.${eng.ext || 'png'}`} alt={eng.name}
                         width={48} height={48}
                         className="object-contain select-none"
                         style={{ width: 48, height: 48 }}
                         draggable={false} />
                  </div>
                  <div className="min-w-0 w-full">
                    <div className="text-sm sm:text-base font-semibold truncate" style={{ color: '#141418' }}>
                      {eng.name}
                    </div>
                    <div className="text-[10px] sm:text-[11px] mt-0.5 truncate" style={{ color: '#94939d' }}>
                      {eng.sub}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* Partners — 与 8 步工作流同栏宽 (max-w-6xl 继承自 main),按 section 节奏间距 */}
          <section className="mt-10 sm:mt-30">
            <div className="text-center mb-8 sm:mb-10">
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-surface border border-soft shadow-glow">
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  className="h-3.5 w-3.5 text-secondary"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z"
                  />
                </svg>
                <span className="text-xs font-semibold text-secondary">
                  {t('home.partners.badge')}
                </span>
              </div>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 sm:gap-4">
              {(t('home.partners.items', { returnObjects: true }) as {
                name: string;
                sub: string;
                logo: string;
                tagline: string;
                // 可选缩放(原始 logo 留白多时调大,默认 1).只影响视觉,不改容器尺寸
                scale?: number;
              }[]).map((item, idx) => (
                <div
                  key={idx}
                  className="rounded-xl flex items-center justify-center px-4 transition-transform duration-200 hover:-translate-y-0.5"
                  style={{
                    background: '#ffffff',
                    height: '88px',
                    boxShadow: '0 1px 2px rgba(0,0,0,0.04)',
                  }}
                >
                  {item.logo ? (
                    <img
                      src={item.logo}
                      alt={`${item.name} · ${item.sub}`}
                      loading="lazy"
                      draggable={false}
                      className="max-h-12 sm:max-h-14 max-w-full w-auto object-contain select-none"
                      style={item.scale && item.scale !== 1
                        ? { transform: `scale(${item.scale})`, transformOrigin: 'center' }
                        : undefined}
                    />
                  ) : (
                    <div className="text-center select-none whitespace-nowrap" style={{ color: '#141418' }}>
                      <span className="text-base sm:text-lg font-bold tracking-tight">
                        {item.name}
                      </span>
                      <span className="hidden sm:inline text-xs ml-2 tracking-wide" style={{ color: '#666' }}>
                        {item.sub}
                      </span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>

          {/* 用户评价 —— 紧跟合作伙伴,无缝横向轮播 */}
          <TestimonialsCarousel />
        </div>
      </main>

      {/* Slogan Banner */}
      <section
        className="relative z-10 px-4 py-16 sm:py-24"
        style={{ background: '#141418' }}
      >
        <div className="w-full max-w-5xl mx-auto">
          {/* Logo:图标 SVG 默认黑,深色 banner 上 brightness-0 invert 翻白;文字直接白色 CSS 渲染 */}
          <div className="flex items-center gap-3 mb-10 select-none">
            <img
              src="/image/logo.svg"
              alt=""
              aria-hidden="true"
              className="h-12 sm:h-14 w-auto brightness-0 invert"
              draggable={false}
            />
            <span className="text-3xl sm:text-4xl font-black tracking-tight text-white">
              Vigilath
            </span>
          </div>


          {/* Heading */}
          <h2 className="text-2xl sm:text-3xl lg:text-4xl font-bold mb-3 text-white">
            {t('home.slogan.sectionTitle')}
          </h2>

          {/* Subtitle */}
          <p className="text-base sm:text-lg italic mb-10" style={{ color: 'rgba(255,255,255,0.55)' }}>
            {t('home.slogan.title')}
          </p>

          {/* 2x2 Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-12">
            {(t('home.slogan.points', { returnObjects: true }) as string[]).map((point, idx) => {
              const sep = point.indexOf(' — ');
              const title = sep !== -1 ? point.slice(0, sep) : point;
              const desc = sep !== -1 ? point.slice(sep + 3) : '';
              return (
                <div
                  key={idx}
                  className="rounded-xl p-5 sm:p-6"
                  style={{ background: 'rgba(255,255,255,0.95)', color: '#141418' }}
                >
                  <h3 className="font-bold text-sm sm:text-base mb-1.5" style={{ color: '#141418' }}>{title}</h3>
                  {desc && <p className="text-xs sm:text-sm leading-relaxed" style={{ color: '#555' }}>{desc}</p>}
                </div>
              );
            })}
          </div>

          {/* CTA Row */}
          <div className="flex justify-center sm:justify-end">
            <button
              type="button"
              onClick={openContact}
              className="inline-flex items-center gap-3 px-6 py-3 rounded-full border-2 border-white text-white font-semibold text-sm sm:text-base transition-colors duration-200 hover:bg-white hover:text-black flex-shrink-0"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <circle cx="12" cy="12" r="10" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 8l4 4m0 0l-4 4m4-4H8" />
              </svg>
              {t('home.slogan.contactSales')}
            </button>
          </div>
        </div>
      </section>

    </div>
  );
}
