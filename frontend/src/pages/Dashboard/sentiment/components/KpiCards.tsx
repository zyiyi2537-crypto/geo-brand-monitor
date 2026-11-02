import { useState } from 'react';
import { useTranslation } from 'react-i18next';

interface KpiData {
  total_today: number;
  high_risk: number;
  avg_sentiment: number;
  active_sources: number;
  trend_total_pct: number;
  trend_risk_pct: number;
  trend_sentiment_pct: number;
}

const cardStyle: React.CSSProperties = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border-color)',
};

export function KpiCards({ data }: { data: KpiData }) {
  const { t } = useTranslation();
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 sm:gap-4">
      <Card
        label={t('dashboard.sentiment.today.kpi.total')}
        tip={t('dashboard.sentiment.today.kpi.tipTotal')}
        value={data.total_today.toLocaleString()}
        delta={data.trend_total_pct}
        deltaLabel={t('dashboard.sentiment.today.kpi.vsYesterday')}
      />
      <Card
        label={t('dashboard.sentiment.today.kpi.highRisk')}
        tip={t('dashboard.sentiment.today.kpi.tipHighRisk')}
        value={data.high_risk.toString()}
        delta={data.trend_risk_pct}
        deltaLabel={t('dashboard.sentiment.today.kpi.vsYesterday')}
        valueColor={data.high_risk > 0 ? '#dc2626' : undefined}
      />
      <Card
        label={t('dashboard.sentiment.today.kpi.avgSentiment')}
        tip={t('dashboard.sentiment.today.kpi.tipAvgSentiment')}
        value={(data.avg_sentiment >= 0 ? '+' : '') + Math.round(data.avg_sentiment * 100) + '%'}
        delta={data.trend_sentiment_pct}
        deltaLabel={t('dashboard.sentiment.today.kpi.vsYesterday')}
        valueColor={data.avg_sentiment < 0 ? '#dc2626' : '#16a34a'}
      />
      <Card
        label={t('dashboard.sentiment.today.kpi.activeSources')}
        tip={t('dashboard.sentiment.today.kpi.tipActiveSources')}
        value={data.active_sources.toString()}
      />
    </div>
  );
}

function Card({ label, tip, value, delta, deltaLabel, valueColor }: {
  label: string;
  tip?: string;
  value: string;
  delta?: number;
  deltaLabel?: string;
  valueColor?: string;
}) {
  const [showTip, setShowTip] = useState(false);
  const arrow = delta === undefined ? '' : delta > 0 ? '↑' : delta < 0 ? '↓' : '';
  const color = delta === undefined ? undefined : delta > 0 ? '#16a34a' : delta < 0 ? '#dc2626' : 'var(--text-muted)';

  const deltaText = delta === undefined ? null
    : delta === 0 ? deltaLabel
    : `${arrow} ${Math.abs(delta)}% ${deltaLabel}`;

  return (
    <div className="rounded-xl p-4 relative" style={cardStyle}>
      <p className="text-xs text-secondary mb-1 flex items-center gap-1">
        {label}
        {tip && (
          <span
            className="inline-flex items-center justify-center w-3.5 h-3.5 rounded-full text-[10px] cursor-help select-none shrink-0"
            style={{ background: 'var(--bg-tertiary)', color: 'var(--text-muted)' }}
            onMouseEnter={() => setShowTip(true)}
            onMouseLeave={() => setShowTip(false)}
          >
            ?
          </span>
        )}
      </p>
      <p className="text-2xl font-bold tabular-nums" style={{ color: valueColor || 'var(--text-primary)' }}>
        {value}
      </p>
      {deltaText && (
        <p className="text-[11px] mt-1" style={{ color }}>
          {deltaText}
        </p>
      )}
      {showTip && tip && (
        <div
          className="absolute z-20 left-3 right-3 rounded-lg px-3 py-2 text-xs leading-relaxed shadow-lg"
          style={{
            top: 'calc(100% + 4px)',
            background: 'var(--bg-card)',
            border: '1px solid var(--border-color)',
            color: 'var(--text-secondary)',
          }}
        >
          {tip}
        </div>
      )}
    </div>
  );
}
