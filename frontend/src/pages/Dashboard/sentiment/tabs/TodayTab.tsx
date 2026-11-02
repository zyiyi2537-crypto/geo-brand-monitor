import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import {
  mockKpi, mockSentimentTrend, mockRiskDist, mockBriefs, mockPosts,
} from '../../../../mocks/sentiment';
import { useTodayData } from '../../../../hooks/useSentiment';
import type { SentimentAccount, SentimentPost } from '../../../../types/sentiment';

import { KpiCards } from '../components/KpiCards';
import { SentimentChart } from '../components/SentimentChart';
import { RiskPie } from '../components/RiskPie';
import { BriefRenderer } from '../components/BriefRenderer';
import { PostCard } from '../components/PostCard';

const cardStyle: React.CSSProperties = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border-color)',
};

interface Props {
  account: SentimentAccount;
  usingMock?: boolean;
}

/** influence × |sentiment| 排序(yuqin chat agent top_posts SQL 同款公式)*/
function noteworthy(p: SentimentPost): number {
  return (p.influence_potential ?? 0) * Math.abs(p.sentiment_score ?? 0);
}

export function TodayTab({ account, usingMock }: Props) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const ticker = account.ticker;

  // 真实模式拉数据;mock 模式 enabled=false 不发请求
  const { data, isLoading, error } = useTodayData(
    usingMock ? null : account.id,
    usingMock ? null : ticker,
  );

  // mock 模式:从静态 fixture 拼一份 today payload
  const today = usingMock
    ? {
        kpi: mockKpi,
        sentiment_trend: mockSentimentTrend,
        risk_dist: mockRiskDist,
        latest_brief: mockBriefs[0],
        top_posts: [...(mockPosts as SentimentPost[])]
          .filter(p => p.is_relevant)
          .sort((a, b) => noteworthy(b) - noteworthy(a))
          .slice(0, 5),
      }
    : data;

  if (!usingMock && isLoading) {
    return <SkeletonCard label={t('common.loading') || 'Loading...'} />;
  }
  if (!usingMock && error) {
    return <ErrorCard message={error instanceof Error ? error.message : 'Failed to load'} />;
  }
  if (!today) {
    return <SkeletonCard label="暂无数据" />;
  }

  return (
    <div className="space-y-4">
      <KpiCards data={today.kpi} />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 items-stretch">
        <div className="lg:col-span-2 flex">
          <SentimentChart data={today.sentiment_trend} />
        </div>
        <div className="flex">
          <RiskPie data={today.risk_dist} />
        </div>
      </div>

      {/* 今日简报内联 */}
      <section className="rounded-xl p-5" style={cardStyle}>
        <header className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-semibold text-primary uppercase tracking-wide">
            {t('dashboard.sentiment.today.latestBrief')}
          </h3>
          <button
            type="button"
            onClick={() => navigate('/sentiment?tab=briefs')}
            className="text-xs font-semibold"
            style={{ color: 'var(--accent-primary)' }}
          >
            {t('dashboard.sentiment.today.viewFull')}
          </button>
        </header>
        {today.latest_brief ? (
          <BriefRenderer body={today.latest_brief.body} maxLines={30} />
        ) : (
          <p className="text-sm text-secondary">尚无简报。</p>
        )}
      </section>

      {/* 高风险帖 Top 5 */}
      <section className="rounded-xl p-5" style={cardStyle}>
        <h3 className="text-sm font-semibold text-primary uppercase tracking-wide mb-3">
          {t('dashboard.sentiment.today.topRisk')}
        </h3>
        {today.top_posts.length === 0 ? (
          <p className="text-sm text-secondary">尚无高风险帖。</p>
        ) : (
          <div className="space-y-2">
            {today.top_posts.map((p) => (
              <button
                key={`${p.source}-${p.post_id}`}
                type="button"
                onClick={() => navigate(`/sentiment?tab=articles&post=${p.source}-${p.post_id}`)}
                className="w-full text-left"
              >
                <PostCard post={p} compact />
              </button>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function SkeletonCard({ label }: { label: string }) {
  return (
    <div className="rounded-xl py-12 text-center text-secondary text-sm" style={cardStyle}>
      {label}
    </div>
  );
}

function ErrorCard({ message }: { message: string }) {
  return (
    <div
      className="rounded-xl py-6 px-4 text-sm"
      style={{
        background: 'rgba(239,68,68,0.1)',
        color: '#dc2626',
        border: '1px solid rgba(239,68,68,0.3)',
      }}
    >
      ⚠ {message}
    </div>
  );
}
