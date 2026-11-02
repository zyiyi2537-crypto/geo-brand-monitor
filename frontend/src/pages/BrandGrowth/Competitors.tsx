import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { BrandGrowthShell, type ShellState } from './shell';
import {
  aiTelemetryApi, type ShareOfVoice, type CompetitorSubstitutionResp,
  type CompetitorSubstitutionItem,
} from '../../services/aiTelemetryApi';
import {
  DonutChart, DonutLegend, HorizontalBarChart, InfoHint, CHART_PALETTE,
  type DonutSlice, type BarItem,
} from './charts';
import { useBgLang } from './lang';

export function Competitors() {
  const L = useBgLang();
  return (
    <BrandGrowthShell title={L.competitorsTitle} breadcrumb={[{ label: L.pageTitle, to: '/brand-growth' }]}>
      {(state) => <Body state={state} />}
    </BrandGrowthShell>
  );
}

function Body({ state }: { state: ShellState }) {
  const { token, topic, period } = state;
  const L = useBgLang();
  const [sov, setSov] = useState<ShareOfVoice | null>(null);
  const [subs, setSubs] = useState<CompetitorSubstitutionResp | null>(null);
  const [selectedComp, setSelectedComp] = useState<string | null>(null);

  useEffect(() => {
    if (!topic) return;
    aiTelemetryApi.getShareOfVoice(topic.id, period, token).then(setSov).catch(() => setSov(null));
    aiTelemetryApi.getCompetitorSubstitutions(topic.id, period, token, { limit: 100 })
      .then(setSubs).catch(() => setSubs(null));
  }, [token, topic?.id, period]);

  if (!topic) return null;

  const filteredItems = selectedComp
    ? (subs?.items ?? []).filter(i => i.competitor_name === selectedComp)
    : (subs?.items ?? []);

  const saivSlices: DonutSlice[] = sov && (sov.brand_count + sov.competitors_count_total) > 0
    ? [
        { label: L.competitorsBrand(sov.target), value: sov.brand_count, color: '#3b82f6' },
        { label: L.competitorsRivalsTotal, value: sov.competitors_count_total, color: '#94a3b8' },
      ]
    : [];

  const compBars: BarItem[] = (sov?.competitors ?? []).slice(0, 10).map((c, i) => ({
    label: c.name, value: c.count, color: CHART_PALETTE[i % CHART_PALETTE.length],
  }));

  return (
    <div className="grid gap-4">
      {sov && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Card title={L.competitorsSaiv} hint={L.hintCompetitors}>
            {saivSlices.length === 0 ? (
              <div className="text-xs text-muted py-10 text-center">{L.sourcesNoData}</div>
            ) : (
              <div className="grid grid-cols-[auto_1fr] gap-4 items-center flex-1">
                <DonutChart
                  slices={saivSlices}
                  centerText={`${sov.saiv_pct.toFixed(1)}%`}
                  centerSub={L.competitorsSaivCenter}
                />
                <div className="space-y-3">
                  <DonutLegend slices={saivSlices} />
                  <div className="pt-3 border-t text-xs" style={{ borderColor: 'var(--border-color)' }}>
                    <div className="flex justify-between mb-1">
                      <span className="text-muted flex items-center gap-1.5">
                        {L.competitorsPositionDist}
                        <InfoHint text={L.hintCompetitorsPosition} />
                      </span>
                    </div>
                    <PositionMiniBar sov={sov} />
                  </div>
                </div>
              </div>
            )}
          </Card>
          <Card title={L.competitorsTopList} hint={L.hintCompetitorsTop}>
            {compBars.length === 0 ? (
              <div className="text-xs text-muted py-10 text-center">{L.competitorsSubsEmpty}</div>
            ) : (
              <HorizontalBarChart items={compBars} formatValue={v => `${v}`} />
            )}
            {sov.competitors.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {sov.competitors.slice(0, 10).map(c => (
                  <button
                    key={c.name} type="button"
                    onClick={() => setSelectedComp(selectedComp === c.name ? null : c.name)}
                    className="text-xs px-2 py-0.5 rounded hover:underline"
                    style={{
                      background: selectedComp === c.name ? 'var(--accent-primary)' : 'var(--bg-input)',
                      color: selectedComp === c.name ? 'white' : 'var(--accent-primary)',
                    }}
                  >
                    {c.name}
                  </button>
                ))}
              </div>
            )}
          </Card>
        </div>
      )}

      <Card title={L.competitorsSubstitutions(selectedComp)} hint={L.hintCompetitorsSubs}
        action={selectedComp && (
          <button type="button" className="text-xs text-muted hover:text-primary"
            onClick={() => setSelectedComp(null)}>{L.clearFilter}</button>
        )}>
        {filteredItems.length === 0 ? (
          <div className="text-xs text-muted text-center py-6">{L.competitorsSubsEmpty}</div>
        ) : (
          <SubstitutionTable items={filteredItems} topicId={topic.id} />
        )}
      </Card>
    </div>
  );
}

