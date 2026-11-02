/**
 * AuthContext — 全局唯一的 JWT token + 用户档案状态源。
 *
 * 背景(bug 修复):原来每个 `useMembership()` 消费者有自己的 React state,
 * 初始化时从 localStorage 读一次,之后不再同步。结果:
 *   - <TierModal /> 在 App 根节点常驻,从应用启动就 mount
 *   - 用户注册后 localStorage 写入新 token
 *   - Register.tsx 不调 refresh(甚至不用 useMembership)
 *   - TierModal 的 token state 永远卡在 null → isLoggedIn=false
 *   - 用户选套餐 → 再次弹登录框
 *
 * 二次修复(2026-05-25):Header 的右上角登录状态在弹窗登录后不刷新。
 * 原因:Header 自己用 useState 维护 `user` / `isAdmin`,只靠
 * `useEffect([isLoggedIn])` 和 `storage` 事件做同步。但:
 *   - 同源 tab 内 `localStorage.setItem` 不会触发本 tab 的 `storage` 事件
 *   - 若 token 在 mount 时就已存在(刷新 / 残留 token),isLoggedIn 不变,
 *     `useEffect([isLoggedIn])` 不会重跑
 *   - persistUser 失败时(/me 抛错),catch 兜底写 {email},但 Header
 *     不接受 is_admin 缺失之外的别的失败路径
 * 现在把 user / isAdmin 一并搬进 AuthContext,作为单一真相;Header 直接
 * 消费,AuthModal / AccountLayout / DashboardLayout / WorkbenchLayout 改走
 * `setUser` 写入,Context 自动更新所有消费者。
 *
 * 新的设计:
 *   - token + user 都只在 AuthProvider 一个地方维护 React state
 *   - 所有 useAuth() 通过 Context 消费,单一真相
 *   - 写 token 一律走 `setToken(x)`,写 user 走 `setUser(u)`,Context
 *     负责同步 localStorage
 *   - AuthProvider 挂 `storage` 事件监听,跨 tab 登录/退出也能同步
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

export interface StoredUser {
  id?: number;
  email: string;
  name?: string | null;
  is_active?: boolean;
  is_admin?: boolean;
}

interface AuthContextValue {
  /** 当前 JWT,未登录时为 null。 */
  token: string | null;
  /** 为 !!token 的便捷别名。 */
  isLoggedIn: boolean;
  /** 当前用户 profile;未登录或 profile 缺失时为 null。 */
  user: StoredUser | null;
  /** user?.is_admin 的便捷别名,默认 false。 */
  isAdmin: boolean;
  /** 登录/注册成功后写入 token。传 null 表示退出。会同步 localStorage。 */
  setToken: (t: string | null) => void;
  /** 写入/清除 user profile,同步 localStorage 并立即通知所有消费者。 */
  setUser: (u: StoredUser | null) => void;
  /** 清空所有登录痕迹(token + user)。 */
  clearAuth: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

const TOKEN_KEY = 'token';
const USER_KEY = 'user';

function readStoredUser(): StoredUser | null {
  try {
    const raw = localStorage.getItem(USER_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return null;
    return parsed as StoredUser;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(() => {
    try {
      return localStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  });

  const [user, setUserState] = useState<StoredUser | null>(() => readStoredUser());

  const setToken = useCallback((t: string | null) => {
    try {
      if (t) {
        localStorage.setItem(TOKEN_KEY, t);
      } else {
        localStorage.removeItem(TOKEN_KEY);
      }
    } catch {
      // 存储失败不能让业务挂掉,state 仍然更新
    }
    setTokenState(t);
  }, []);

  const setUser = useCallback((u: StoredUser | null) => {
    try {
      if (u) {
        localStorage.setItem(USER_KEY, JSON.stringify(u));
      } else {
        localStorage.removeItem(USER_KEY);
      }
    } catch {
      // ignore
    }
    setUserState(u);
  }, []);

  const clearAuth = useCallback(() => {
    try {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
    } catch {
      // ignore
    }
    setTokenState(null);
    setUserState(null);
  }, []);

  // 跨 tab 同步:用户在 A tab 登录,B tab 也要看到。
  // 浏览器 `storage` 事件只在**其他 tab**触发,所以不会和本 tab 的
  // setToken/setUser 形成循环。
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === TOKEN_KEY) {
        setTokenState(e.newValue);
      } else if (e.key === USER_KEY) {
        setUserState(readStoredUser());
      }
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      token,
      isLoggedIn: !!token,
      user,
      isAdmin: !!user?.is_admin,
      setToken,
      setUser,
      clearAuth,
    }),
    [token, user, setToken, setUser, clearAuth],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used within <AuthProvider>. Wrap your app in AuthProvider at the top level.');
  }
  return ctx;
}
