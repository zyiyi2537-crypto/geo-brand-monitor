// 内容创作 — 按 query / 簇 起稿 + 适配引擎答题套路 + 品牌口吻模板.
// 当前为静态页 MVP:topic 选择器拉真 topic,query / 簇 列表来自真 topic;
// 起稿区是 mock(占位文本),不接 LLM.

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { PageHead } from '../../components/PageHead';
import {
  aiTelemetryApi,
  type Topic,
} from '../../services/aiTelemetryApi';

type AnswerFormat = 'listicle' | 'report' | 'case';

const FORMATS: { id: AnswerFormat; labelKey: string }[] = [
  { id: 'listicle', labelKey: 'dashboard.compose.formatListicle' },
  { id: 'report',   labelKey: 'dashboard.compose.formatReport' },
  { id: 'case',     labelKey: 'dashboard.compose.formatCase' },
];

const BRAND_VOICES = [
  { id: 'professional',  nameKey: 'dashboard.compose.voiceProfessional' },
  { id: 'friendly',      nameKey: 'dashboard.compose.voiceFriendly' },
  { id: 'authoritative', nameKey: 'dashboard.compose.voiceAuthoritative' },
];

function mockDraft(query: string, fmt: AnswerFormat, t: (k: string) => string): string {
  const title = `${query}`;
  if (fmt === 'listicle') {
    return `# ${title}\n\n## 1. ${t('dashboard.compose.draftStub.list1')}\n${t('dashboard.compose.draftStub.fill')}\n\n## 2. ${t('dashboard.compose.draftStub.list2')}\n${t('dashboard.compose.draftStub.fill')}\n\n## 3. ${t('dashboard.compose.draftStub.list3')}\n${t('dashboard.compose.draftStub.fill')}\n`;
  }
  if (fmt === 'report') {
    return `# ${title}\n\n## ${t('dashboard.compose.draftStub.background')}\n${t('dashboard.compose.draftStub.fill')}\n\n## ${t('dashboard.compose.draftStub.data')}\n${t('dashboard.compose.draftStub.fill')}\n\n## ${t('dashboard.compose.draftStub.conclusion')}\n${t('dashboard.compose.draftStub.fill')}\n`;
  }
  return `# ${title}\n\n## ${t('dashboard.compose.draftStub.caseBg')}\n${t('dashboard.compose.draftStub.fill')}\n\n## ${t('dashboard.compose.draftStub.caseProcess')}\n${t('dashboard.compose.draftStub.fill')}\n\n## ${t('dashboard.compose.draftStub.caseOutcome')}\n${t('dashboard.compose.draftStub.fill')}\n`;
}

