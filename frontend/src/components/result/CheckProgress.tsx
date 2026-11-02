import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { RerunMode } from './rerunModes';

// Estimated per-stage durations (seconds). The timer walks through these
// weights to advance the visible "active stage" so the user sees real motion
// instead of a static spinner. Weights are best-guess based on observed
// latencies — if the real API returns earlier, the overlay unmounts; if it
// takes longer, the last stage parks with an "almost done" hint.
const STAGE_WEIGHTS: Record<RerunMode, number[]> = {
  default:    [3, 4, 5, 5, 6, 6, 5],
  aeo:        [4, 6, 8, 8, 6, 5],
  compare:    [30, 60, 120, 120, 60],
  crawlTest:  [3, 5, 6, 6, 4],
  authority:  [4, 6, 7, 7, 6],
  citation:   [4, 8, 8, 6],
  visibility: [5, 10, 10, 10, 8, 6],
  entity:     [5, 8, 8, 8, 8, 6, 6],
};

const STAGE_KEYS: Record<RerunMode, string[]> = {
  aeo: [
    'result.progress.stages.default.fetch',
    'result.progress.stages.default.protocols',
    'result.progress.stages.default.structured',
    'result.progress.stages.default.content',
    'result.progress.stages.default.authority',
    'result.progress.stages.default.finalize',
  ],
  default: [
    'result.progress.stages.default.fetch',
    'result.progress.stages.default.protocols',
    'result.progress.stages.default.structured',
    'result.progress.stages.default.content',
    'result.progress.stages.default.technical',
    'result.progress.stages.default.authority',
    'result.progress.stages.default.finalize',
  ],
  compare: [
    'result.progress.stages.compare.fetch',
    'result.progress.stages.compare.parse',
    'result.progress.stages.compare.score',
    'result.progress.stages.compare.diff',
    'result.progress.stages.compare.finalize',
  ],
  crawlTest: [
    'result.progress.stages.crawlTest.robots',
    'result.progress.stages.crawlTest.probe',
    'result.progress.stages.crawlTest.waf',
    'result.progress.stages.crawlTest.commonCrawl',
    'result.progress.stages.crawlTest.finalize',
  ],
  authority: [
    'result.progress.stages.authority.github',
    'result.progress.stages.authority.pkg',
    'result.progress.stages.authority.wiki',
    'result.progress.stages.authority.social',
    'result.progress.stages.authority.finalize',
  ],
  citation: [
    'result.progress.stages.citation.prepare',
    'result.progress.stages.citation.perplexity',
    'result.progress.stages.citation.parseCites',
    'result.progress.stages.citation.finalize',
  ],
  visibility: [
    'result.progress.stages.visibility.prepare',
    'result.progress.stages.visibility.chatgpt',
    'result.progress.stages.visibility.perplexity',
    'result.progress.stages.visibility.claude',
    'result.progress.stages.visibility.classify',
    'result.progress.stages.visibility.finalize',
  ],
  entity: [
    'result.progress.stages.entity.wiki',
    'result.progress.stages.entity.wikidata',
    'result.progress.stages.entity.platforms',
    'result.progress.stages.entity.llm',
    'result.progress.stages.entity.sentiment',
    'result.progress.stages.entity.gaps',
    'result.progress.stages.entity.finalize',
  ],
};