function PositionMiniBar({ sov }: { sov: ShareOfVoice }) {
  const L = useBgLang();
  const { lead, body, tail, unknown } = sov.position_dist;
  const total = lead + body + tail + unknown;
  if (total === 0) return <div className="text-[10px] text-muted">{L.responsesMiss}</div>;
  const segs = [
    { k: 'lead', v: lead, color: '#10b981', label: L.posLead },
    { k: 'body', v: body, color: '#3b82f6', label: L.posBody },
    { k: 'tail', v: tail, color: '#f59e0b', label: L.posTail },
    { k: 'unknown', v: unknown, color: '#64748b', label: L.posUnknown },
  ];
  return (
    <div>
      <div className="flex h-2 rounded overflow-hidden" style={{ background: 'var(--bg-input)' }}>
        {segs.map(s => s.v > 0 && (
          <div key={s.k} style={{ width: `${s.v / total * 100}%`, background: s.color }} />
        ))}
      </div>
      <div className="flex justify-between mt-1.5 text-[10px] text-muted">
        {segs.filter(s => s.v > 0).map(s => (
          <span key={s.k}>
            <span className="inline-block w-1.5 h-1.5 mr-1 align-middle rounded-sm" style={{ background: s.color }} />
            {s.label} {s.v}
          </span>
        ))}
      </div>
    </div>
  );
}

function Card({ title, action, hint, children }: {
  title: string; action?: React.ReactNode; hint?: string; children: React.ReactNode;
}) {
  return (
    <div className="p-4 rounded-lg flex flex-col"
      style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
      <div className="flex items-center justify-between mb-3 pb-2 border-b"
        style={{ borderColor: 'var(--border-color)' }}>
        <h3 className="text-sm font-medium text-primary flex items-center gap-2">
          <span className="w-1 h-4 rounded-sm" style={{ background: 'var(--accent-primary)' }} />
          {title}
          {hint && <InfoHint text={hint} />}
        </h3>
        {action}
      </div>
      <div className="flex-1 flex flex-col">{children}</div>
    </div>
  );
}

function SubstitutionTable({ items, topicId }: { items: CompetitorSubstitutionItem[]; topicId: number }) {
  const navigate = useNavigate();
  const L = useBgLang();
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-muted">
          <th className="text-left px-2 py-1.5">{L.competitorsSubColQuery}</th>
          <th className="text-left px-2 py-1.5">{L.competitorsSubColRival}</th>
          <th className="text-right px-2 py-1.5">{L.competitorsSubColCount}</th>
          <th className="text-left px-2 py-1.5">{L.competitorsSubColEvidence}</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {items.slice(0, 50).map((i, idx) => (
          <tr key={idx} className="border-t" style={{ borderColor: 'var(--border-color)' }}>
            <td className="px-2 py-1.5 text-primary">{i.query}</td>
            <td className="px-2 py-1.5 text-primary">{i.competitor_name}</td>
            <td className="px-2 py-1.5 text-right tabular-nums">{i.competitor_count}</td>
            <td className="px-2 py-1.5 text-secondary truncate max-w-[260px]">{i.sample_snippet}</td>
            <td className="px-2 py-1.5">
              <button
                type="button"
                onClick={() => navigate(`/brand-growth/matrix?topic=${topicId}&q=${encodeURIComponent(i.query)}`)}
                className="text-xs text-accent hover:underline"
              >
                {L.competitorsSubViewMatrix}
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
