import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { switchLanguage } from '../i18n';

interface LanguageSwitcherProps {
  className?: string;
}

export function LanguageSwitcher({ className = '' }: LanguageSwitcherProps) {
  const { i18n } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);
  const [switching, setSwitching] = useState(false);

  const languages = [
    { code: 'en', name: 'English' },
    { code: 'zh', name: '中文' },
  ];

  // switchLanguage awaits target-language pack download before flipping,
  // so the UI never briefly shows raw translation keys. Lock the dropdown
  // while in-flight to avoid a double-click landing on two requests.
  const handleLanguageChange = async (lang: string) => {
    if (switching || lang === i18n.language) {
      setIsOpen(false);
      return;
    }
    setSwitching(true);
    try {
      await switchLanguage(lang as 'en' | 'zh');
    } finally {
      setSwitching(false);
      setIsOpen(false);
    }
  };

  const getLanguageName = (code: string) => {
    return languages.find(lang => lang.code === code)?.name || code;
  };

  return (
    <div className={`relative ${className}`}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          padding: '8px 16px',
          backgroundColor: 'var(--bg-tertiary)',
          border: '1px solid var(--border-color)',
          borderRadius: '9999px',
          color: 'var(--text-secondary)',
          fontSize: '0.875rem',
          fontWeight: '500',
          cursor: 'pointer',
          transition: 'all 0.3s',
        }}
        onMouseOver={(e) => {
          e.currentTarget.style.backgroundColor = 'var(--bg-secondary)';
          e.currentTarget.style.borderColor = 'var(--accent-primary)';
        }}
        onMouseOut={(e) => {
          e.currentTarget.style.backgroundColor = 'var(--bg-tertiary)';
          e.currentTarget.style.borderColor = 'var(--border-color)';
        }}
      >
        {getLanguageName(i18n.language)}
        <svg
          xmlns="http://www.w3.org/2000/svg"
          style={{ height: '16px', width: '16px', color: 'var(--text-secondary)' }}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M19 9l-7 7-7-7"
          />
        </svg>
      </button>

      {isOpen && (
        <div
          style={{
            position: 'absolute',
            top: '100%',
            right: 0,
            marginTop: '8px',
            backgroundColor: 'var(--bg-card)',
            border: '1px solid var(--border-color)',
            borderRadius: '12px',
            boxShadow: '0 4px 16px rgba(0, 0, 0, 0.2)',
            zIndex: 1000,
            minWidth: '120px',
            overflow: 'hidden',
          }}
        >
          {languages.map((lang) => (
            <button
              key={lang.code}
              onClick={() => handleLanguageChange(lang.code)}
              style={{
                display: 'block',
                width: '100%',
                padding: '10px 16px',
                textAlign: 'left' as const,
                backgroundColor: lang.code === i18n.language ? 'rgba(0, 240, 255, 0.1)' : 'transparent',
                color: lang.code === i18n.language ? 'var(--accent-primary)' : 'var(--text-secondary)',
                border: 'none',
                borderRadius: lang.code === i18n.language ? '8px' : '0',
                fontSize: '0.875rem',
                fontWeight: '500',
                cursor: 'pointer',
                transition: 'all 0.2s',
              }}
              onMouseOver={(e) => {
                if (lang.code !== i18n.language) {
                  e.currentTarget.style.backgroundColor = 'var(--bg-tertiary)';
                  e.currentTarget.style.color = 'var(--text-primary)';
                }
              }}
              onMouseOut={(e) => {
                if (lang.code !== i18n.language) {
                  e.currentTarget.style.backgroundColor = 'transparent';
                  e.currentTarget.style.color = 'var(--text-secondary)';
                }
              }}
            >
              {lang.name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
