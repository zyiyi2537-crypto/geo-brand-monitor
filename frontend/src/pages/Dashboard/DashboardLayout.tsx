import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useEffect, useState } from 'react';
import { authApi } from '../../services/authApi';
import { useAuthModal } from '../../contexts/AuthModalContext';
import { useAuth } from '../../contexts/AuthContext';
import { PageHead } from '../../components/PageHead';

interface SidebarItem {
  to: string;
  end: boolean;
  icon: string;
  labelKey: string;
}

const sidebarItems: SidebarItem[] = [
  { to: '/dashboard', end: true, icon: 'config', labelKey: 'dashboard.nav.config' },
  // Phase D.1 — 内容 + 投放合并:一份「内容」菜单覆盖起稿 / 用户提交 / 状态查看 / 发布媒体
  { to: '/dashboard/content', end: false, icon: 'compose', labelKey: 'dashboard.nav.content' },
  // AI 遥测 = 概览 / 引用追踪 / 遥测详情(原"跑批结果")
  { to: '/dashboard/ai-telemetry', end: false, icon: 'telemetry', labelKey: 'dashboard.nav.aiTelemetry' },
  // 优化建议从原 AI 遥测 tab 提级到一级菜单
  { to: '/dashboard/insights', end: false, icon: 'insights', labelKey: 'dashboard.nav.insights' },
];

function SidebarIcon({ name }: { name: string }) {
  switch (name) {
    case 'config':
      return (
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
      );
    case 'compose':
      return (
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
        </svg>
      );
    case 'posts':
      return (
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v1m2 13a2 2 0 01-2-2V7m2 13a2 2 0 002-2V9a2 2 0 00-2-2h-2m-4-3H9M7 16h6M7 8h6v4H7V8z" />
        </svg>
      );
    case 'telemetry':
      return (
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <circle cx="12" cy="12" r="3" strokeWidth={2} />
          <circle cx="12" cy="12" r="7" strokeWidth={2} />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 5V2M12 22v-3M5 12H2M22 12h-3" />
        </svg>
      );
    case 'insights':
      return (
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
        </svg>
      );
    case 'review':
      return (
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
        </svg>
      );
    default:
      return null;
  }
}

export function DashboardLayout() {
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

  return (
    <div className="min-h-[calc(100vh-5rem)] grid-background relative">
      <PageHead
        titleKey="pageMeta.dashboard.title"
        descriptionKey="pageMeta.dashboard.description"
      />
      <div className="bg-glow bg-glow-1" />
      <div className="bg-glow bg-glow-2" />
      <div className="bg-glow bg-glow-3" />

      <div className="md:flex relative z-10">
        {/* Sidebar */}
        <aside
          className="md:w-56 md:shrink-0 md:sticky md:top-16 md:h-[calc(100vh-4rem)] md:flex md:flex-col md:border-r"
          style={{
            borderColor: 'var(--border-color)',
            background: 'var(--bg-card)',
          }}
        >
          {/* Tenant header — 只显示品牌名,邮箱在顶 Header 的账户下拉里 */}
          <div
            className="hidden md:flex items-center gap-2 p-4 border-b"
            style={{ borderColor: 'var(--border-color)' }}
          >
            <div
              className="w-8 h-8 rounded-lg flex items-center justify-center text-xs font-bold"
              style={{ background: 'var(--accent-primary)', color: 'var(--solid-btn-text)' }}
            >
              {user?.email?.charAt(0).toUpperCase() ?? 'U'}
            </div>
            <p className="text-sm font-semibold truncate text-primary">
              {t('dashboard.title')}
            </p>
          </div>

          {/* Nav items */}
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

        {/* Main content */}
        <main className="flex-1 min-w-0 px-4 sm:px-6 py-6 md:py-8">
          <div className="max-w-6xl mx-auto">
            <Outlet context={{ user }} />
          </div>
        </main>
      </div>
    </div>
  );
}
