import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { BrandGrowthShell, type ShellState } from './shell';
import { aiTelemetryApi, type Briefing } from '../../services/aiTelemetryApi';
import { useBgLang } from './lang';
import { InfoHint } from './charts';

export function Insights() {
  const L = useBgLang();
  return (
    <BrandGrowthShell title={L.insightsTitle} breadcrumb={[{ label: L.pageTitle, to: '/brand-growth' }]}>
      {(state) => <Body state={state} />}
    </BrandGrowthShell>
  );
}

function Body({ state }: { state: ShellState }) {
  const { token, topic } = state;
  const L = useBgLang();
  const [params, setParams] = useSearchParams();
  const briefingId = Number(params.get('briefing') || '0');
  const [items, setItems] = useState<Briefing[]>([]);
  const [generating, setGenerating] = useState(false);
  const [active, setActive] = useState<Briefing | null>(null);

  useEffect(() => {
    if (!topic) return;
    aiTelemetryApi.listBriefings(topic.id, token, 30).then(setItems).catch(() => setItems([]));
  }, [token, topic?.id]);

  useEffect(() => {
    if (briefingId > 0 && items.length > 0) {
      setActive(items.find(b => b.id === briefingId) || null);
    }
  }, [briefingId, items]);

  if (!topic) return null;

  const generate = async () => {
    setGenerating(true);
    try {
      const b = await aiTelemetryApi.triggerBriefing(topic.id, token);
      setItems([b, ...items]);
      setActive(b);
      const next = new URLSearchParams(params);
      next.set('briefing', String(b.id));
      setParams(next, { replace: true });
    } catch (e) {
      console.error(e);
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <div className="lg:col-span-1 p-4 rounded-lg" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
        <div className="flex items-center justify-between mb-3 pb-2 border-b" style={{ borderColor: 'var(--border-color)' }}>
          <h3 className="text-sm font-medium text-primary flex items-center gap-2">
            <span className="w-1 h-4 rounded-sm" style={{ background: 'var(--accent-primary)' }} />
            {L.insightsBriefingList}
            <InfoHint text={L.hintInsights} />
          </h3>
          <button
            type="button" onClick={generate} disabled={generating}
            className="px-3 py-1 text-xs rounded"
            style={{ background: 'var(--accent-primary)', color: 'white', opacity: generating ? 0.6 : 1 }}
          >
            {generating ? L.insightsGenerating : L.insightsGenerate}
          </button>
        </div>
        {items.length === 0 ? (
          <div className="text-xs text-muted py-6 text-center">{L.emptyBriefings}</div>
        ) : (
          <ul className="space-y-1">
            {items.map(b => (
              <li key={b.id}>
                <button
                  type="button"
                  onClick={() => {
                    setActive(b);
                    const next = new URLSearchParams(params);
                    next.set('briefing', String(b.id));
                    setParams(next, { replace: true });
                  }}
                  className="w-full text-left px-2 py-1.5 rounded text-xs"
                  style={{
                    background: active?.id === b.id ? 'var(--bg-input)' : 'transparent',
                    color: active?.id === b.id ? 'var(--accent-primary)' : 'var(--text-secondary)',
                  }}
                >
                  <div className="truncate">{L.insightsBriefingItem(new Date(b.period_start).toLocaleDateString(), new Date(b.period_end).toLocaleDateString())}</div>
                  <div className="text-[10px] text-muted">{new Date(b.generated_at).toLocaleString()}</div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="lg:col-span-2 p-4 rounded-lg" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
        {!active ? (
          <div className="text-xs text-muted py-10 text-center">{L.insightsPick}</div>
        ) : (
          <BriefingView b={active} />
        )}
      </div>
    </div>
  );
}

function BriefingView({ b }: { b: Briefing }) {
  const L = useBgLang();
  return (
    <div>
      <div className="text-xs text-muted mb-2 flex items-center gap-1.5">
        {L.insightsBriefingMeta(
          new Date(b.period_start).toLocaleDateString(),
          new Date(b.period_end).toLocaleDateString(),
        )}
        <InfoHint text={L.hintInsightsView} />
      </div>
      <div className="text-sm text-primary whitespace-pre-wrap leading-relaxed">{b.body_md}</div>
      {b.top_actions.length > 0 && (
        <div className="mt-4">
          <h4 className="text-xs text-muted mb-2">{L.insightsRecommendations}</h4>
          <ul className="space-y-2">
            {b.top_actions.map((a, i) => (
              <li key={i} className="p-2 rounded text-xs" style={{ background: 'var(--bg-input)' }}>
                <div className="text-primary font-medium">[{a.priority}] {a.title}</div>
                <div className="text-secondary mt-1">{a.how}</div>
                <div className="text-muted mt-1">{L.insightsRecReason}:{a.why}</div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
