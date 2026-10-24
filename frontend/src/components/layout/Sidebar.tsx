import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useShallow } from 'zustand/react/shallow';
import { Monitor, Moon, PanelLeftClose, Plus, Settings, Sun } from 'lucide-react';
import { clsx } from 'clsx';
import { useChatStore, CHAT_MODES, type ChatMode } from '../../store/chatStore';
import { groupSessions } from '../../lib/sessionGrouping';
import { toast } from '../../lib/toast';
import { useTheme, type Theme } from '../../lib/useTheme';
import { Button } from '../ui/Button';
import { IconButton } from '../ui/IconButton';
import { SessionList } from './SessionList';
import { SidebarSearch } from './SidebarSearch';

interface SidebarProps {
  isOpen: boolean;
  toggleSidebar: () => void;
  /** 窄屏下侧栏是覆盖层抽屉：打开时抢焦点到搜索框，选中会话后自动收起 */
  drawerMode?: boolean;
}

const MODE_OPTIONS: { value: ChatMode; label: string }[] = [
  { value: CHAT_MODES.DOCUMENT, label: '文档问答' },
  { value: CHAT_MODES.AUTO_DOCUMENT, label: '自动知识库' },
  { value: CHAT_MODES.OPEN_CHAT, label: '自由对话' },
];

const THEME_OPTIONS: { value: Theme; label: string; icon: typeof Sun }[] = [
  { value: 'light', label: '浅色', icon: Sun },
  { value: 'system', label: '跟随系统', icon: Monitor },
  { value: 'dark', label: '深色', icon: Moon },
];

