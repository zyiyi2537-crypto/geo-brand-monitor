import { lazy, Suspense } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, useParams } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { HelmetProvider } from 'react-helmet-async';
import { Header } from './components/Header';
import { Footer } from './components/Footer';
import { ScrollToTop } from './components/ScrollToTop';
import { ContactModalProvider } from './components/ContactModalContext';
import { ContactModal } from './components/ContactModal';
import { TierModalProvider } from './components/TierModalContext';
import { TierModal } from './components/TierModal';
import { AuthProvider } from './contexts/AuthContext';
import { AuthModalProvider } from './contexts/AuthModalContext';
import { AgentChatWidget } from './components/AgentChat/AgentChatWidget';

// Eagerly loaded: Home is the landing page
import { Home } from './pages/Home';

// Lazy loaded: everything else
const Landing = lazy(() => import('./pages/Landing').then(m => ({ default: m.Landing })));
const Result = lazy(() => import('./pages/Result').then(m => ({ default: m.Result })));
const UnifiedMonitor = lazy(() => import('./pages/UnifiedMonitor').then(m => ({ default: m.UnifiedMonitor })));
const Contact = lazy(() => import('./pages/Contact').then(m => ({ default: m.Contact })));
const GeoKnowledge = lazy(() => import('./pages/GeoKnowledge').then(m => ({ default: m.GeoKnowledge })));
const GeoKnowledgeMetrics = lazy(() => import('./pages/GeoKnowledgeMetrics').then(m => ({ default: m.GeoKnowledgeMetrics })));
const Faq = lazy(() => import('./pages/Faq').then(m => ({ default: m.Faq })));
const ProductsServices = lazy(() => import('./pages/ProductsServices').then(m => ({ default: m.ProductsServices })));
const About = lazy(() => import('./pages/About').then(m => ({ default: m.About })));
const Blog = lazy(() => import('./pages/Blog').then(m => ({ default: m.Blog })));
const BlogPost = lazy(() => import('./pages/BlogPost').then(m => ({ default: m.BlogPost })));
const Advanced = lazy(() => import('./pages/Advanced').then(m => ({ default: m.Advanced })));
const PrivacyPolicy = lazy(() => import('./pages/PrivacyPolicy').then(m => ({ default: m.PrivacyPolicy })));
const TermsOfUse = lazy(() => import('./pages/TermsOfUse').then(m => ({ default: m.TermsOfUse })));
const CookiePolicy = lazy(() => import('./pages/CookiePolicy').then(m => ({ default: m.CookiePolicy })));
const DashboardLayout = lazy(() => import('./pages/Dashboard/DashboardLayout').then(m => ({ default: m.DashboardLayout })));
const Content = lazy(() => import('./pages/Dashboard/Content').then(m => ({ default: m.Content })));
const ContentRedirect = lazy(() => import('./pages/Dashboard/ContentRedirect').then(m => ({ default: m.ContentRedirect })));
const BrandGrowth = lazy(() => import('./pages/BrandGrowth').then(m => ({ default: m.BrandGrowth })));
const BrandGrowthSources = lazy(() => import('./pages/BrandGrowth/Sources').then(m => ({ default: m.Sources })));
const BrandGrowthEngines = lazy(() => import('./pages/BrandGrowth/Engines').then(m => ({ default: m.Engines })));
const BrandGrowthCompetitors = lazy(() => import('./pages/BrandGrowth/Competitors').then(m => ({ default: m.Competitors })));
const BrandGrowthMatrix = lazy(() => import('./pages/BrandGrowth/Matrix').then(m => ({ default: m.Matrix })));
const BrandGrowthInsights = lazy(() => import('./pages/BrandGrowth/Insights').then(m => ({ default: m.Insights })));
const BrandGrowthQueries = lazy(() => import('./pages/BrandGrowth/Queries').then(m => ({ default: m.Queries })));
const BrandGrowthResponses = lazy(() => import('./pages/BrandGrowth/Responses').then(m => ({ default: m.Responses })));
const BrandGrowthPublished = lazy(() => import('./pages/BrandGrowth/Published').then(m => ({ default: m.Published })));
const AdminContentReview = lazy(() => import('./pages/Admin/ContentReview').then(m => ({ default: m.AdminContentReview })));
const AdminPlatformRules = lazy(() => import('./pages/Admin/PlatformRules').then(m => ({ default: m.AdminPlatformRules })));
const AdminAccounts = lazy(() => import('./pages/Workbench/AdminAccounts').then(m => ({ default: m.AdminAccounts })));
const AdminAccountTopics = lazy(() => import('./pages/Workbench/AdminAccountTopics').then(m => ({ default: m.AdminAccountTopics })));
const AdminTopicEdit = lazy(() => import('./pages/Workbench/AdminTopicEdit').then(m => ({ default: m.AdminTopicEdit })));
const AdminAllRuns = lazy(() => import('./pages/Workbench/AdminAllRuns').then(m => ({ default: m.AdminAllRuns })));
const AdminRunDetail = lazy(() => import('./pages/Workbench/AdminRunDetail').then(m => ({ default: m.AdminRunDetail })));
const AdminCockpit = lazy(() => import('./pages/Workbench/AdminCockpit').then(m => ({ default: m.AdminCockpit })));
const AdminInsights = lazy(() => import('./pages/Workbench/AdminInsights').then(m => ({ default: m.AdminInsights })));
const AdminCrawl = lazy(() => import('./pages/Workbench/AdminCrawl').then(m => ({ default: m.AdminCrawl })));
const AdminWorkers = lazy(() => import('./pages/Workbench/AdminWorkers').then(m => ({ default: m.AdminWorkers })));
const TopicProfile = lazy(() => import('./pages/User/TopicProfile').then(m => ({ default: m.TopicProfile })));
const WorkbenchLayout = lazy(() => import('./pages/Workbench/WorkbenchLayout').then(m => ({ default: m.WorkbenchLayout })));
const Sentiment = lazy(() => import('./pages/Dashboard/Sentiment').then(m => ({ default: m.Sentiment })));
const SentimentSettings = lazy(() => import('./pages/Dashboard/sentiment/SettingsPage').then(m => ({ default: m.SettingsPage })));


