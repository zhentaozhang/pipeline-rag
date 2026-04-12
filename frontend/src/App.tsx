import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ChatPage } from './pages/ChatPage';
import { AdminLoginPage } from './pages/admin/AdminLoginPage';
import { AdminLayout } from './pages/admin/layout/AdminLayout';
import { AdminDashboardView } from './pages/admin/AdminDashboardView';
import { AdminDocumentListView } from './pages/admin/AdminDocumentListView';
import { AdminDocumentDetailView } from './pages/admin/AdminDocumentDetailView';
import { AdminDocumentCenterView } from './pages/admin/AdminDocumentCenterView';
import { AdminKnowledgeRouteView } from './pages/admin/AdminKnowledgeRouteView';
import { AdminKnowledgeRouteTraceView } from './pages/admin/AdminKnowledgeRouteTraceView';
import { AdminObservabilityListView } from './pages/admin/AdminObservabilityListView';
import { AdminObservabilitySessionView } from './pages/admin/AdminObservabilitySessionView';
import { AdminObservabilityDetailView } from './pages/admin/AdminObservabilityDetailView';
import { AdminEvaluationDatasetView } from './pages/admin/AdminEvaluationDatasetView';
import { AdminMetricsView } from './pages/admin/AdminMetricsView';
import { isAdminAuthenticated } from './lib/adminAuth';
import { useTheme } from './lib/useTheme';

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
        <Route path="/chat/:conversationId?" element={<ChatPage />} />
        
        {/* Admin Routes */}
        <Route path="/admin/login" element={<AdminLoginPage />} />
        <Route path="/admin" element={<AdminRoute><AdminLayout /></AdminRoute>}>
          <Route index element={<Navigate to="/admin/dashboard" replace />} />
          <Route path="dashboard" element={<AdminDashboardView />} />
          <Route path="documents" element={<AdminDocumentListView />} />
          <Route path="documents/center" element={<AdminDocumentCenterView />} />
          <Route path="documents/:documentId" element={<AdminDocumentDetailView />} />
          <Route path="knowledge-route" element={<AdminKnowledgeRouteView />} />
          <Route path="knowledge-route/trace" element={<AdminKnowledgeRouteTraceView />} />
          <Route path="observability" element={<AdminObservabilityListView />} />
          <Route path="observability/:conversationId" element={<AdminObservabilitySessionView />} />
          <Route path="observability/:conversationId/exchange/:exchangeId" element={<AdminObservabilityDetailView />} />
          <Route path="evaluation" element={<AdminEvaluationDatasetView />} />
          <Route path="metrics" element={<AdminMetricsView />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