export function Compose() {
  const { t } = useTranslation();
  const token = localStorage.getItem('token') || '';
  const [topics, setTopics] = useState<Topic[]>([]);
  const [topicId, setTopicId] = useState<number | null>(null);
  const [selectedQuery, setSelectedQuery] = useState<string | null>(null);
  const [format, setFormat] = useState<AnswerFormat>('listicle');
  const [voiceId, setVoiceId] = useState<string>(BRAND_VOICES[0].id);
  const [draft, setDraft] = useState<string>('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    aiTelemetryApi.listTopics(token)
      .then(list => {
        setTopics(list);
        if (list[0]?.id) setTopicId(list[0].id);
      })
      .finally(() => setLoading(false));
  }, [token]);

  const currentTopic = useMemo(
    () => topics.find(x => x.id === topicId) || null,
    [topics, topicId],
  );

  // 按 cluster 分组 queries
  const grouped = useMemo(() => {
    if (!currentTopic) return [] as { cid: number; label: string; queries: string[] }[];
    const { queries, query_cluster_ids, clusters } = currentTopic;
    const map = new Map<number, string[]>();
    queries.forEach((q, i) => {
      const cid = query_cluster_ids?.[i] ?? -1;
      if (!map.has(cid)) map.set(cid, []);
      map.get(cid)!.push(q);
    });
    return Array.from(map.entries()).map(([cid, qs]) => ({
      cid,
      label: clusters?.find(c => c.cluster_id === cid)?.label
        ?? (cid === -1 ? t('dashboard.compose.clusterUngrouped') : `#${cid}`),
      queries: qs,
    }));
  }, [currentTopic, t]);

  // 选 query / 切 format / 切 voice 时,重新生成 mock 初稿(占位)
  const regenerate = () => {
    if (!selectedQuery) return;
    setDraft(mockDraft(selectedQuery, format, t));
  };

  useEffect(() => {
    if (selectedQuery) setDraft(mockDraft(selectedQuery, format, t));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedQuery, format, voiceId]);

  return (
    <div className="space-y-4">
      <PageHead titleKey="dashboard.nav.compose" titleFallback="Content" />

      <header className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-xl font-semibold text-primary leading-tight">
            {t('dashboard.nav.compose')}
          </h1>
          <p className="text-xs text-secondary mt-0.5">
            {t('dashboard.compose.subtitle')}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-secondary">{t('dashboard.compose.topicLabel')}</label>
          <select
            value={topicId ?? ''}
            onChange={(e) => { setTopicId(Number(e.target.value)); setSelectedQuery(null); setDraft(''); }}
            disabled={loading || topics.length === 0}
            className="px-3 py-1.5 rounded-md text-sm"
            style={{
              background: 'var(--bg-input)',
              border: '1px solid var(--border-color)',
              color: 'var(--text-primary)',
            }}
          >
            {topics.length === 0 && <option value="">{t('dashboard.compose.noTopic')}</option>}
            {topics.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}
          </select>
        </div>
      </header>

      <div className="grid grid-cols-12 gap-4">
        {/* 左栏:query / 簇 列表 */}
        <aside
          className="col-span-12 md:col-span-3 rounded-md p-3 space-y-3 max-h-[70vh] overflow-y-auto"
          style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}
        >
          <h3 className="text-xs font-semibold text-secondary uppercase tracking-wide">
            {t('dashboard.compose.queriesTitle')}
          </h3>
          {grouped.length === 0 && (
            <p className="text-xs text-muted py-4">{t('dashboard.compose.queriesEmpty')}</p>
          )}
          {grouped.map(g => (
            <div key={g.cid} className="space-y-1">
              <div className="text-[11px] font-semibold text-muted">{g.label}</div>
              <ul className="space-y-0.5">
                {g.queries.map(q => (
                  <li key={q}>
                    <button
                      type="button"
                      onClick={() => setSelectedQuery(q)}
                      className="w-full text-left px-2 py-1.5 rounded text-xs leading-snug transition-colors"
                      style={{
                        background: selectedQuery === q ? 'var(--bg-tertiary)' : 'transparent',
                        color: selectedQuery === q ? 'var(--accent-primary)' : 'var(--text-secondary)',
                      }}
                    >
                      {q}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </aside>

        {/* 中栏:起稿区 */}
        <main
          className="col-span-12 md:col-span-7 rounded-md p-4 space-y-4"
          style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}
        >
          {!selectedQuery && (
            <div className="py-16 text-center text-sm text-muted">
              {t('dashboard.compose.selectQueryHint')}
            </div>
          )}
          {selectedQuery && (
            <>
              <div>
                <div className="text-[11px] text-muted">{t('dashboard.compose.currentQuery')}</div>
                <div className="text-sm font-semibold text-primary mt-0.5">{selectedQuery}</div>
              </div>

              <div className="flex items-center gap-4 flex-wrap">
                {/* answer_format */}
                <div className="flex items-center gap-2">
                  <span className="text-xs text-secondary">{t('dashboard.compose.formatLabel')}</span>
                  <div className="inline-flex rounded-md border overflow-hidden" style={{ borderColor: 'var(--border-color)' }}>
                    {FORMATS.map(f => (
                      <button
                        key={f.id}
                        type="button"
                        onClick={() => setFormat(f.id)}
                        className="px-3 py-1 text-xs transition-colors"
                        style={{
                          background: format === f.id ? 'var(--accent-primary)' : 'var(--bg-input)',
                          color: format === f.id ? 'var(--solid-btn-text)' : 'var(--text-secondary)',
                        }}
                      >
                        {t(f.labelKey)}
                      </button>
                    ))}
                  </div>
                </div>

                {/* brand voice */}
                <div className="flex items-center gap-2">
                  <span className="text-xs text-secondary">{t('dashboard.compose.voiceLabel')}</span>
                  <select
                    value={voiceId}
                    onChange={(e) => setVoiceId(e.target.value)}
                    className="px-3 py-1 rounded-md text-xs"
                    style={{
                      background: 'var(--bg-input)',
                      border: '1px solid var(--border-color)',
                      color: 'var(--text-primary)',
                    }}
                  >
                    {BRAND_VOICES.map(v => (
                      <option key={v.id} value={v.id}>{t(v.nameKey)}</option>
                    ))}
                  </select>
                </div>

                <button
                  type="button"
                  onClick={regenerate}
                  className="text-xs px-3 py-1 rounded-md ml-auto"
                  style={{ background: 'var(--bg-tertiary)', color: 'var(--accent-primary)' }}
                >
                  ⟳ {t('dashboard.compose.regenerate')}
                </button>
              </div>

              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                rows={18}
                className="w-full rounded-md p-3 text-sm font-mono resize-none focus:outline-none focus:ring-2"
                style={{
                  background: 'var(--bg-surface)',
                  color: 'var(--text-primary)',
                  border: '1px solid var(--border-color)',
                  '--tw-ring-color': 'var(--accent-primary)',
                } as React.CSSProperties}
                placeholder={t('dashboard.compose.draftPlaceholder')}
              />

              <p className="text-[11px] text-muted">{t('dashboard.compose.mockNotice')}</p>
            </>
          )}
        </main>

        {/* 右栏:状态 + 操作 */}
        <aside
          className="col-span-12 md:col-span-2 rounded-md p-3 space-y-3"
          style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}
        >
          <h3 className="text-xs font-semibold text-secondary uppercase tracking-wide">
            {t('dashboard.compose.statusTitle')}
          </h3>
          <div className="text-xs text-secondary leading-relaxed">
            <div>
              <span className="text-muted">{t('dashboard.compose.statusCurrent')}</span>
              <span className="ml-1 px-1.5 py-0.5 rounded text-[10px]"
                style={{ background: 'var(--bg-tertiary)', color: 'var(--text-primary)' }}>
                {t('dashboard.compose.statusDraft')}
              </span>
            </div>
          </div>
          <div className="space-y-2 pt-2 border-t" style={{ borderColor: 'var(--border-color)' }}>
            <button
              type="button"
              disabled={!selectedQuery}
              className="w-full px-3 py-1.5 text-xs rounded-md"
              style={{
                background: 'var(--bg-tertiary)',
                color: 'var(--text-primary)',
                opacity: selectedQuery ? 1 : 0.5,
              }}
            >
              {t('dashboard.compose.saveDraft')}
            </button>
            <button
              type="button"
              disabled={!selectedQuery}
              className="w-full px-3 py-1.5 text-xs rounded-md text-white"
              style={{
                background: 'var(--accent-primary)',
                opacity: selectedQuery ? 1 : 0.5,
              }}
            >
              {t('dashboard.compose.sendToDistribution')}
            </button>
          </div>
        </aside>
      </div>
    </div>
  );
}
