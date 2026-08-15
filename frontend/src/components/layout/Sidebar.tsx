import React, { useEffect, useState, useRef, useMemo } from 'react';
import { PanelLeftClose, Plus, MessageSquare, Settings, Trash2, MoreHorizontal, Pin, PinOff, Pencil, Moon, Sun, Monitor } from 'lucide-react';
import { clsx } from 'clsx';
import { useChatStore, CHAT_MODES } from '../../store/chatStore';
import { sortSessions, sessionTitle } from '../../lib/sessionUtils';
import { useNavigate } from 'react-router-dom';
import { useTheme } from '../../lib/useTheme';
import type { ChatSession } from '../../types/api';

interface SidebarProps {
  isOpen: boolean;
  toggleSidebar: () => void;
}

const SessionItem: React.FC<{
  session: ChatSession;
  currentConversationId: string;
  isStreaming: boolean;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onPin: (id: string, pinned: boolean) => void;
  onRename: (id: string, title: string) => void;
}> = ({ session, currentConversationId, isStreaming, onSelect, onDelete, onPin, onRename }) => {
  const [isEditing, setIsEditing] = useState(false);
  const [editTitle, setEditTitle] = useState('');
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const title = sessionTitle(session);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    if (menuOpen) document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [menuOpen]);

  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus();
    }
  }, [isEditing]);

  const handleRenameSubmit = () => {
    if (editTitle.trim() && editTitle.trim() !== title) {
      onRename(session.conversationId, editTitle.trim());
    }
    setIsEditing(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleRenameSubmit();
    if (e.key === 'Escape') setIsEditing(false);
  };

  return (
    <div
      className={clsx(
        "group relative w-full flex items-center gap-2 p-2 rounded-lg transition-colors text-sm",
        session.conversationId === currentConversationId
          ? "bg-secondary/80 text-foreground font-medium"
          : "hover:bg-secondary/50 text-muted-foreground"
      )}
    >
      <button
        onClick={() => !isEditing && onSelect(session.conversationId)}
        disabled={isStreaming}
        className="flex items-center gap-2 flex-1 min-w-0 text-left"
      >
        <MessageSquare size={16} className="opacity-50 group-hover:opacity-100 flex-shrink-0" />
        {isEditing ? (
          <input
            ref={inputRef}
            type="text"
            value={editTitle}
            onChange={(e) => setEditTitle(e.target.value)}
            onBlur={handleRenameSubmit}
            onKeyDown={handleKeyDown}
            className="flex-1 min-w-0 bg-background border border-primary text-foreground rounded px-1.5 py-0.5 outline-none -ml-1.5 focus:ring-2 focus:ring-primary/20"
            onClick={(e) => e.stopPropagation()}
          />
        ) : (
          <span className="truncate flex-1">{title}</span>
        )}
        {session.running && <span className="w-2 h-2 rounded-full bg-primary flex-shrink-0"></span>}
      </button>

      {/* Options Menu Toggle */}
      {!isEditing && (
        <div className="relative" ref={menuRef}>
          <button
            onClick={(e) => {
              e.stopPropagation();
              setMenuOpen(!menuOpen);
            }}
            disabled={isStreaming}
            className={clsx(
              "p-1 rounded transition-opacity",
              menuOpen ? "opacity-100 bg-secondary" : "opacity-0 group-hover:opacity-100 hover:text-foreground"
            )}
            title="Options"
          >
            <MoreHorizontal size={14} />
          </button>

          {menuOpen && (
            <div className="absolute right-0 top-full mt-1 w-32 bg-background border border-border/50 rounded-md shadow-lg py-1 z-50 text-xs text-foreground">
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onPin(session.conversationId, !session.isPinned);
                  setMenuOpen(false);
                }}
                className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-secondary transition-colors text-left"
              >
                {session.isPinned ? <PinOff size={12} /> : <Pin size={12} />}
                {session.isPinned ? 'Unpin' : 'Pin'}
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setEditTitle(title);
                  setIsEditing(true);
                  setMenuOpen(false);
                }}
                className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-secondary transition-colors text-left"
              >
                <Pencil size={12} />
                Rename
              </button>
              <div className="h-px bg-border/50 my-1 mx-2" />
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(session.conversationId);
                  setMenuOpen(false);
                }}
                className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-destructive/10 text-destructive transition-colors text-left"
              >
                <Trash2 size={12} />
                Delete
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export const Sidebar: React.FC<SidebarProps> = ({ isOpen, toggleSidebar }) => {
  const {
    sessions,
    loadingSessions,
    currentConversationId,
    deleteConversation,
    renameConversation,
    pinConversation,
    chatMode,
    setChatMode,
    startNewConversation,
    refreshSessions,
    isStreaming
  } = useChatStore();
  
  const navigate = useNavigate();
  const { theme, setTheme } = useTheme();

  useEffect(() => {
    refreshSessions();
  }, [refreshSessions]);

  const { pinnedSessions, historySessions } = useMemo(() => {
    const sorted = sortSessions(sessions);
    return {
      pinnedSessions: sorted.filter(s => s.isPinned),
      historySessions: sorted.filter(s => !s.isPinned)
    };
  }, [sessions]);

  return (
    <div
      className={clsx(
        "flex flex-col h-full bg-secondary/30 border-r border-border/50 transition-all duration-300 flex-shrink-0 z-40",
        isOpen ? "w-[260px] translate-x-0" : "w-0 -translate-x-full xl:translate-x-0 xl:w-0 overflow-hidden border-transparent"
      )}
    >
      <div className="p-3 flex items-center justify-between">
        <button
          onClick={() => { startNewConversation(); navigate('/chat'); }}
          disabled={isStreaming}
          className="flex-1 flex items-center gap-2 hover:bg-secondary/50 p-2 rounded-lg transition-colors text-sm font-medium disabled:opacity-50 text-foreground"
        >
          <div className="w-6 h-6 rounded-full bg-primary/20 flex items-center justify-center text-primary text-xs font-bold">
            C
          </div>
          <span className="truncate">New Chat</span>
          <Plus size={16} className="ml-auto opacity-70" />
        </button>

        <button
          onClick={toggleSidebar}
          className="ml-2 p-2 rounded-lg hover:bg-secondary/50 transition-colors text-muted-foreground"
          title="Close sidebar"
        >
          <PanelLeftClose size={20} />
        </button>
      </div>

      {/* Mode Selection — hidden on desktop (xl+), shown on narrow screens */}
      <div className="xl:hidden px-3 pb-1">
        <div className="flex flex-col gap-1 bg-secondary/40 rounded-lg p-1.5">
          <button
            disabled={isStreaming}
            onClick={() => { setChatMode(CHAT_MODES.DOCUMENT); }}
            className={clsx(
              "px-3 py-1.5 text-xs font-medium rounded-md transition-colors text-left",
              chatMode === CHAT_MODES.DOCUMENT
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:bg-secondary/80"
            )}
          >
            Document
          </button>
          <button
            disabled={isStreaming}
            onClick={() => { setChatMode(CHAT_MODES.AUTO_DOCUMENT); }}
            className={clsx(
              "px-3 py-1.5 text-xs font-medium rounded-md transition-colors text-left",
              chatMode === CHAT_MODES.AUTO_DOCUMENT
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:bg-secondary/80"
            )}
          >
            Auto Knowledge
          </button>
          <button
            disabled={isStreaming}
            onClick={() => { setChatMode(CHAT_MODES.OPEN_CHAT); }}
            className={clsx(
              "px-3 py-1.5 text-xs font-medium rounded-md transition-colors text-left",
              chatMode === CHAT_MODES.OPEN_CHAT
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:bg-secondary/80"
            )}
          >
            Open Chat
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto overflow-x-hidden p-3 space-y-4">
        {loadingSessions ? (
          <div className="text-sm text-muted-foreground opacity-80 px-2 mt-2">Loading...</div>
        ) : sessions.length === 0 ? (
          <div className="text-sm text-muted-foreground opacity-80 px-2 mt-2">No history.</div>
        ) : (
          <>
            {pinnedSessions.length > 0 && (
              <div className="space-y-1">
                <div className="text-xs font-semibold text-muted-foreground px-2 py-1 flex items-center gap-2">
                  <Pin size={12} />
                  Pinned
                </div>
                {pinnedSessions.map((session) => (
                  <SessionItem
                    key={session.conversationId}
                    session={session}
                    currentConversationId={currentConversationId}
                    isStreaming={isStreaming}
                    onSelect={(id) => navigate('/chat/' + id)}
                    onDelete={deleteConversation}
                    onPin={pinConversation}
                    onRename={renameConversation}
                  />
                ))}
              </div>
            )}

            {historySessions.length > 0 && (
              <div className="space-y-1">
                <div className="text-xs font-semibold text-muted-foreground px-2 py-1">
                  History
                </div>
                {historySessions.map((session) => (
                  <SessionItem
                    key={session.conversationId}
                    session={session}
                    currentConversationId={currentConversationId}
                    isStreaming={isStreaming}
                    onSelect={(id) => navigate('/chat/' + id)}
                    onDelete={deleteConversation}
                    onPin={pinConversation}
                    onRename={renameConversation}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </div>

      <div className="p-3 border-t border-border/50 flex flex-col gap-2">
        <div className="flex items-center p-1 bg-secondary/50 rounded-lg">
          <button
            onClick={() => setTheme('light')}
            className={clsx("flex-1 flex justify-center py-1.5 rounded-md transition-colors", theme === 'light' ? 'bg-background shadow-sm text-foreground' : 'text-muted-foreground hover:text-foreground')}
            title="Light Mode"
          >
            <Sun size={14} />
          </button>
          <button
            onClick={() => setTheme('system')}
            className={clsx("flex-1 flex justify-center py-1.5 rounded-md transition-colors", theme === 'system' ? 'bg-background shadow-sm text-foreground' : 'text-muted-foreground hover:text-foreground')}
            title="System Theme"
          >
            <Monitor size={14} />
          </button>
          <button
            onClick={() => setTheme('dark')}
            className={clsx("flex-1 flex justify-center py-1.5 rounded-md transition-colors", theme === 'dark' ? 'bg-background shadow-sm text-foreground' : 'text-muted-foreground hover:text-foreground')}
            title="Dark Mode"
          >
            <Moon size={14} />
          </button>
        </div>
        <a href="/admin" target="_blank" className="w-full flex items-center gap-2 p-2 rounded-lg hover:bg-secondary/50 transition-colors text-sm text-muted-foreground hover:text-foreground">
          <div className="w-6 h-6 rounded-full bg-secondary flex items-center justify-center overflow-hidden shrink-0">
            <Settings size={14} />
          </div>
          <span className="truncate">Admin Console</span>
        </a>
      </div>
    </div>
  );
};
