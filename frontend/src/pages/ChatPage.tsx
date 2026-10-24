import React, { useState, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { AppLayout } from '../components/layout/AppLayout';
import { ChatContainer } from '../components/chat/ChatContainer';
import { useChatStore } from '../store/chatStore';

/** Sidebar 在 xl 及以上是常驻的，桌面端默认展开，移动端默认收起 */
const DESKTOP_QUERY = '(min-width: 1280px)';

export const ChatPage: React.FC = () => {
  const [sidebarOpen, setSidebarOpen] = useState<boolean>(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return true;
    return window.matchMedia(DESKTOP_QUERY).matches;
  });
  const { conversationId } = useParams();
  const navigate = useNavigate();
  const loadConversation = useChatStore((state) => state.loadConversation);
  const startNewConversation = useChatStore((state) => state.startNewConversation);
  const currentConversationId = useChatStore((state) => state.currentConversationId);

  useEffect(() => {
    if (conversationId) {
      // 撞见的不是当前会话才去拉，避免重复请求
      if (conversationId !== useChatStore.getState().currentConversationId) {
        void loadConversation(conversationId);
      }
      return;
    }

    // URL 是 /chat（没有会话 id）：清掉状态里残留的会话。
    // 否则地址栏是空的、界面却显示上一轮对话，一刷新就"丢失"了。
    // 只在 conversationId 变化时判断，避免用户在本页发消息后被误清空。
    if (useChatStore.getState().messages.length > 0) {
      startNewConversation();
    }
  }, [conversationId, loadConversation, startNewConversation]);

  useEffect(() => {
    // 会话 id 只有在第一条消息发出后才会生成（新对话不在 URL 里占位），
    // 此时把地址栏补成 /chat/<id>，刷新或分享才回得到这段对话。
    // 用 replace 而不是 push：这只是同一段对话的地址纠正，不该多一条历史记录。
    // 反方向不管：/chat/<id> 加载失败时不能被"跳回旧会话"盖掉错误提示。
    if (conversationId || !currentConversationId) return;
    navigate(`/chat/${currentConversationId}`, { replace: true });
  }, [conversationId, currentConversationId, navigate]);

  const toggleSidebar = () => setSidebarOpen((open) => !open);

  return (
    <AppLayout sidebarOpen={sidebarOpen} toggleSidebar={toggleSidebar}>
      <ChatContainer sidebarOpen={sidebarOpen} toggleSidebar={toggleSidebar} />
    </AppLayout>
  );
};
