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

export const AdminLayout: React.FC = () => {
  const navigate = useNavigate();

  const handleLogout = async () => {
    try {
      await adminAuthApi.logout();
    } catch (e) {
      // ignore
    } finally {
      clearAdminAuth();
      navigate('/admin/login', { replace: true });
    }
  };

  const navItems = [
    { to: '/admin/dashboard', icon: <LayoutDashboard size={20} />, label: '流水线总览' },
    { to: '/admin/documents', icon: <FileText size={20} />, label: '接入文档' },
    { to: '/admin/knowledge-route', icon: <Network size={20} />, label: '路由配置' },
    { to: '/admin/observability', icon: <ActivitySquare size={20} />, label: '对话观测' },
    { to: '/admin/metrics', icon: <BarChart3 size={20} />, label: '观测指标' },
    { to: '/admin/evaluation', icon: <FileText size={20} />, label: '评估看板' },
  ];

  return (
    <div className="min-h-screen bg-secondary/30 flex flex-col md:flex-row">
      {/* Sidebar */}
      <aside className="w-full md:w-[260px] bg-background border-b md:border-b-0 md:border-r border-border flex-shrink-0 flex flex-col">
        <div className="h-16 flex items-center px-6 border-b border-border">
          <h1 className="font-bold text-lg tracking-tight text-foreground">
            文档流水线
          </h1>
        </div>
        
        <nav className="flex-1 px-4 py-6 space-y-1 overflow-y-auto">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => 
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                  isActive 
                    ? 'bg-primary/10 text-primary' 
                    : 'text-muted-foreground hover:bg-secondary/80 hover:text-foreground'
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
            <MessageSquare size={20} className="text-primary" />
            返回聊天
          </Button>
          <Button 
            variant="ghost"
            onClick={handleLogout}
            className="w-full flex items-center justify-start gap-3 text-muted-foreground hover:text-destructive"
          >
            <LogOut size={20} />
            退出登录
          </Button>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 min-w-0 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
};
