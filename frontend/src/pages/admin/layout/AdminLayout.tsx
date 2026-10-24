import React from 'react';
import { Outlet, NavLink, useNavigate } from 'react-router-dom';
import { 
  LayoutDashboard, 
  FileText, 
  Network, 
  ActivitySquare, 
  LogOut,
  MessageSquare,
  BarChart3
} from 'lucide-react';
import { adminAuthApi } from '../../../lib/api';
import { clearAdminAuth } from '../../../lib/adminAuth';
import { Button } from '../../../components/ui/Button';
import { ErrorBoundary } from '../../../components/common/ErrorBoundary';

export const AdminLayout: React.FC = () => {
  const navigate = useNavigate();

  const handleLogout = async () => {
    try {
      await adminAuthApi.logout();
    } catch {
      // ignore
    } finally {
      clearAdminAuth();
      navigate('/admin/login', { replace: true });
    }
  };

  // 图标只做视觉锚点，无障碍名称交给文字，避免读屏重复朗读
  const navItems = [
    { to: '/admin/dashboard', icon: <LayoutDashboard size={18} aria-hidden="true" />, label: '流水线总览' },
    { to: '/admin/documents', icon: <FileText size={18} aria-hidden="true" />, label: '接入文档' },
    { to: '/admin/knowledge-route', icon: <Network size={18} aria-hidden="true" />, label: '路由配置' },
    { to: '/admin/observability', icon: <ActivitySquare size={18} aria-hidden="true" />, label: '对话观测' },
    { to: '/admin/metrics', icon: <BarChart3 size={18} aria-hidden="true" />, label: '观测指标' },
    { to: '/admin/evaluation', icon: <FileText size={18} aria-hidden="true" />, label: '评估看板' },
    { to: '/admin/traces', icon: <ActivitySquare size={18} aria-hidden="true" />, label: 'Trace 链路' },
  ];

  return (
    <div className="min-h-dvh bg-secondary/30 flex flex-col md:flex-row">
      {/* Sidebar */}
      <aside className="w-full md:w-[260px] bg-background border-b md:border-b-0 md:border-r border-border flex-shrink-0 flex flex-col">
        <div className="h-16 flex items-center px-6 border-b border-border">
          <h1 className="font-bold text-lg tracking-tight text-foreground">
            文档流水线
          </h1>
        </div>
        
        <nav aria-label="管理后台导航" className="flex-1 px-4 py-6 space-y-1 overflow-y-auto">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => 
                `flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                  isActive
                    ? 'bg-primary/10 text-primary'
                    : 'text-muted-foreground hover:bg-secondary hover:text-foreground'
                }`
              }
            >
              {item.icon}
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="p-4 border-t border-border flex flex-col gap-2">
          <Button 
            variant="outline"
            className="w-full flex items-center justify-start gap-3"
            onClick={() => navigate('/chat')}
          >
            <MessageSquare size={16} className="text-primary" aria-hidden="true" />
            返回聊天
          </Button>
          <Button 
            variant="ghost"
            onClick={handleLogout}
            className="w-full flex items-center justify-start gap-3 text-muted-foreground hover:text-destructive"
          >
            <LogOut size={16} aria-hidden="true" />
            退出登录
          </Button>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 min-w-0 overflow-y-auto">
        {/* 单个后台页面崩了不该把整个后台导航一起带走 */}
        <ErrorBoundary>
          <Outlet />
        </ErrorBoundary>
      </main>
    </div>
  );
};
