import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { CISourcePreference, CISourceTrace } from '../../types/sourceAnalysis';
import { ENGINE_COLORS, orderEngines } from './SourceTracePanel';

const cardStyle: React.CSSProperties = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border-color)',
};

function DonutChart({ data }: { data: { label: string; value: number; color: string }[] }) {
  const total = data.reduce((s, d) => s + d.value, 0);
  if (total === 0) return null;

  const size = 180;
  const strokeWidth = 35;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;

  let accumulated = 0;
  const segments = data.map((d) => {
    const pct = d.value / total;
    const offset = circumference * (1 - accumulated) + circumference * 0.25;
    accumulated += pct;
    return { ...d, pct, dasharray: `${circumference * pct} ${circumference * (1 - pct)}`, offset };
  });

  return (
    <div className="flex flex-col items-center gap-4">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        {segments.map((seg, i) => (
          <circle
            key={i}
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={seg.color}
            strokeWidth={strokeWidth}
            strokeDasharray={seg.dasharray}
            strokeDashoffset={seg.offset}
            strokeLinecap="butt"
            style={{ transition: 'stroke-dasharray 0.5s, stroke-dashoffset 0.5s' }}
          />
        ))}
      </svg>
      <div className="space-y-2">
        {data.map((d) => (
          <div key={d.label} className="flex items-center gap-3">
            <span className="w-3 h-3 rounded-full shrink-0" style={{ background: d.color }} />
            <span className="text-sm" style={{ color: 'var(--text-secondary)' }}>{d.label}</span>
            <span className="text-sm font-bold ml-auto" style={{ color: d.color }}>{d.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export interface SourceAnalysisPanelProps {
  sourceTrace: CISourceTrace;
  sourcePreference: CISourcePreference;
  engines: string[];
}

export function SourceAnalysisPanel({
  sourceTrace,
  sourcePreference: sp,
  engines,
}: SourceAnalysisPanelProps) {
  const { t } = useTranslation();
  const allModelsLabel = t('home.advanced.result.entity.sa.allModels');
  const [activeEngine, setActiveEngine] = useState<string>('__all__');
  const [searchQuery, setSearchQuery] = useState('');
  const [expandedPlatform, setExpandedPlatform] = useState<string | null>(null);

  const engineList = [allModelsLabel, ...orderEngines(engines)];

  const filteredSources = sourceTrace.sources.filter((s) => {
    if (activeEngine !== '__all__' && !s.engines.includes(activeEngine)) return false;
    if (searchQuery && !s.platform.toLowerCase().includes(searchQuery.toLowerCase())) return false;
    return true;
  });

  const total_sources = filteredSources.length;
  const total_citations = filteredSources.reduce((sum, s) => sum + s.total_citations, 0);
  const avg_citations = total_sources > 0 ? +(total_citations / total_sources).toFixed(1) : 0;

  const domainByEngine: Record<string, Record<string, number>> = {};
  for (const eng of sp.per_engine) {
    for (const td of eng.top_domains) {
      if (!domainByEngine[td.domain]) domainByEngine[td.domain] = {};
      domainByEngine[td.domain][eng.engine] = td.count;
    }
  }
  for (const src of filteredSources) {
    if (!domainByEngine[src.platform]) domainByEngine[src.platform] = {};
    for (const eng of src.engines) {
      if (!domainByEngine[src.platform][eng]) {
        domainByEngine[src.platform][eng] = Math.ceil(src.total_citations / src.engines.length);
      }
    }
  }

  const barData = Object.entries(domainByEngine)
    .filter(([domain]) => filteredSources.some((s) => s.platform === domain))
    .map(([domain, engs]) => ({
      domain,
      total: Object.values(engs).reduce((s, v) => s + v, 0),
      byEngine: engs,
    }))
    .sort((a, b) => b.total - a.total)
    .slice(0, 10);

  const maxTotal = Math.max(...barData.map((d) => d.total), 1);
  const maxCitations = Math.max(...filteredSources.map((s) => s.total_citations), 1);

  const donutData = activeEngine === '__all__'
    ? Object.entries(sp.engine_totals).map(([label, value]) => ({
        label,
        value,
        color: ENGINE_COLORS[label] || '#6B7280',
      }))
    : (() => {
        const engSources = sourceTrace.sources.filter(s => s.engines.includes(activeEngine));
        const engCitations = engSources.reduce((sum, s) => {
          const share = Math.ceil(s.total_citations / s.engines.length);
          return sum + share;
        }, 0);
        return [{
          label: activeEngine,
          value: engCitations,
          color: ENGINE_COLORS[activeEngine] || '#6B7280',
        }];
      })();

  return (
    <div className="space-y-6">
      {/* A. Top controls */}
      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex gap-2 flex-wrap">
          {engineList.map((eng, i) => (
            <button
              key={i === 0 ? '__all__' : eng}
              onClick={() => setActiveEngine(i === 0 ? '__all__' : eng)}
              className="px-4 py-1.5 rounded-lg text-sm font-medium border transition-colors"
              style={
                (i === 0 ? activeEngine === '__all__' : activeEngine === eng)
                  ? { background: 'var(--accent-primary)', color: '#fff', borderColor: 'var(--accent-primary)' }
                  : { background: 'var(--bg-card)', color: 'var(--text-secondary)', borderColor: 'var(--border-color)' }
              }
            >
              {eng}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-3 ml-auto">
          <div className="relative">
            <svg
              className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4"
              style={{ color: 'var(--text-tertiary)' }}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input
              type="text"
              placeholder={t('home.advanced.result.entity.sa.searchDomain')}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="rounded-lg border pl-9 pr-3 py-1.5 text-sm w-48"
              style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }}
            />
          </div>
        </div>
      </div>

      {/* B. Stat cards */}
      <div className="grid grid-cols-3 gap-4">
        <div className="rounded-xl p-5" style={cardStyle}>
          <div className="text-xs mb-2" style={{ color: 'var(--text-tertiary)' }}>{t('home.advanced.result.entity.sa.sourceCount')}</div>
          <div className="text-3xl font-bold" style={{ color: 'var(--text-primary)' }}>{total_sources}</div>
        </div>
        <div className="rounded-xl p-5" style={cardStyle}>
          <div className="text-xs mb-2" style={{ color: 'var(--text-tertiary)' }}>{t('home.advanced.result.entity.sa.totalCitations')}</div>
          <div className="text-3xl font-bold" style={{ color: 'var(--text-primary)' }}>{total_citations}</div>
        </div>
        <div className="rounded-xl p-5" style={cardStyle}>
          <div className="text-xs mb-2" style={{ color: 'var(--text-tertiary)' }}>{t('home.advanced.result.entity.sa.avgCitations')}</div>
          <div className="text-3xl font-bold" style={{ color: 'var(--text-primary)' }}>{avg_citations}</div>
        </div>
      </div>

      {/* C. Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
        <div className="lg:col-span-3 rounded-xl p-6" style={cardStyle}>
          <h3 className="text-base font-semibold mb-6" style={{ color: 'var(--text-primary)' }}>
            {t('home.advanced.result.entity.sa.top10Sources')}
          </h3>
          <div className="space-y-3">
            {barData.map((source) => (
              <div key={source.domain} className="flex items-center gap-3">
                <span className="text-xs text-right shrink-0 truncate" style={{ width: 110, color: 'var(--text-secondary)' }}>
                  {source.domain}
                </span>
                <div className="flex-1 flex h-5 rounded overflow-hidden" style={{ background: 'var(--bg-surface)' }}>
                  {orderEngines(engines).map((eng) => {
                    const val = source.byEngine[eng] || 0;
                    if (val === 0) return null;
                    return (
                      <div
                        key={eng}
                        className="h-full transition-all duration-500"
                        style={{ width: `${(val / maxTotal) * 100}%`, background: ENGINE_COLORS[eng] || '#6B7280' }}
                        title={`${eng}: ${val}`}
                      />
                    );
                  })}
                </div>
              </div>
            ))}
            {barData.length === 0 && (
              <p className="text-center py-8 text-sm" style={{ color: 'var(--text-tertiary)' }}>{t('home.advanced.result.entity.sa.noData')}</p>
            )}
          </div>
        </div>

        <div className="lg:col-span-2 rounded-xl p-6" style={cardStyle}>
          <h3 className="text-base font-semibold mb-6" style={{ color: 'var(--text-primary)' }}>
            {t('home.advanced.result.entity.sa.platformShare')}
          </h3>
          <div className="flex justify-center">
            <DonutChart data={donutData} />
          </div>
        </div>
      </div>

      {/* D. Source table */}
      <div className="rounded-xl overflow-hidden" style={cardStyle}>
        <div
          className="grid items-center px-5 py-3 text-xs font-medium uppercase tracking-wider border-b"
          style={{ gridTemplateColumns: '32px 1fr 200px 200px', color: 'var(--text-tertiary)', borderColor: 'var(--border-color)' }}
        >
          <span />
          <span>{t('home.advanced.result.entity.sa.headerPlatform')}</span>
          <span className="text-center">{t('home.advanced.result.entity.sa.headerCitations')}</span>
          <span className="text-right">{t('home.advanced.result.entity.sa.headerModels')}</span>
        </div>

        {filteredSources.map((source) => (
          <div key={source.platform}>
            <div
              className="grid items-center px-5 py-5 cursor-pointer transition-colors hover:bg-[var(--bg-surface)] border-b"
              style={{ gridTemplateColumns: '32px 1fr 200px 200px', borderColor: 'var(--border-color)' }}
              onClick={() => setExpandedPlatform(expandedPlatform === source.platform ? null : source.platform)}
            >
              <svg
                className={`w-4 h-4 transition-transform ${expandedPlatform === source.platform ? 'rotate-90' : ''}`}
                style={{ color: 'var(--text-tertiary)' }}
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>

              <div className="flex items-center gap-3">
                <span className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>{source.platform}</span>
                <span
                  className="text-xs px-2 py-0.5 rounded-full"
                  style={{ background: 'var(--bg-surface)', color: 'var(--text-tertiary)' }}
                >
                  {t('home.advanced.result.entity.sa.articles', { count: source.article_count })}
                </span>
              </div>

              <div className="flex flex-col items-center gap-1">
                <span className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>{source.total_citations}</span>
                <div className="w-20 h-1 rounded-full overflow-hidden" style={{ background: 'var(--bg-surface)' }}>
                  <div
                    className="h-full rounded-full"
                    style={{ width: `${(source.total_citations / maxCitations) * 100}%`, background: '#7C3AED' }}
                  />
                </div>
              </div>

              <div className="flex justify-end gap-2 flex-wrap">
                {source.engines.map((eng) => (
                  <span
                    key={eng}
                    className="text-xs px-2.5 py-1 rounded-md font-medium text-white"
                    style={{ background: ENGINE_COLORS[eng] || '#6B7280' }}
                  >
                    {eng}
                  </span>
                ))}
              </div>
            </div>

            {expandedPlatform === source.platform && source.articles.length > 0 && (
              <div
                className="px-10 py-3 space-y-2 border-b"
                style={{ background: 'var(--bg-surface)', borderColor: 'var(--border-color)' }}
              >
                {source.articles.map((article) => (
                  <div key={article.url} className="flex items-center justify-between py-2">
                    <a
                      href={article.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sm hover:underline"
                      style={{ color: 'var(--accent-primary)' }}
                    >
                      {article.title}
                    </a>
                    <span className="text-xs font-medium" style={{ color: 'var(--text-tertiary)' }}>
                      {t('home.advanced.result.entity.sa.citedTimes', { count: article.citations })}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}

        {filteredSources.length === 0 && (
          <p className="text-center py-12 text-sm" style={{ color: 'var(--text-tertiary)' }}>
            {t('home.advanced.result.entity.sa.noMatch')}
          </p>
        )}
      </div>

      {/* E. Recommendations */}
      {sp.recommendations.length > 0 && (
        <div className="rounded-xl p-6" style={cardStyle}>
          <h3 className="text-base font-semibold mb-4" style={{ color: 'var(--text-primary)' }}>{t('home.advanced.result.entity.sa.recommendations')}</h3>
          <div className="space-y-3">
            {sp.recommendations.map((rec, i) => (
              <div
                key={i}
                className="flex items-start gap-3 rounded-lg p-3"
                style={{ background: 'var(--bg-surface)' }}
              >
                <span
                  className="text-xs px-2 py-0.5 rounded-full font-medium shrink-0 mt-0.5"
                  style={{
                    background: rec.type === 'warning' ? '#FEF3C7' : rec.type === 'insight' ? '#DBEAFE' : '#F3F4F6',
                    color: rec.type === 'warning' ? '#92400E' : rec.type === 'insight' ? '#1E40AF' : '#374151',
                  }}
                >
                  {rec.engine}
                </span>
                <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>{rec.message}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
