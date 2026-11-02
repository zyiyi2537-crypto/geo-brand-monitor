// 工作台(admin 专属)— 独立 sidebar.
// 非 admin 用户进入这里会被预检踢回 /dashboard.
//
// sidebar 按"admin 角色任务"组织,而非按 pipeline stage 一步步点:
//   项目进度 / 画像 / 待审批 / 监测报告 / 跑批结果
// pipeline 自动跑,admin 在项目进度页一屏看全管线,只在「待审批」介入。
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useEffect, useState } from 'react';
import { authApi } from '../../services/authApi';
import { useAuthModal } from '../../contexts/AuthModalContext';
import { useAuth } from '../../contexts/AuthContext';
import { PageHead } from '../../components/PageHead';

const sidebarItems = [
  { to: '/workbench/cockpit',        end: false, icon: 'cockpit',     labelKey: 'nav.adminCockpit' },
  { to: '/workbench/accounts',       end: false, icon: 'accounts',    labelKey: 'nav.adminAccounts' },
  { to: '/workbench/content-review', end: false, icon: 'docs',        labelKey: 'nav.adminContentReview' },
  { to: '/workbench/platform-rules', end: false, icon: 'docs',        labelKey: 'nav.adminPlatformRules' },
  { to: '/workbench/insights',       end: false, icon: 'insights',    labelKey: 'nav.adminInsights' },
  { to: '/workbench/runs',           end: false, icon: 'runs',        labelKey: 'nav.adminRuns' },
  { to: '/workbench/crawl',          end: false, icon: 'crawl',       labelKey: 'nav.adminCrawl' },
  { to: '/workbench/workers',        end: false, icon: 'workers',     labelKey: 'nav.adminWorkers' },
  { to: '/workbench/gateway',        end: false, icon: 'workers',     labelKey: 'nav.adminGateway' },
] as const;

function SidebarIcon({ name }: { name: string }) {
  // 项目进度:仪表盘
  if (name === 'cockpit') {
    return (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
      </svg>
    );
  }
  // 画像:用户组
  if (name === 'accounts') {
    return (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" />
      </svg>
    );
  }
  // 文案复审:文档
  if (name === 'docs') {
    return (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
      </svg>
    );
  }
  // 监测报告:折线图
  if (name === 'insights') {
    return (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
      </svg>
    );
  }
  // 跑批结果:齿轮
  if (name === 'runs') {
    return (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
      </svg>
    );
  }
  // AI 爬虫分析:机器人/雷达
  if (name === 'crawl') {
    return (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h.01M15 9h.01M9.5 13a3.5 3.5 0 005 0" />
      </svg>
    );
  }
  // 调度中心 / Worker:服务器堆叠
  if (name === 'workers') {
    return (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M5 4h14a1 1 0 011 1v4a1 1 0 01-1 1H5a1 1 0 01-1-1V5a1 1 0 011-1zM5 14h14a1 1 0 011 1v4a1 1 0 01-1 1H5a1 1 0 01-1-1v-4a1 1 0 011-1zM8 7h.01M8 17h.01" />
      </svg>
    );
  }
  return null;
}

export function WorkbenchLayout() {
  const navigate = useNavigate();
  const { openAuthModal } = useAuthModal();
  const { t } = useTranslation();
  const { user, setUser, clearAuth } = useAuth();
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem('token');
    if (!token) {
      openAuthModal('login');
      navigate('/', { replace: true });
      return;
    }
    let cancelled = false;
    authApi
      .getCurrentUser(token)
      .then((u) => {
        if (cancelled) return;
        if (!u.is_admin) {
          // 非 admin 进 /workbench 直接踢回 /dashboard
          navigate('/dashboard', { replace: true });
          return;
        }
        setUser(u);
      })
      .catch(() => {
        clearAuth();
        openAuthModal('login');
        navigate('/', { replace: true });
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [navigate, openAuthModal, setUser, clearAuth]);

  if (loading) {
    return (
      <div className="min-h-screen grid-background flex items-center justify-center">
        <div
          className="animate-spin rounded-full h-10 w-10 border-t-2 border-b-2"
          style={{ borderColor: 'var(--accent-primary)' }}
        />
      </div>
    );
  }

  if (!user) return null;

  return (
    <div className="min-h-[calc(100vh-5rem)] grid-background relative">
      <PageHead
        titleKey="dashboard.nav.adminWorkbench"
        descriptionKey="dashboard.nav.adminWorkbench"
      />
      <div className="bg-glow bg-glow-1" />
      <div className="bg-glow bg-glow-2" />
      <div className="bg-glow bg-glow-3" />

      <div className="md:flex relative z-10">
        <aside
          className="md:w-56 md:shrink-0 md:sticky md:top-16 md:h-[calc(100vh-4rem)] md:flex md:flex-col md:border-r"
          style={{
            borderColor: 'var(--border-color)',
            background: 'var(--bg-card)',
          }}
        >
          <div
            className="hidden md:flex items-center gap-2 p-4 border-b"
            style={{ borderColor: 'var(--border-color)' }}
          >
            <div
              className="w-8 h-8 rounded-lg flex items-center justify-center text-xs font-bold"
              style={{ background: '#ef4444', color: '#fff' }}
            >
              🛡
            </div>
            <p className="text-sm font-semibold truncate text-primary">
              {t('dashboard.nav.adminWorkbench')}
            </p>
          </div>

          <nav className="p-2 md:p-3 flex md:flex-col gap-0.5 overflow-x-auto md:overflow-visible md:flex-1 scrollbar-hide">
            {sidebarItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className="px-3 py-2 rounded-lg text-sm font-medium whitespace-nowrap transition-colors flex items-center gap-2"
                style={({ isActive }) =>
                  isActive
                    ? {
                        background: 'var(--bg-tertiary)',
                        color: 'var(--accent-primary)',
                      }
                    : { color: 'var(--text-secondary)' }
                }
              >
                <SidebarIcon name={item.icon} />
                {t(item.labelKey)}
              </NavLink>
            ))}
          </nav>
        </aside>

        <main className="flex-1 min-w-0 px-4 sm:px-6 py-6 md:py-8">
          <div className="max-w-6xl mx-auto">
            <Outlet context={{ user }} />
          </div>
        </main>
      </div>
    </div>
  );
}