function PageLoader() {
  return (
    <div className="min-h-[60vh] flex items-center justify-center">
      <div
        className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2"
        style={{ borderColor: 'var(--accent-primary)' }}
      />
    </div>
  );
}

const queryClient = new QueryClient();

/** 单主题详情老路由(/solution /execution-plan /docs)合并到「画像」主流程,直接重定向到对应 step. */
function TopicEditRedirect({ step }: { step: number }) {
  const { topicId } = useParams();
  return <Navigate to={`/workbench/topics/${topicId}/edit?step=${step}`} replace />;
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <HelmetProvider>
      <Router>
      <AuthProvider>
      <AuthModalProvider>
      <ContactModalProvider>
      <TierModalProvider>
        {/* Outer Suspense covers Header / Footer / Modals for the brief
            moment during language switch when react-i18next flips "ready"
            state. Without this, any useTranslation component outside the
            inner route Suspense would cause the whole tree to unmount
            (white screen) when suspension bubbles past the Router. */}
        <Suspense fallback={<PageLoader />}>
        <ScrollToTop />
        <Header />
        <ContactModal />
        <TierModal />
        <div className="pt-16 min-h-screen flex flex-col">
          <Suspense fallback={<PageLoader />}>
            <Routes>
              <Route path="/" element={<Navigate to="/unified-monitor" replace />} />
              <Route path="/checker" element={<Home />} />
              <Route path="/geo-knowledge" element={<GeoKnowledge />} />
              <Route path="/geo-knowledge/metrics" element={<GeoKnowledgeMetrics />} />
              <Route path="/geo-knowledge/faq" element={<Navigate to="/faq" replace />} />
              <Route path="/faq" element={<Faq />} />
              <Route path="/products-services" element={<ProductsServices />} />
              <Route path="/account/*" element={<Navigate to="/unified-monitor" replace />} />
              <Route path="/dashboard/topics/:topicId/profile" element={<TopicProfile />} />
              {/* 品牌增长 — 全宽,无 sidebar */}
              <Route path="/brand-growth" element={<BrandGrowth />} />
              <Route path="/brand-growth/sources" element={<BrandGrowthSources />} />
              <Route path="/brand-growth/engines" element={<BrandGrowthEngines />} />
              <Route path="/brand-growth/competitors" element={<BrandGrowthCompetitors />} />
              <Route path="/brand-growth/matrix" element={<BrandGrowthMatrix />} />
              <Route path="/brand-growth/insights" element={<BrandGrowthInsights />} />
              <Route path="/brand-growth/queries" element={<BrandGrowthQueries />} />
              <Route path="/brand-growth/responses" element={<BrandGrowthResponses />} />
              <Route path="/brand-growth/published" element={<BrandGrowthPublished />} />
              <Route path="/dashboard" element={<DashboardLayout />}>
                {/* 首页 → /brand-growth(无 sidebar 全宽页) */}
                <Route index element={<Navigate to="/brand-growth" replace />} />
                {/* 内容入口砍掉:普通用户去 /brand-growth/published(战报),admin 去 /workbench/content-management */}
                <Route path="content" element={<ContentRedirect />} />
                {/* 老路由统一跳新页 */}
                <Route path="compose" element={<Navigate to="/brand-growth/published" replace />} />
                <Route path="posts" element={<Navigate to="/brand-growth/published" replace />} />
                <Route path="ai-telemetry" element={<Navigate to="/brand-growth" replace />} />
                <Route path="insights" element={<Navigate to="/brand-growth/insights" replace />} />
              </Route>
              {/* 工作台 — admin 专属,独立 sidebar 不混 AEO 菜单 */}
              <Route path="/workbench" element={<WorkbenchLayout />}>
                <Route index element={<Navigate to="cockpit" replace />} />
                <Route path="cockpit" element={<AdminCockpit />} />
                <Route path="accounts" element={<AdminAccounts />} />
                <Route path="accounts/:userId/topics" element={<AdminAccountTopics />} />
                {/* 旧审批入口退役 → 客户账号(防旧书签 404)*/}
                <Route path="approvals" element={<Navigate to="/workbench/accounts" replace />} />
                <Route path="review" element={<Navigate to="/workbench/accounts" replace />} />
                <Route path="insights" element={<AdminInsights />} />
                <Route path="crawl" element={<AdminCrawl />} />
                <Route path="workers" element={<AdminWorkers />} />
                <Route path="gateway" element={<Navigate to="/unified-monitor" replace />} />
                <Route path="runs" element={<AdminAllRuns />} />
                <Route path="runs/:runId" element={<AdminRunDetail />} />
                {/* 详情页 / 非 sidebar 直达 */}
                <Route path="content-review" element={<AdminContentReview />} />
                <Route path="platform-rules" element={<AdminPlatformRules />} />
                <Route path="content-management" element={<Content />} />
                <Route path="topics/:topicId/edit" element={<AdminTopicEdit />} />
                {/* 老的单主题详情路由全部并入「画像」主流程,只保留这一个 wizard */}
                <Route path="topics/:topicId/solution" element={<TopicEditRedirect step={4} />} />
                <Route path="topics/:topicId/execution-plan" element={<TopicEditRedirect step={5} />} />
                <Route path="topics/:topicId/docs" element={<TopicEditRedirect step={6} />} />
              </Route>
              {/* 舆情监控独立成顶级路由,不再嵌套在 DashboardLayout 下 */}
              <Route path="/sentiment" element={<Sentiment />} />
              <Route path="/sentiment/settings" element={<SentimentSettings />} />
              <Route path="/about" element={<About />} />
              <Route path="/blog" element={<Blog />} />
              <Route path="/blog/:slug" element={<BlogPost />} />
              <Route path="/process" element={<Landing />} />
              <Route path="/pricing" element={<Navigate to="/unified-monitor" replace />} />
              <Route path="/data" element={<Landing />} />
              <Route path="/result" element={<Result />} />
              <Route path="/unified-monitor" element={<UnifiedMonitor />} />
              <Route path="/advanced/:mode" element={<Advanced />} />
              <Route path="/contact" element={<Contact />} />
              <Route path="/login" element={<Navigate to="/unified-monitor" replace />} />
              <Route path="/register" element={<Navigate to="/unified-monitor" replace />} />
              <Route path="/forgot-password" element={<Navigate to="/unified-monitor" replace />} />
              <Route path="/checkout/*" element={<Navigate to="/unified-monitor" replace />} />
              <Route path="/privacy" element={<PrivacyPolicy />} />
              <Route path="/terms" element={<TermsOfUse />} />
              <Route path="/cookie-policy" element={<CookiePolicy />} />
            </Routes>
          </Suspense>
          <Footer />
        </div>
        <AgentChatWidget />
        </Suspense>
      </TierModalProvider>
      </ContactModalProvider>
      </AuthModalProvider>
      </AuthProvider>
      </Router>
      </HelmetProvider>
    </QueryClientProvider>
  );
}

export default App;



