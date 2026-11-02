import { Navigate } from 'react-router-dom';

export function ContentRedirect() {
  const userRaw = localStorage.getItem('user');
  let isAdmin = false;
  try {
    const u = userRaw ? JSON.parse(userRaw) : null;
    isAdmin = Boolean(u?.is_admin);
  } catch {
    isAdmin = false;
  }
  return <Navigate to={isAdmin ? '/workbench/content-management' : '/brand-growth/published'} replace />;
}
