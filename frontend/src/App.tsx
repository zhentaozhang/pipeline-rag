import React, { Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { isAdminAuthenticated } from './lib/adminAuth';
import { useTheme } from './lib/useTheme';

// P3-1 路由级代码分割：页面按需加载，减小首屏 chunk
const ChatPage = lazy(() => import('./pages/ChatPage').then((mod) => ({ default: mod.ChatPage })));
const AdminLoginPage = lazy(() => import('./pages/admin/AdminLoginPage').then((mod) => ({ default: mod.AdminLoginPage })));
const AdminLayout = lazy(() => import('./pages/admin/layout/AdminLayout').then((mod) => ({ default: mod.AdminLayout })));
const AdminDashboardView = lazy(() => import('./pages/admin/AdminDashboardView').then((mod) => ({ default: mod.AdminDashboardView })));
const AdminDocumentListView = lazy(() => import('./pages/admin/AdminDocumentListView').then((mod) => ({ default: mod.AdminDocumentListView })));
const AdminDocumentDetailView = lazy(() => import('./pages/admin/AdminDocumentDetailView').then((mod) => ({ default: mod.AdminDocumentDetailView })));
const AdminDocumentCenterView = lazy(() => import('./pages/admin/AdminDocumentCenterView').then((mod) => ({ default: mod.AdminDocumentCenterView })));
const AdminKnowledgeRouteView = lazy(() => import('./pages/admin/AdminKnowledgeRouteView').then((mod) => ({ default: mod.AdminKnowledgeRouteView })));
const AdminKnowledgeRouteTraceView = lazy(() => import('./pages/admin/AdminKnowledgeRouteTraceView').then((mod) => ({ default: mod.AdminKnowledgeRouteTraceView })));
const AdminObservabilityListView = lazy(() => import('./pages/admin/AdminObservabilityListView').then((mod) => ({ default: mod.AdminObservabilityListView })));
const AdminObservabilitySessionView = lazy(() => import('./pages/admin/AdminObservabilitySessionView').then((mod) => ({ default: mod.AdminObservabilitySessionView })));
const AdminObservabilityDetailView = lazy(() => import('./pages/admin/AdminObservabilityDetailView').then((mod) => ({ default: mod.AdminObservabilityDetailView })));
const AdminEvaluationDatasetView = lazy(() => import('./pages/admin/AdminEvaluationDatasetView').then((mod) => ({ default: mod.AdminEvaluationDatasetView })));
const AdminMetricsView = lazy(() => import('./pages/admin/AdminMetricsView').then((mod) => ({ default: mod.AdminMetricsView })));
const AdminTraceListView = lazy(() => import('./pages/admin/AdminTraceListView').then((mod) => ({ default: mod.AdminTraceListView })));
const AdminTraceDetailView = lazy(() => import('./pages/admin/AdminTraceDetailView').then((mod) => ({ default: mod.AdminTraceDetailView })));

function PageLoader({ children }: { children: React.ReactNode }) {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center min-h-[40vh] text-muted-foreground text-sm">
          加载中…
        </div>
      }
    >
      {children}
    </Suspense>
  );
}

const AdminRoute = ({ children }: { children: React.ReactNode }) => {
  if (!isAdminAuthenticated()) {
    return <Navigate to="/admin/login" replace />;
  }
  return <>{children}</>;
};

function App() {
  useTheme(); // Initialize theme on boot

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/chat" replace />} />
        <Route path="/chat/:conversationId?" element={<PageLoader><ChatPage /></PageLoader>} />
        
        {/* Admin Routes */}
        <Route path="/admin/login" element={<PageLoader><AdminLoginPage /></PageLoader>} />
        <Route path="/admin" element={<AdminRoute><PageLoader><AdminLayout /></PageLoader></AdminRoute>}>
          <Route index element={<Navigate to="/admin/dashboard" replace />} />
          <Route path="dashboard" element={<PageLoader><AdminDashboardView /></PageLoader>} />
          <Route path="documents" element={<PageLoader><AdminDocumentListView /></PageLoader>} />
          <Route path="documents/center" element={<PageLoader><AdminDocumentCenterView /></PageLoader>} />
          <Route path="documents/:documentId" element={<PageLoader><AdminDocumentDetailView /></PageLoader>} />
          <Route path="knowledge-route" element={<PageLoader><AdminKnowledgeRouteView /></PageLoader>} />
          <Route path="knowledge-route/trace" element={<PageLoader><AdminKnowledgeRouteTraceView /></PageLoader>} />
          <Route path="observability" element={<PageLoader><AdminObservabilityListView /></PageLoader>} />
          <Route path="observability/:conversationId" element={<PageLoader><AdminObservabilitySessionView /></PageLoader>} />
          <Route path="observability/:conversationId/exchange/:exchangeId" element={<PageLoader><AdminObservabilityDetailView /></PageLoader>} />
          <Route path="evaluation" element={<PageLoader><AdminEvaluationDatasetView /></PageLoader>} />
          <Route path="metrics" element={<PageLoader><AdminMetricsView /></PageLoader>} />
          <Route path="traces" element={<PageLoader><AdminTraceListView /></PageLoader>} />
          <Route path="traces/:traceId" element={<PageLoader><AdminTraceDetailView /></PageLoader>} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