export function Sidebar({ isOpen, toggleSidebar, drawerMode = false }: SidebarProps) {
  const {
    sessions,
    loadingSessions,
    currentConversationId,
    isStreaming,
    chatMode,
    setChatMode,
    startNewConversation,
    refreshSessions,
    renameSession,
    pinSession,
    deleteSession,
  } = useChatStore(
    useShallow((state) => ({
      sessions: state.sessions,
      loadingSessions: state.loadingSessions,
      currentConversationId: state.currentConversationId,
      isStreaming: state.isStreaming,
      chatMode: state.chatMode,
      setChatMode: state.setChatMode,
      startNewConversation: state.startNewConversation,
      refreshSessions: state.refreshSessions,
      renameSession: state.renameSession,
      pinSession: state.pinSession,
      deleteSession: state.deleteSession,
    }))
  );

  const navigate = useNavigate();
  const { theme, setTheme } = useTheme();
  const searchInputRef = useRef<HTMLInputElement>(null);

  const [query, setQuery] = useState('');
  // 「N 分钟前」「昨天」这类文案不会自己变，每分钟重算一次比让用户看到过期时间好
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    refreshSessions();
  }, [refreshSessions]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    // 抽屉是覆盖层：打开就把焦点放到搜索框，键盘用户不用先 Tab 过整列表
    if (drawerMode && isOpen) searchInputRef.current?.focus();
  }, [drawerMode, isOpen]);

  const groups = useMemo(() => groupSessions(sessions, query, now), [sessions, query, now]);

  const handleClearSearch = useCallback(() => {
    setQuery('');
    searchInputRef.current?.focus();
  }, []);

  const handleSelect = useCallback(
    (conversationId: string) => {
      navigate(`/chat/${conversationId}`);
      // 抽屉会挡住正文，选中就收起，否则用户还得再点一次遮罩
      if (drawerMode && isOpen) toggleSidebar();
    },
    [navigate, drawerMode, isOpen, toggleSidebar]
  );

  const handleNewChat = useCallback(() => {
    startNewConversation();
    navigate('/chat');
    if (drawerMode && isOpen) toggleSidebar();
  }, [startNewConversation, navigate, drawerMode, isOpen, toggleSidebar]);

  /**
   * store 的这三个 action 失败时会自己回滚并弹错误 toast（chatStore.ts:400、:422、:443），
   * 所以这里不再补错误 toast，只补 store 没覆盖的成功反馈；是否成功以列表状态为准 ——
   * action 用乐观更新 + 回滚，await 之后读到的就是用户真正看到的结果。
   */
  const handleRename = useCallback(
    async (conversationId: string, title: string) => {
      await renameSession(conversationId, title);
      const renamed = useChatStore
        .getState()
        .sessions.some((item) => item.conversationId === conversationId && item.title === title);
      if (renamed) toast({ title: '已重命名会话', variant: 'success' });
    },
    [renameSession]
  );

  const handleTogglePin = useCallback(
    async (conversationId: string, pinned: boolean) => {
      await pinSession(conversationId, pinned);
      const current = useChatStore
        .getState()
        .sessions.find((item) => item.conversationId === conversationId);
      if (Boolean(current?.isPinned) === pinned) {
        toast({ title: pinned ? '已置顶会话' : '已取消置顶', variant: 'success' });
      }
    },
    [pinSession]
  );

  return (
    <aside
      id="app-sidebar"
      // 收起时不占位也不能被 Tab 到：inert 才能真正把它移出焦点顺序和读屏范围
      inert={!isOpen}
      aria-label="会话侧边栏"
      className={clsx(
        'absolute inset-y-0 left-0 z-40 flex w-[280px] flex-col border-r border-border bg-card transition-[transform,width] duration-200',
        // 桌面端回到文档流里：宽度收放比位移正确，位移会把内容压在正文上面
        'xl:static xl:z-auto xl:w-[264px] xl:translate-x-0 xl:shadow-none',
        isOpen
          ? 'translate-x-0 shadow-xl'
          : '-translate-x-full shadow-none xl:w-0 xl:overflow-hidden xl:border-transparent'
      )}
    >
      <div className="flex items-center gap-1 border-b border-border px-2 py-2">
        <Button
          variant="ghost"
          size="sm"
          className="h-8 flex-1 justify-start gap-2 px-2 text-sm font-medium"
          disabled={isStreaming}
          onClick={handleNewChat}
        >
          <span
            aria-hidden="true"
            className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-primary/15 text-2xs font-bold text-primary"
          >
            C
          </span>
          新对话
          <Plus size={14} aria-hidden="true" className="ml-auto opacity-70" />
        </Button>
        <IconButton
          label="收起侧边栏"
          icon={<PanelLeftClose size={18} aria-hidden="true" />}
          onClick={toggleSidebar}
        />
      </div>

      <SidebarSearch inputRef={searchInputRef} value={query} onChange={setQuery} />

      {/* 模式切换只在窄屏出现：宽屏由正文顶部的模式条负责 */}
      <div className="xl:hidden px-2 pb-1">
        <div role="group" aria-label="对话模式" className="flex flex-col gap-0.5 rounded-lg bg-secondary/60 p-1">
          {MODE_OPTIONS.map((option) => {
            const active = chatMode === option.value;
            return (
              <Button
                key={option.value}
                variant="ghost"
                size="sm"
                aria-pressed={active}
                disabled={isStreaming}
                className={clsx(
                  'w-full justify-start text-xs',
                  // 选中态靠底色 + 阴影，不只靠文字颜色深浅
                  active ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground'
                )}
                onClick={() => setChatMode(option.value)}
              >
                {option.label}
              </Button>
            );
          })}
        </div>
      </div>

      <SessionList
        groups={groups}
        loading={loadingSessions}
        hasSessions={sessions.length > 0}
        query={query}
        now={now}
        currentConversationId={currentConversationId}
        streaming={isStreaming}
        onSelect={handleSelect}
        onRename={handleRename}
        onTogglePin={handleTogglePin}
        onDelete={deleteSession}
        onClearSearch={handleClearSearch}
        onStartNew={handleNewChat}
      />

      <div className="flex flex-col gap-2 border-t border-border p-2">
        <div role="group" aria-label="外观主题" className="flex items-center gap-0.5 rounded-lg bg-secondary/60 p-1">
          {THEME_OPTIONS.map((option) => {
            const Icon = option.icon;
            const active = theme === option.value;
            return (
              <IconButton
                key={option.value}
                label={option.label}
                aria-pressed={active}
                size="sm"
                icon={<Icon size={14} aria-hidden="true" />}
                className={clsx('flex-1', active && 'bg-background text-foreground shadow-sm')}
                onClick={() => setTheme(option.value)}
              />
            );
          })}
        </div>
        <a
          href="/admin"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2 rounded-lg p-2 text-sm text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
        >
          <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-secondary">
            <Settings size={14} aria-hidden="true" />
          </span>
          <span className="truncate">管理后台</span>
        </a>
      </div>
    </aside>
  );
}
