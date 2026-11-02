import { Link, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

export function GeoKnowledgeTabs() {
  const { t } = useTranslation();
  const location = useLocation();

  const tabs = [
    { to: '/geo-knowledge', label: t('geoKnowledge.tabs.overview') },
    { to: '/geo-knowledge/metrics', label: t('geoKnowledge.tabs.metrics') },
  ];

  return (
    <div className="flex justify-center mb-12">
      <div
        className="inline-flex gap-1 p-1 rounded-xl border"
        style={{
          background: 'var(--bg-card)',
          borderColor: 'var(--border-color)',
        }}
      >
        {tabs.map((tab) => {
          const active = location.pathname === tab.to;
          return (
            <Link
              key={tab.to}
              to={tab.to}
              className="px-5 py-2 rounded-lg text-sm font-semibold transition-colors flex items-center"
              style={{
                background: active ? 'var(--accent-primary)' : 'transparent',
                color: active ? 'var(--bg-primary)' : 'var(--text-secondary)',
              }}
            >
              {tab.label}
            </Link>
          );
        })}
      </div>
    </div>
  );
}
