// 舆情品牌设置页 — 已迁移到账户中心 /account/brand.
// 保留路由兼容:访问 /sentiment/settings 自动重定向.
import { Navigate } from 'react-router-dom';

export function SettingsPage() {
  return <Navigate to="/account/brand" replace />;
}
