import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

type Testimonial = {
  name: string;
  role: string;
  text: string;
};

const AUTO_MS = 5500;

function Arrow({ dir, onClick }: { dir: 'prev' | 'next'; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={dir === 'prev' ? 'previous' : 'next'}
      className="shrink-0 h-10 w-10 rounded-full bg-surface border border-soft shadow-glow flex items-center justify-center text-secondary hover:text-primary hover:-translate-y-0.5 transition-all duration-200"
    >
      <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d={dir === 'prev' ? 'M15 19l-7-7 7-7' : 'M9 5l7 7-7 7'}
        />
      </svg>
    </button>
  );
}

export function TestimonialsCarousel() {
  const { t } = useTranslation();
  const items = t('home.testimonials.items', { returnObjects: true }) as Testimonial[];
  const [active, setActive] = useState(0);
  const pausedRef = useRef(false);
  const [, force] = useState(0); // hover 暂停时触发重渲(配合 ref)

  const len = Array.isArray(items) ? items.length : 0;

  const go = useCallback(
    (next: number) => {
      if (!len) return;
      setActive(((next % len) + len) % len);
    },
    [len],
  );

  // 自动轮播.悬停暂停,尊重 reduce-motion
  useEffect(() => {
    if (!len) return;
    const reduce =
      typeof window !== 'undefined' &&
      window.matchMedia &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduce) return;
    const id = setInterval(() => {
      if (!pausedRef.current) setActive((a) => (a + 1) % len);
    }, AUTO_MS);
    return () => clearInterval(id);
  }, [len]);

  if (!len) return null;
  const item = items[active];

  const pause = () => {
    pausedRef.current = true;
    force((n) => n + 1);
  };
  const resume = () => {
    pausedRef.current = false;
    force((n) => n + 1);
  };

  return (
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
              d="M7 8h10M7 12h6m-6 8l-4-4h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12z"
            />
          </svg>
          <span className="text-xs font-semibold text-secondary">{t('home.testimonials.badge')}</span>
        </div>
      </div>

      <div
        className="flex items-center justify-center gap-3 sm:gap-5 max-w-3xl mx-auto"
        onMouseEnter={pause}
        onMouseLeave={resume}
      >
        <Arrow dir="prev" onClick={() => go(active - 1)} />

        <div className="relative flex-1 min-w-0">
          <div
            key={active}
            className="animate-fade-in rounded-2xl bg-surface border border-soft shadow-glow px-6 sm:px-12 py-9 sm:py-11 min-h-[240px] sm:min-h-[220px] flex flex-col items-center text-center"
          >
            {/* 大引号装饰 */}
            <svg className="h-9 w-9 text-accent-secondary opacity-30" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M9.13 9C8.5 9.41 8 10.2 8 11h2a2 2 0 012 2v4a2 2 0 01-2 2H6a2 2 0 01-2-2v-5c0-3.31 2.02-6.04 5-7l.13 2zm9 0c-.63.41-1.13 1.2-1.13 2h2a2 2 0 012 2v4a2 2 0 01-2 2h-4a2 2 0 01-2-2v-5c0-3.31 2.02-6.04 5-7l.13 2z" />
            </svg>

            <div className="flex gap-0.5 mt-3" aria-hidden="true">
              {Array.from({ length: 5 }).map((_, i) => (
                <svg key={i} className="h-4 w-4" viewBox="0 0 20 20" fill="#f59e0b">
                  <path d="M9.05 2.93c.3-.92 1.6-.92 1.9 0l1.37 4.22a1 1 0 00.95.69h4.44c.97 0 1.37 1.24.59 1.81l-3.6 2.61a1 1 0 00-.36 1.12l1.37 4.22c.3.92-.75 1.69-1.54 1.12l-3.6-2.61a1 1 0 00-1.18 0l-3.6 2.61c-.78.57-1.83-.2-1.53-1.12l1.37-4.22a1 1 0 00-.36-1.12L1.1 9.66c-.78-.57-.38-1.81.59-1.81h4.44a1 1 0 00.95-.69L8.45 2.93z" />
                </svg>
              ))}
            </div>

            <blockquote className="mt-4 text-base sm:text-xl leading-relaxed text-primary max-w-xl">
              {item.text}
            </blockquote>

            <figcaption className="mt-6 text-sm">
              <span className="font-semibold text-primary">{item.name}</span>
              <span className="text-secondary"> · {item.role}</span>
            </figcaption>
          </div>
        </div>

        <Arrow dir="next" onClick={() => go(active + 1)} />
      </div>

      {/* 圆点指示器 */}
      <div className="flex items-center justify-center gap-2 mt-6">
        {items.map((it, i) => (
          <button
            key={i}
            type="button"
            onClick={() => go(i)}
            aria-label={`testimonial ${i + 1}: ${it.name}`}
            aria-current={i === active}
            className={`h-2 rounded-full transition-all duration-300 ${
              i === active ? 'w-6 bg-accent-primary' : 'w-2 bg-border hover:bg-accent-secondary'
            }`}
          />
        ))}
      </div>
    </section>
  );
}
