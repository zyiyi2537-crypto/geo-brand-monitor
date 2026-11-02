/**
 * 路由切换时把窗口滚动到顶部。React Router 不会主动重置滚动位置——
 * 上一个页面滚到底部后跳过去,下一个页面会带着同一个 scrollY 渲染,
 * 看起来像「卡在底部」需要手动滑回顶部。
 *
 * 仅在 pathname 变化时重置;同路径下 search/hash 变化不重置,避免
 * 用 ?tab=xxx 在同页切 tab 时把视口顶飞。带 hash(#anchor)的链接
 * 也跳过,交给浏览器原生锚点滚动行为。
 */
import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';

export function ScrollToTop() {
  const { pathname, hash } = useLocation();

  useEffect(() => {
    if (hash) return;
    window.scrollTo({ top: 0, left: 0, behavior: 'auto' });
  }, [pathname, hash]);

  return null;
}
