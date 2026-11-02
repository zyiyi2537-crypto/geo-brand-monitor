// 风险等级分布饼图 — 纯 SVG。
import { useTranslation } from 'react-i18next';
import type { RiskLevel } from '../../../../mocks/sentiment';

interface Slice {
  level: RiskLevel;
  count: number;
  color: string;
}

const cardStyle: React.CSSProperties = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border-color)',
};

export function RiskPie({ data }: { data: Slice[] }) {
  const { t } = useTranslation();
  const total = data.reduce((s, x) => s + x.count, 0) || 1;

  // 用 stroke-dasharray 画环形图,centred 在 50,50,半径 40,周长 ~251.3
  const R = 40;
  const C = 2 * Math.PI * R;
  // 预计算每段 offset,避免 render 中可变状态
  const segments = data.reduce<{ slice: Slice; dash: number; offset: number }[]>(
    (acc, s) => {
      const dash = (s.count / total) * C;
      const offset = -acc.reduce((sum, x) => sum + x.dash, 0);
      acc.push({ slice: s, dash, offset });
      return acc;
    },
    [],
  );

  // 最高风险条目（不含 none）
  const riskItems = data.filter(s => s.level !== 'none');
  const riskCount = riskItems.reduce((s, x) => s + x.count, 0);
  const maxSlice = riskItems.length > 0
    ? riskItems.reduce((a, b) => a.count > b.count ? a : b)
    : null;

  return (
    <section className="rounded-xl p-5 flex-1 flex flex-col min-w-0 w-full" style={cardStyle}>
      <h3 className="text-sm font-semibold text-primary uppercase tracking-wide mb-3">
        {t('dashboard.sentiment.today.riskDist')}
      </h3>

      {/* 环形图 + 中心数字 */}
      <div className="flex items-center justify-center mb-4">
        <div className="relative">
          <svg viewBox="0 0 100 100" width={130} height={130} style={{ transform: 'rotate(-90deg)' }}>
            <circle cx="50" cy="50" r={R} fill="none" stroke="var(--bg-tertiary)" strokeWidth="14" />
            {segments.map(({ slice: s, dash, offset }) => (
              <circle
                key={s.level}
                cx="50" cy="50" r={R}
                fill="none"
                stroke={s.color}
                strokeWidth="14"
                strokeDasharray={`${dash} ${C}`}
                strokeDashoffset={offset}
              >
                <title>{`${s.level}: ${s.count} (${((s.count/total)*100).toFixed(0)}%)`}</title>
              </circle>
            ))}
          </svg>
          {/* 中心总计 */}
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-lg font-bold text-primary leading-none">{total}</span>
            <span className="text-[10px] text-muted mt-0.5">总帖数</span>
          </div>
        </div>
      </div>

      {/* 各等级明细 + 百分比条 */}
      <ul className="space-y-2.5 text-xs">
        {data.map(s => {
          const pct = (s.count / total) * 100;
          return (
            <li key={s.level}>
              <div className="flex items-center justify-between mb-0.5">
                <span className="flex items-center gap-1.5">
                  <span className="inline-block w-2.5 h-2.5 rounded-sm" style={{ background: s.color }} />
                  <span className="text-secondary">{t(`dashboard.sentiment.articles.risk.${s.level}`)}</span>
                </span>
                <span className="font-mono tabular-nums text-primary">
                  {s.count} <span className="text-muted">({pct.toFixed(0)}%)</span>
                </span>
              </div>
              <div className="w-full h-1.5 rounded-full" style={{ background: 'var(--bg-tertiary)' }}>
                <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, background: s.color }} />
              </div>
            </li>
          );
        })}
      </ul>

      {/* 底部风险摘要 */}
      <div className="mt-3 pt-3 text-[11px] text-muted" style={{ borderTop: '1px solid var(--border-color)' }}>
        {riskCount > 0 ? (
          <span>
            共 <span className="font-semibold text-primary">{riskCount}</span> 条风险帖
            {maxSlice && (
              <>，<span style={{ color: maxSlice.color }} className="font-semibold">
                {t(`dashboard.sentiment.articles.risk.${maxSlice.level}`)}
              </span> 最多</>
            )}
          </span>
        ) : (
          <span>当前无风险帖</span>
        )}
      </div>
    </section>
  );
}
