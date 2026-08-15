import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { AppLayout } from '../components/layout/AppLayout';
import { ChatContainer } from '../components/chat/ChatContainer';
import { useChatStore } from '../store/chatStore';

export const ChatPage: React.FC = () => {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const { conversationId } = useParams();
  const loadConversation = useChatStore((state) => state.loadConversation);
  const storeConversationId = useChatStore((state) => state.currentConversationId);

  useEffect(() => {
    if (conversationId && conversationId !== storeConversationId) {
      void (async () => {
        await loadConversation(conversationId);
      })();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId]);

  const toggleSidebar = () => setSidebarOpen(!sidebarOpen);

  return (
    <AppLayout sidebarOpen={sidebarOpen} toggleSidebar={toggleSidebar}>
      <ChatContainer sidebarOpen={sidebarOpen} toggleSidebar={toggleSidebar} />
    </AppLayout>
  );
};
