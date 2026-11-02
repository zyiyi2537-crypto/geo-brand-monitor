import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Tooltip } from './Tooltip';

type Theme = 'peec' | 'light' | 'dark';
const THEMES: Theme[] = ['peec', 'light', 'dark'];

const applyTheme = (t: Theme) => {
  document.body.setAttribute('data-theme', t);
  document.body.classList.remove('light-mode');
};

const getInitialTheme = (): Theme => {
  const saved = localStorage.getItem('theme');
  if (saved === 'peec' || saved === 'light' || saved === 'dark') {
    return saved;
  }
  return 'peec';
};

export function ThemeToggle() {
  const { t } = useTranslation();
  const [theme, setTheme] = useState<Theme>(() => {
    const value = getInitialTheme();
    applyTheme(value);
    return value;
  });

  useEffect(() => {
    applyTheme(theme);
    localStorage.setItem('theme', theme);
  }, [theme]);

  const cycle = () => {
    const next = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
    setTheme(next);
  };

  const nextTheme = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
  const currentLabel = t(`common.theme.labels.${theme}`);
  const nextLabel = t(`common.theme.labels.${nextTheme}`);
  const tooltipContent = t('common.theme.tooltip', { current: currentLabel, next: nextLabel });

  return (
    <Tooltip content={tooltipContent}>
      <button
        onClick={cycle}
        className="h-9 px-3 flex items-center gap-2 rounded-full border text-xs font-semibold transition bg-surface border-soft border-soft-hover"
        style={{ color: 'var(--text-primary)' }}
        aria-label={currentLabel}
      >
        {theme === 'peec' && (
          <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="4" />
            <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
          </svg>
        )}
        {theme === 'light' && (
          <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="5" />
            <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
          </svg>
        )}
        {theme === 'dark' && (
          <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
          </svg>
        )}
        <span>{currentLabel}</span>
      </button>
    </Tooltip>
  );
}
