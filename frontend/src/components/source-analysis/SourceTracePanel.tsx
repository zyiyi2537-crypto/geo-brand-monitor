import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { CISourceEntry, CISelfCitation } from '../../types/sourceAnalysis';

export const ENGINE_COLORS: Record<string, string> = {
  OpenAI: '#00A67E',
  DeepSeek: '#7C3AED',
  Kimi: '#3B82F6',
  '通义千问': '#F59E0B',
  '智谱': '#10B981',
  Perplexity: '#8B5CF6',
  '文心一言': '#EC4899',
  '豆包': '#EF4444',
  ChatGPT: '#6366F1',
  Claude: '#06B6D4',
  Doubao: '#EF4444',
  '元宝': '#F97316',
  Gemini: '#4285F4',
  Mistral: '#FF7000',
};

const ENGINE_POPULARITY: Record<string, number> = {
  '豆包': 1,
  Doubao: 1,
  DeepSeek: 2,
  '通义千问': 3,
  '元宝': 4,
  '文心一言': 5,
  Kimi: 6,
  '智谱': 7,
  OpenAI: 8,
  ChatGPT: 8,
  Claude: 9,
  Gemini: 10,
  Perplexity: 11,
  Mistral: 12,
};

const HIDDEN_ENGINES = new Set(['Copilot']);

export function orderEngines(engines: string[]): string[] {
  return engines
    .filter((e) => !HIDDEN_ENGINES.has(e))
    .slice()
    .sort((a, b) => (ENGINE_POPULARITY[a] ?? 99) - (ENGINE_POPULARITY[b] ?? 99));
}

const cardStyle: React.CSSProperties = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border-color)',
};

export interface SourceTracePanelProps {
  sources: CISourceEntry[];
  selfCitations: CISelfCitation[];
  missingQueries: string[];
  totalSources: number;
  totalCitations: number;
  engines: string[];
}

export function SourceTracePanel({
  sources,
  engines,
}: SourceTracePanelProps) {
  const { t } = useTranslation();
  const [expandedPlatform, setExpandedPlatform] = useState<string | null>(null);
  const [activeEngine, setActiveEngine] = useState<string>('__all__');
  const [searchQuery, setSearchQuery] = useState('');

  const allModelsLabel = t('home.advanced.result.entity.sa.allModels');
  const engineList = [allModelsLabel, ...orderEngines(engines)];

  const filteredSources = sources.filter((s) => {
    if (searchQuery && !s.platform.toLowerCase().includes(searchQuery.toLowerCase())) return false;
    if (activeEngine !== '__all__' && !s.engines.includes(activeEngine)) return false;
    return true;
  });

  const displayTotalSources = filteredSources.length;
  const displayTotalCitations = filteredSources.reduce((sum, s) => sum + s.total_citations, 0);
  const maxCitations = Math.max(...filteredSources.map((s) => s.total_citations), 1);

  return (
    <div className="space-y-5">
      {/* Model filter */}
      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-2">
          <svg className="w-4 h-4" style={{ color: 'var(--text-tertiary)' }} fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
          <span className="text-sm" style={{ color: 'var(--text-tertiary)' }}>{t('home.advanced.result.entity.sa.aiModels')}</span>
        </div>
        <div className="flex gap-2 flex-wrap">
          {engineList.map((eng, i) => (
            <button
              key={eng}
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
      </div>

      {/* Info bar */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--text-secondary)' }}>
          <span className="font-semibold" style={{ color: '#7C3AED' }}>{t('home.advanced.result.entity.sa.sourcesCount', { count: displayTotalSources })}</span>
          <span>{'·'}</span>
          <span>{t('home.advanced.result.entity.sa.citationsCount', { count: displayTotalCitations })}</span>
        </div>
        <div className="flex items-center gap-3">
          <div className="relative">
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
      </div>

      {/* Table */}
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
                fill="none" viewBox="0 0 24 24" stroke="currentColor"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>

              <div className="flex items-center gap-3">
                <span className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
                  {source.platform}
                </span>
                <span className="text-xs px-2 py-0.5 rounded-full" style={{ background: 'var(--bg-surface)', color: 'var(--text-tertiary)' }}>
                  {t('home.advanced.result.entity.sa.articles', { count: source.article_count })}
                </span>
              </div>

              <div className="flex flex-col items-center gap-1">
                <span className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>{source.total_citations}</span>
                <div className="w-20 h-1 rounded-full overflow-hidden" style={{ background: 'var(--bg-surface)' }}>
                  <div className="h-full rounded-full" style={{ width: `${(source.total_citations / maxCitations) * 100}%`, background: '#7C3AED' }} />
                </div>
              </div>

              <div className="flex justify-end gap-2 flex-wrap">
                {orderEngines(source.engines).map((eng) => (
                  <span key={eng} className="text-xs px-2.5 py-1 rounded-md font-medium text-white" style={{ background: ENGINE_COLORS[eng] || '#6B7280' }}>
                    {eng}
                  </span>
                ))}
              </div>
            </div>

            {expandedPlatform === source.platform && source.articles.length > 0 && (
              <div className="px-10 py-3 space-y-2 border-b" style={{ background: 'var(--bg-surface)', borderColor: 'var(--border-color)' }}>
                {source.articles.map((article) => (
                  <div key={article.url} className="flex items-center justify-between py-2">
                    <a href={article.url} target="_blank" rel="noopener noreferrer" className="text-sm hover:underline" style={{ color: 'var(--accent-primary)' }}>
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
    </div>
  );
}
