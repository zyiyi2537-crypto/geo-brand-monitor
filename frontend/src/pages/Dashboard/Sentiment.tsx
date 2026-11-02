// 舆情监控落地页 — 访问控制守卫 + 数据面板.
//
// 访问控制流程:
//   1. 未登录 → Navigate 到 / (首页)
//   2. 已登录但无账号 → Navigate 到 /account/brand (品牌配置页)
//   3. 已登录且有账号 → 展示数据监测面板 (4 Tabs)
//
// 数据来源:
//   VITE_USE_MOCK_SENTIMENT=1  → 走 mocks/sentiment.ts (离线 demo)
//   否则                         → useSentimentAccounts + sentimentApi (真实 API)
import { useState } from 'react';
import { useSearchParams, Link, Navigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import { useAuth } from '../../contexts/AuthContext';
import { mockAccount, timeAgo } from '../../mocks/sentiment';
import { isMockMode } from '../../services/sentimentApi';
import { useSentimentAccounts, useRunNow, useRunStatus } from '../../hooks/useSentiment';
import type { SentimentAccount } from '../../types/sentiment';
import { PageHead } from '../../components/PageHead';

import { TodayTab } from './sentiment/tabs/TodayTab';
import { ArticlesTab } from './sentiment/tabs/ArticlesTab';
import { BriefsTab } from './sentiment/tabs/BriefsTab';
import { StatusBanner, FirstRunWaiting } from './sentiment/components/StatusBanner';
import { AccountSidebar } from './sentiment/components/AccountSidebar';
import { HotTopicsPanel } from './sentiment/components/HotTopicsPanel';

type TabKey = 'today' | 'articles' | 'briefs';
const TAB_KEYS: TabKey[] = ['today', 'articles', 'briefs'];

export function Sentiment() {
  const { t } = useTranslation();
  const { isLoggedIn } = useAuth();
  const [params, setParams] = useSearchParams();
  const demo = params.get('demo');
  const usingMock = isMockMode() || demo !== null;

  const { data: accounts = [], isLoading, refetch: refetchAccounts } = useSentimentAccounts();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [mockCreated, _setMockCreated] = useState(false);

  const account: SentimentAccount | null = usingMock
    ? (demo === 'onboarding' && !mockCreated ? null : (mockAccount as SentimentAccount))
    : (accounts.find(a => a.id === (selectedId ?? accounts[0]?.id)) ?? null);

  // hooks 必须在所有 early return 之前调用 — React Rules of Hooks
  const runStatusQuery = useRunStatus(usingMock ? null : (account?.id ?? null));
  const runNowMutation = useRunNow();

  // ── 守卫 1: 未登录 → 首页 ──
  if (!usingMock && !isLoggedIn) {
    return <Navigate to="/" replace />;
  }

  // ── 加载中 ──
  if (!usingMock && isLoading) {
    return (
      <div className="min-h-[calc(100vh-5rem)] grid-background relative flex items-center justify-center">
        <div className="bg-glow bg-glow-1" />
        <div className="bg-glow bg-glow-2" />
        <div className="bg-glow bg-glow-3" />
        <div className="text-center space-y-3 relative z-10">
          <div
            className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 mx-auto"
            style={{ borderColor: 'var(--accent-primary)' }}
          />
          <p className="text-sm text-secondary">{t('common.loading') || 'Loading...'}</p>
        </div>
      </div>
    );
  }

  // ── 守卫 2: 已登录但无配置的品牌 → 品牌设置页 ──
  if (!usingMock && !account) {
    return <Navigate to="/account/brand" replace />;
  }

  // guard 2 已经处理了无账号场景,这里 account 一定存在
  const acct = account!;

  const status = demo === 'running' ? 'running'
              : demo === 'failed' ? 'failed'
              : demo === 'firstrun' ? null
              : (usingMock ? acct.last_run_status : (runStatusQuery.data?.status ?? acct.last_run_status));
  const error = demo === 'failed' ? '调用 OpenAI 时出错(429 速率限制)'
              : (usingMock ? acct.last_run_error : runStatusQuery.data?.error ?? acct.last_run_error);
  const lastRunAt = usingMock ? acct.last_run_at : (runStatusQuery.data?.last_run_at ?? acct.last_run_at);

  const tab = (params.get('tab') as TabKey) || 'today';
  const view: 'account' | 'newsnow' = params.get('view') === 'newsnow' ? 'newsnow' : 'account';
  const setTab = (k: TabKey) => {
    const next = new URLSearchParams(params);
    next.set('tab', k);
    next.delete('post');
    next.delete('view');
    setParams(next);
  };
  const selectNewsnow = () => {
    const next = new URLSearchParams(params);
    next.set('view', 'newsnow');
    next.delete('post');
    setParams(next);
  };
  const handleSelectAccount = (id: number) => {
    setSelectedId(id);
    if (params.get('view')) {
      const next = new URLSearchParams(params);
      next.delete('view');
      setParams(next);
    }
  };

  const ago = lastRunAt ? timeAgo(lastRunAt) : '';

  const handleRefresh = () => {
    runStatusQuery.refetch();
    refetchAccounts();
  };
  const handleRetry = () => {
    if (usingMock) handleRefresh();
    else if (acct.id) {
      runNowMutation.mutate(acct.id, {
        onSuccess: () => runStatusQuery.refetch(),
      });
    }
  };

  return (
    <div className="min-h-[calc(100vh-5rem)] grid-background relative">
      <PageHead titleKey="pageMeta.sentiment.title" descriptionKey="pageMeta.sentiment.description" />
      <div className="bg-glow bg-glow-1" />
      <div className="bg-glow bg-glow-2" />
      <div className="bg-glow bg-glow-3" />
      <div className="max-w-[1600px] mx-auto px-4 sm:px-6 py-6 md:py-8 relative z-10">
        <header className="flex items-center justify-between flex-wrap gap-3 mb-4">
          <h1 className="text-2xl font-bold text-primary">
            {t('dashboard.sentiment.title')}
          </h1>

          <div className="flex items-center gap-3">
            {status === 'success' && (
              <span className="text-xs text-muted">
                {t('dashboard.sentiment.status.success')} ·{' '}
                {t('dashboard.sentiment.lastUpdate', { ago })}
              </span>
            )}
            <button
              type="button"
              onClick={handleRefresh}
              className="text-xs font-semibold rounded-md px-2.5 py-1.5"
              style={{ background: 'var(--bg-tertiary)', color: 'var(--text-secondary)' }}
            >
              {t('dashboard.sentiment.refresh')}
            </button>
            <Link
              to="/account/brand"
              className="text-xs font-semibold rounded-md px-3 py-1.5"
              style={{ background: 'var(--bg-tertiary)', color: 'var(--text-primary)' }}
            >
              {t('dashboard.sentiment.settingsLink')}
            </Link>
          </div>
        </header>

        {/* 主体 2 列布局:左侧账户树 + 右侧 Tab 区. 移动端单列堆叠. */}
        <div className="grid grid-cols-1 xl:grid-cols-[220px_minmax(0,1fr)] gap-4">
          <AccountSidebar
            accounts={usingMock ? [acct] : accounts}
            selectedId={acct.id}
            onSelect={handleSelectAccount}
            view={view}
            onSelectNewsnow={selectNewsnow}
          />

          <div className="space-y-4 min-w-0">
            {view === 'newsnow' ? (
              <HotTopicsPanel usingMock={usingMock} account={acct} />
            ) : (
              <>
            <StatusBanner
              status={status as never}
              error={error}
              onRefresh={handleRefresh}
              onRetry={handleRetry}
            />

            {status === null && (
              <div
                className="rounded-xl px-4 py-3 flex items-center justify-between gap-3 text-sm"
                style={{
                  background: 'rgba(59,130,246,0.10)',
                  color: '#1d4ed8',
                  border: '1px solid rgba(59,130,246,0.35)',
                }}
              >
                <span>{t('dashboard.sentiment.status.neverRun')}</span>
                <button
                  type="button"
                  onClick={handleRetry}
                  disabled={runNowMutation.isPending}
                  className="text-xs font-semibold px-2.5 py-1 rounded-md disabled:opacity-50"
                  style={{ background: 'rgba(255,255,255,0.6)', color: '#1d4ed8' }}
                >
                  {runNowMutation.isPending
                    ? t('dashboard.sentiment.status.queueing')
                    : t('dashboard.sentiment.status.runNow')}
                </button>
              </div>
            )}

            {/* 首次运行的全屏占位 — 没历史数据时才用 */}
            {(status === 'pending' || status === 'running') && !lastRunAt ? (
              <FirstRunWaiting onRefresh={handleRefresh} />
            ) : (
              <>
                <nav
                  className="flex justify-between items-end gap-3 border-b overflow-x-auto flex-wrap"
                  style={{ borderColor: 'var(--border-color)' }}
                >
                  <div className="flex gap-1">
                    {TAB_KEYS.map(k => (
                      <button
                        key={k}
                        type="button"
                        onClick={() => setTab(k)}
                        className="px-4 py-2 text-sm font-medium border-b-2 -mb-px whitespace-nowrap transition-colors"
                        style={tab === k
                          ? { borderColor: 'var(--accent-primary)', color: 'var(--accent-primary)' }
                          : { borderColor: 'transparent', color: 'var(--text-secondary)' }}
                      >
                        {t(`dashboard.sentiment.tabs.${k}`)}
                      </button>
                    ))}
                  </div>
                  {/* 子 Tab 通过 portal 把工具条渲染到这里 — 比如文章 Tab 的时间筛选 chip */}
                  <div id="sentiment-tab-toolbar" className="flex items-center gap-2 pb-2" />
                </nav>

                {tab === 'today' && <TodayTab account={acct} usingMock={usingMock} />}
                {tab === 'articles' && <ArticlesTab account={acct} usingMock={usingMock} />}
                {tab === 'briefs' && <BriefsTab account={acct} usingMock={usingMock} />}
              </>
            )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
