import React, { useState, useEffect } from 'react';
import { PanelLeft } from 'lucide-react';
import { ChatInput } from './ChatInput';
import { MessageList } from './MessageList';

import { useChatStore } from '../../store/chatStore';
import { chatApi } from '../../lib/api';

interface ChatContainerProps {
  sidebarOpen: boolean;
  toggleSidebar: () => void;
}

export const ChatContainer: React.FC<ChatContainerProps> = ({ sidebarOpen, toggleSidebar }) => {
  const { messages, pageError, loadingConversation, isStreaming, sendMessage } = useChatStore();
  const messagesEndRef = React.useRef<HTMLDivElement>(null);
  const [connectionStatus, setConnectionStatus] = useState<'checking' | 'connected' | 'disconnected'>('checking');

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isStreaming]);

  useEffect(() => {
    const checkConn = async () => {
      setConnectionStatus('checking');
      try {
        const res = await chatApi.checkConnection();
        // /api/health might return something, or just throw if it's 404/500
        // wait, requestJson returns null on 204 or json. If it doesn't throw, we assume connected.
        setConnectionStatus(res !== undefined ? 'connected' : 'disconnected');
      } catch {
        setConnectionStatus('disconnected');
      }
    };
    checkConn();
    const interval = setInterval(checkConn, 30000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="flex flex-col h-full w-full relative bg-background">
      {/* Header */}
      <header className="absolute top-0 left-0 right-0 h-14 flex items-center justify-between px-4 z-10 bg-gradient-to-b from-background to-transparent pointer-events-none">
        <div className="flex items-center gap-2 pointer-events-auto">
          {!sidebarOpen && (
            <button 
              onClick={toggleSidebar}
                className="p-2 rounded-lg hover:bg-secondary transition-colors text-muted-foreground hidden xl:block"
              title="Open sidebar"
            >
              <PanelLeft size={20} />
            </button>
          )}
          <span className="font-medium text-foreground ml-12 xl:ml-0">
            Pipeline RAG
          </span>
        </div>

        {/* Connection Status Indicator */}
        <div className="pointer-events-auto flex items-center gap-2 px-2">
          {connectionStatus === 'checking' && (
            <span className="relative flex h-2.5 w-2.5" title="Checking connection...">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-yellow-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-yellow-500"></span>
            </span>
          )}
          {connectionStatus === 'connected' && (
            <span className="flex h-2.5 w-2.5 rounded-full bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.5)]" title="Connected"></span>
          )}
          {connectionStatus === 'disconnected' && (
            <span className="flex h-2.5 w-2.5 rounded-full bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.5)]" title="Disconnected"></span>
          )}
        </div>
      </header>

      {/* Messages Area */}
      <div className="flex-1 overflow-y-auto scroll-smooth">
        <div className="max-w-3xl mx-auto px-4 py-20 pb-40 flex flex-col gap-6">
          
          {pageError && (
            <div className="p-4 bg-destructive/10 text-destructive rounded-xl text-sm border border-destructive/20">
              {pageError}
            </div>
          )}

          {loadingConversation && (
            <div className="text-sm text-muted-foreground py-4 text-center">
              正在加载会话内容...
            </div>
          )}

          {!loadingConversation && messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center min-h-[50vh] text-center space-y-8 mt-10">
              <div>
                <h1 className="text-3xl font-bold tracking-tight text-foreground mb-3">
                  Pipeline RAG
                </h1>
                <p className="text-muted-foreground max-w-md mx-auto text-base">
                  Ask questions, analyze documents, and execute tasks across your knowledge base.
                </p>
              </div>
              <div className="flex flex-wrap justify-center gap-3 max-w-lg mt-8">
                <button 
                  onClick={() => sendMessage('请先介绍一下你能帮我做哪些事情，并给出几个典型使用场景')}
                  disabled={isStreaming}
                  className="px-5 py-2.5 bg-secondary/30 hover:bg-secondary border border-border/50 rounded-full text-sm text-muted-foreground hover:text-foreground transition-colors shadow-sm"
                >
                  助手能做什么
                </button>
                <button 
                  onClick={() => sendMessage('请帮我把一个复杂问题拆成清晰的分析步骤，并给出执行建议')}
                  disabled={isStreaming}
                  className="px-5 py-2.5 bg-secondary/30 hover:bg-secondary border border-border/50 rounded-full text-sm text-muted-foreground hover:text-foreground transition-colors shadow-sm"
                >
                  拆解复杂问题
                </button>
                <button 
                  onClick={() => sendMessage('结合当前项目，帮我梳理对话能力、知识库能力和后台能力之间的关系')}
                  disabled={isStreaming}
                  className="px-5 py-2.5 bg-secondary/30 hover:bg-secondary border border-border/50 rounded-full text-sm text-muted-foreground hover:text-foreground transition-colors shadow-sm"
                >
                  梳理项目能力
                </button>
              </div>
            </div>
          ) : (
            <>
              <MessageList messages={messages} />
              <div ref={messagesEndRef} className="h-4" />
            </>
          )}
        </div>
      </div>

      {/* Input Area */}
      <div className="absolute bottom-0 left-0 right-0 p-4 bg-gradient-to-t from-background via-background/90 to-transparent">
        <div className="max-w-3xl mx-auto">
          <ChatInput />
        </div>
        <div className="text-center text-[10px] text-muted-foreground/50 mt-4 hidden md:block uppercase tracking-wider font-medium">
          Pipeline RAG can make mistakes. Consider verifying important information.
        </div>
      </div>
    </div>
  );
};
