import { useEffect, useState } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { authApi } from '../../services/authApi';
import { useAuthModal } from '../../contexts/AuthModalContext';
import { useAuth } from '../../contexts/AuthContext';

export function AccountLayout() {
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

  const handleLogout = () => {
    clearAuth();
    navigate('/');
  };

  const menu = [
    { to: '/account/profile', label: t('account.menu.profile', '个人资料') },
    { to: '/account/brand', label: t('account.menu.brand', '品牌与监控') },
    { to: '/account/membership', label: t('account.menu.membership', '会员信息') },
    { to: '/account/usage', label: t('account.menu.usage', '使用情况') },
    { to: '/account/articles', label: t('account.menu.articles', '文章审核') },
    { to: '/account/integration', label: t('account.menu.integration', '对接集成') },
    { to: '/account/history', label: t('account.menu.history', '检测记录') },
    { to: '/account/payments', label: t('account.menu.payments', '支付记录') },
  ];

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
      <div className="bg-glow bg-glow-1"></div>
      <div className="bg-glow bg-glow-2"></div>
      <div className="bg-glow bg-glow-3"></div>

      <div className="md:flex relative z-10">
        <aside
          className="md:w-64 md:shrink-0 md:sticky md:top-20 md:h-[calc(100vh-5rem)] md:flex md:flex-col md:border-r"
          style={{
            borderColor: 'var(--border-color)',
            background: 'var(--bg-card)',
          }}
        >
          <div
            className="hidden md:block p-5 border-b"
            style={{ borderColor: 'var(--border-color)' }}
          >
            <p className="text-sm font-semibold truncate text-primary">
              {user?.email}
            </p>
            <p className="text-xs text-secondary mt-1">
              {t('account.layout.subtitle', '账户信息')}
            </p>
          </div>
          <nav className="p-2 md:p-3 flex md:flex-col gap-1 overflow-x-auto md:overflow-visible md:flex-1 scrollbar-hide">
            {menu.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className="px-3 py-2 rounded-lg text-sm font-medium whitespace-nowrap transition-colors flex items-center"
                style={({ isActive }) =>
                  isActive
                    ? {
                      background: 'var(--bg-tertiary)',
                      color: 'var(--accent-primary)',
                    }
                    : { color: 'var(--text-secondary)' }
                }
              >
                {item.label}
              </NavLink>
            ))}
            {/* Mobile logout button inline */}
            <button
              onClick={handleLogout}
              className="md:hidden px-3 py-2 rounded-lg text-sm font-medium whitespace-nowrap transition-colors"
              style={{ color: '#f43f5e' }}
            >
              {t('account.layout.logout', '退出登录')}
            </button>
          </nav>
          <div
            className="hidden md:block p-3 border-t"
            style={{ borderColor: 'var(--border-color)' }}
          >
            <button
              onClick={handleLogout}
              className="w-full px-3 py-2 text-sm font-medium rounded-lg transition-colors"
              style={{
                color: '#f43f5e',
                border: '1px solid rgba(244, 63, 94, 0.35)',
                background: 'transparent',
              }}
            >
              {t('account.layout.logout', '退出登录')}
            </button>
          </div>
        </aside>

        <main className="flex-1 min-w-0 px-4 sm:px-6 py-8 md:py-10">
          <div className="max-w-4xl mx-auto">
            <Outlet context={{ user }} />
          </div>
        </main>
      </div>
    </div>
  );
}
