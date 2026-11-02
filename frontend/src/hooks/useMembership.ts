import { useCallback } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { membershipApi, ApiError } from '../services/membershipApi';
import { useAuth } from '../contexts/AuthContext';

interface UserMembership {
  id: number;
  user_id: number;
  membership_id: number;
  start_date: string;
  end_date: string;
  is_active: boolean;
}

/**
 * Shared logout helper — delegates to AuthContext.clearAuth via a
 * component-captured closure. Kept as a re-export convenience for code that
 * already imports from this module.
 *
 * NOTE: can only be called from within a React component (via the hook
 * returned value). If non-React code needs to clear auth, it should import
 * useAuth directly or the caller needs to propagate a callback.
 *
 * @deprecated Prefer `useAuth().clearAuth()` directly in new code.
 */
export function useClearStoredAuth(): () => boolean {
  const { token, clearAuth } = useAuth();
  return useCallback(() => {
    if (!token) return false;
    clearAuth();
    return true;
  }, [token, clearAuth]);
}

export function useMembership() {
  // Token 现在来自 AuthContext,全局单一真相。任何 setToken / clearAuth
  // 调用都会触发所有消费 useMembership 的组件重渲染。修掉了 TierModal 等
  // 常驻组件"登录了但 state 不同步"的 bug。
  const { token, isLoggedIn, clearAuth } = useAuth();
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery<UserMembership | null>({
    queryKey: ['user-membership', token],
    queryFn: async () => {
      if (!token) return null;
      try {
        return await membershipApi.getUserMembership(token);
      } catch (err) {
        // Zombie-login killer: token 被后端拒(401/403),清掉存储以免 UI
        // 继续假装"已登录"。其他错误(网络、5xx、解析)保留 token,下次
        // 刷新再试,不要无故踢用户下线。
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
          clearAuth();
        }
        return null;
      }
    },
    enabled: !!token,
    staleTime: 60_000,
    retry: false,
  });

  const refresh = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['user-membership'] });
  }, [queryClient]);

  return {
    token,
    isLoggedIn,
    // `id === 0` is the backend's sentinel for a synthesized free-tier row
    // (no real `user_memberships` record exists — logged-in free users always
    // get one of these). A real paid subscription has a positive PK. Treating
    // the sentinel as "unlocked" would let free users bypass the paywall.
    isUnlocked: !!(data && data.is_active && data.id > 0),
    isLoading,
    refresh,
  };
}
