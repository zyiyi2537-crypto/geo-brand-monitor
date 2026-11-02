import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ENGINE_COLORS, orderEngines } from './SourceTracePanel';
import type { CISourcePreference, CISourceTrace } from '../../types/sourceAnalysis';

const cardStyle: React.CSSProperties = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border-color)',
};

/* -- Donut Chart ------------------------------------------------- */

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

/* -- Component --------------------------------------------------- */

export interface SourcePreferencePanelProps {
  sourcePreference: CISourcePreference;
  sourceTrace: CISourceTrace;
  engines: string[];
}

export function SourcePreferencePanel({
  sourcePreference: sp,
  sourceTrace,
  engines,
}: SourcePreferencePanelProps) {
  const { t } = useTranslation();
  const allPlatformsLabel = t('home.advanced.result.entity.sa.allPlatforms');
  const [activeEngine, setActiveEngine] = useState<string>('__all__');
  const [searchQuery, setSearchQuery] = useState('');

  const orderedEngines = orderEngines(engines);
  const engineList = [allPlatformsLabel, ...orderedEngines];

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
    if (activeEngine !== '__all__' && eng.engine !== activeEngine) continue;
    for (const td of eng.top_domains) {
      if (!domainByEngine[td.domain]) domainByEngine[td.domain] = {};
      domainByEngine[td.domain][eng.engine] = td.count;
    }
  }
  for (const src of filteredSources) {
    if (!domainByEngine[src.platform]) {
      domainByEngine[src.platform] = {};
    }
    for (const eng of src.engines) {
      if (activeEngine !== '__all__' && eng !== activeEngine) continue;
      if (!domainByEngine[src.platform][eng]) {
        domainByEngine[src.platform][eng] = Math.ceil(src.total_citations / src.engines.length);
      }
    }
  }

  const barData = Object.entries(domainByEngine)
    .map(([domain, engs]) => ({
      domain,
      total: Object.values(engs).reduce((s, v) => s + v, 0),
      byEngine: engs,
    }))
    .filter((d) => !searchQuery || d.domain.toLowerCase().includes(searchQuery.toLowerCase()))
    .sort((a, b) => b.total - a.total)
    .slice(0, 10);

  const maxTotal = Math.max(...barData.map((d) => d.total), 1);

  const donutData = activeEngine === '__all__'
    ? orderedEngines
        .filter((label) => sp.engine_totals[label] !== undefined)
        .map((label) => ({
          label,
          value: sp.engine_totals[label],
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
      {/* Filters */}
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
        <div className="relative ml-auto">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4" style={{ color: 'var(--text-tertiary)' }} fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            type="text"
            placeholder={t('home.advanced.result.entity.sa.searchSource')}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="rounded-lg border pl-9 pr-3 py-1.5 text-sm w-48"
            style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }}
          />
        </div>
      </div>

      {/* Stat cards */}
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

      {/* Charts row */}
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
                  {orderedEngines.map((eng) => {
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

      {/* Recommendations */}
      {sp.recommendations.length > 0 && (
        <div className="rounded-xl p-6" style={cardStyle}>
          <h3 className="text-base font-semibold mb-4" style={{ color: 'var(--text-primary)' }}>
            {t('home.advanced.result.entity.sa.recommendations')}
          </h3>
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
                <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
                  {rec.message}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