export function CheckProgress({ mode }: { mode: RerunMode }) {
  const { t } = useTranslation();
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const start = Date.now();
    const id = setInterval(() => {
      setElapsed((Date.now() - start) / 1000);
    }, 250);
    return () => clearInterval(id);
  }, []);

  const weights = STAGE_WEIGHTS[mode];
  const keys = STAGE_KEYS[mode];
  const total = weights.reduce((a, b) => a + b, 0);

  let cumul = 0;
  let currentIdx = keys.length - 1;
  for (let i = 0; i < keys.length; i++) {
    cumul += weights[i];
    if (elapsed < cumul) {
      currentIdx = i;
      break;
    }
  }
  // Cap bar at 95% — we only hit 100% when the real response lands and the
  // overlay unmounts. Otherwise the bar appears "stuck" at the end for slow
  // APIs, which feels worse than a bar that keeps creeping forward.
  const percent = Math.min(95, Math.round((elapsed / total) * 95));
  const overran = elapsed >= total;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 backdrop-blur-sm animate-fade-in"
      style={{ background: 'rgba(0, 0, 0, 0.6)' }}
      role="dialog"
      aria-modal="true"
      aria-live="polite"
    >
      <div className="w-full max-w-md bg-surface border border-soft rounded-2xl p-6 sm:p-7 shadow-2xl">
        <div className="text-center mb-5">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-surface-hover border border-soft mb-3">
            <svg
              className="animate-spin h-6 w-6"
              style={{ color: 'var(--accent-primary)' }}
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
            >
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
              />
            </svg>
          </div>
          <h3 className="text-lg font-bold tracking-tight">
            <span className="gradient-text">{t('result.progress.title')}</span>
          </h3>
          <p className="text-xs text-secondary mt-1">
            {t(`result.progress.subtitle.${mode}`)}
          </p>
        </div>

        {/* Circular ring progress */}
        <div className="flex justify-center mb-5">
          <svg width="80" height="80" viewBox="0 0 80 80" className="transform -rotate-90">
            <defs>
              <linearGradient id="ring-grad" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stopColor="var(--accent-primary, #06b6d4)" />
                <stop offset="100%" stopColor="var(--accent-secondary, #3b82f6)" />
              </linearGradient>
            </defs>
            <circle
              cx="40" cy="40" r="34"
              fill="none"
              stroke="var(--surface-hover, rgba(148, 163, 184, 0.15))"
              strokeWidth="6"
            />
            <circle
              cx="40" cy="40" r="34"
              fill="none"
              stroke="url(#ring-grad)"
              strokeWidth="6"
              strokeLinecap="round"
              strokeDasharray={`${2 * Math.PI * 34}`}
              strokeDashoffset={`${2 * Math.PI * 34 * (1 - percent / 100)}`}
              className="transition-all duration-500 ease-out"
            />
            <text
              x="40" y="40"
              textAnchor="middle"
              dominantBaseline="central"
              className="transform rotate-90 origin-center"
              fill="var(--text-primary, #e2e8f0)"
              fontSize="18"
              fontWeight="700"
            >
              {percent}%
            </text>
          </svg>
        </div>

        <ul className="space-y-2.5">
          {keys.map((key, i) => {
            const done = i < currentIdx;
            const active = i === currentIdx;
            return (
              <li key={key} className="flex items-center gap-3 text-sm">
                <span className="flex-shrink-0 w-5 h-5 flex items-center justify-center">
                  {done ? (
                    <svg viewBox="0 0 20 20" className="w-5 h-5 text-emerald-500" fill="currentColor">
                      <path d="M16.7 5.3a1 1 0 010 1.4l-8 8a1 1 0 01-1.4 0l-4-4a1 1 0 111.4-1.4L8 12.59l7.3-7.3a1 1 0 011.4 0z" />
                    </svg>
                  ) : active ? (
                    <svg
                      className="animate-spin w-4 h-4"
                      style={{ color: 'var(--accent-primary)' }}
                      viewBox="0 0 24 24"
                      fill="none"
                    >
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path
                        className="opacity-75"
                        fill="currentColor"
                        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                      />
                    </svg>
                  ) : (
                    <span className="w-2 h-2 rounded-full border border-soft" />
                  )}
                </span>
                <span
                  className={
                    done
                      ? 'text-secondary'
                      : active
                      ? 'text-primary font-semibold'
                      : 'text-muted'
                  }
                >
                  {t(key)}
                </span>
              </li>
            );
          })}
        </ul>

        <div className="mt-5 pt-4 border-t border-soft flex items-center justify-between text-xs">
          <span className="text-muted">
            {t('result.progress.elapsed', { seconds: Math.floor(elapsed) })}
          </span>
          {overran ? (
            <span className="font-semibold" style={{ color: 'var(--accent-primary)' }}>
              {t('result.progress.almostDone')}
            </span>
          ) : (
            <span className="text-muted">{t('result.progress.hint')}</span>
          )}
        </div>
      </div>
    </div>
  );
}
