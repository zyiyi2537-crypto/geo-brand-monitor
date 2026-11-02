// 7 天情感堆叠柱 — 纯 SVG,无外部图表依赖。
import { useTranslation } from 'react-i18next';

interface Row {
  date: string;
  bullish: number;
  neutral: number;
  bearish: number;
  mixed: number;
}

const COLORS = {
  bullish: '#16a34a',
  neutral: '#94a3b8',
  bearish: '#dc2626',
  mixed:   '#7c3aed',
};

const cardStyle: React.CSSProperties = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border-color)',
};

export function SentimentChart({ data }: { data: Row[] }) {
  const { t } = useTranslation();

  const maxTotal = Math.max(...data.map(r => r.bullish + r.neutral + r.bearish + r.mixed), 1);
  const W = 100;          // viewBox 宽
  const H = 60;           // viewBox 高
  const barW = W / data.length * 0.7;
  const gap = W / data.length * 0.3;

  const keys: (keyof Row)[] = ['bullish', 'neutral', 'mixed', 'bearish'];

  return (
    <section className="rounded-xl p-5 flex-1 flex flex-col min-w-0 w-full" style={cardStyle}>
      <header className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-primary uppercase tracking-wide">
          {t('dashboard.sentiment.today.sentimentTrend')}
        </h3>
        <div className="flex items-center gap-3 text-[11px] text-muted">
          {keys.map(k => (
            <span key={k} className="flex items-center gap-1">
              <span className="inline-block w-2.5 h-2.5 rounded-sm" style={{ background: COLORS[k as keyof typeof COLORS] }} />
              {t(`dashboard.sentiment.articles.labels.${k}`)}
            </span>
          ))}
        </div>
      </header>

      {/* 顶部 flex-1 spacer:section 用 items-stretch 时,把柱子推到卡片下半段,
         而 chart 容器本身固定高度,避免 SVG `preserveAspectRatio=none` 把柱子
         随容器一起垂直拉伸成"高瘦怪". */}
      <div className="flex-1" />

      {/* chart 区:固定 h-56 (224px),svg 等比铺满这块区域. */}
      <div className="relative h-56">
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="w-full h-full">
          {data.map((row, i) => {
            const total = row.bullish + row.neutral + row.bearish + row.mixed;
            const x = i * (W / data.length) + gap / 2;
            let y = H;
            return (
              <g key={row.date}>
                {keys.map(k => {
                  const val = row[k] as number;
                  const h = (val / maxTotal) * H;
                  y -= h;
                  return (
                    <rect
                      key={k}
                      x={x}
                      y={y}
                      width={barW}
                      height={h}
                      fill={COLORS[k as keyof typeof COLORS]}
                    >
                      <title>{`${row.date} ${k}: ${val} (${total} 总)`}</title>
                    </rect>
                  );
                })}
              </g>
            );
          })}
        </svg>
      </div>
      {/* x 轴标签 — 放在 chart 容器外,避免贴底 */}
      <div className="flex justify-between mt-2 pb-1 text-[10px] text-muted px-1">
        {data.map(r => <span key={r.date} className="font-mono">{r.date}</span>)}
      </div>
    </section>
  );
}
