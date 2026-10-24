import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { Menu } from 'lucide-react';
import { clsx } from 'clsx';
import { IconButton } from '../ui/IconButton';
import { ErrorBoundary } from '../common/ErrorBoundary';
import { Sidebar } from './Sidebar';

interface AppLayoutProps {
  children: ReactNode;
  sidebarOpen: boolean;
  toggleSidebar: () => void;
}

/** 与 Tailwind 的 xl 断点对齐：低于它，侧栏是覆盖层抽屉而不是并排的一列 */
const DRAWER_QUERY = '(max-width: 1279px)';

function isDrawerViewport(): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia(DRAWER_QUERY).matches;
}

export function AppLayout({ children, sidebarOpen, toggleSidebar }: AppLayoutProps) {
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const wasOpenRef = useRef(sidebarOpen);
  const [drawerMode, setDrawerMode] = useState(isDrawerViewport);

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;
    const query = window.matchMedia(DRAWER_QUERY);
    const update = () => setDrawerMode(query.matches);
    update();
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);

  // 抽屉关闭后把焦点还给汉堡按钮：否则焦点掉回 body，键盘用户要重头 Tab 一整轮
  useEffect(() => {
    if (wasOpenRef.current && !sidebarOpen) {
      const trigger = menuButtonRef.current;
      // 宽屏下汉堡是 display:none，focus() 不生效，还会把正文里的焦点抢走
      if (trigger && trigger.offsetParent !== null) trigger.focus();
    }
    wasOpenRef.current = sidebarOpen;
  }, [sidebarOpen]);

  useEffect(() => {
    // 只有抽屉形态需要锁滚动；宽屏侧栏和正文各自滚动，锁 body 没有意义
    if (!sidebarOpen || !drawerMode) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [sidebarOpen, drawerMode]);

  useEffect(() => {
    if (!sidebarOpen) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      // Esc 只负责关抽屉；宽屏下这个手势没有预期，容易和其它浮层抢事件
      if (event.key === 'Escape' && isDrawerViewport()) toggleSidebar();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [sidebarOpen, toggleSidebar]);

  const closeDrawer = useCallback(() => {
    if (sidebarOpen) toggleSidebar();
  }, [sidebarOpen, toggleSidebar]);

  return (
    // h-dvh 而不是 h-screen：移动端浏览器地址栏收起/展开时 100vh 会溢出，
    // 底部的输入框会被顶出屏幕。
    <div className="relative flex h-dvh w-full overflow-hidden bg-background font-sans text-foreground transition-colors duration-200">
      {/* 抽屉遮罩：点空白处收起，同时让「背后暂时不可交互」看得见 */}
      <div
        aria-hidden="true"
        onClick={closeDrawer}
        className={clsx(
          'absolute inset-0 z-30 bg-foreground/20 transition-opacity xl:hidden',
          sidebarOpen ? 'opacity-100' : 'pointer-events-none opacity-0'
        )}
      />

      {/* 抽屉打开时它自带关闭按钮，汉堡再浮在上面只会挡住「新对话」 */}
      <div className={clsx('absolute left-3 top-3 z-50 xl:hidden', sidebarOpen && 'hidden')}>
        <IconButton
          ref={menuButtonRef}
          label={sidebarOpen ? '收起侧边栏' : '展开侧边栏'}
          aria-expanded={sidebarOpen}
          aria-controls="app-sidebar"
          icon={<Menu size={20} aria-hidden="true" />}
          onClick={toggleSidebar}
        />
      </div>

      <Sidebar isOpen={sidebarOpen} toggleSidebar={toggleSidebar} drawerMode={drawerMode} />

      <main className="relative flex h-full flex-1 flex-col overflow-hidden transition-all duration-300">
        <ErrorBoundary>{children}</ErrorBoundary>
      </main>
    </div>
  );
}
