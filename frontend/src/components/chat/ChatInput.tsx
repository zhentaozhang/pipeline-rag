import React, { useState } from 'react';
import { ArrowUp, StopCircle } from 'lucide-react';
import TextareaAutosize from 'react-textarea-autosize';

import { useChatStore, CHAT_MODES } from '../../store/chatStore';

export const ChatInput: React.FC = () => {
  const [input, setInput] = useState('');
  
  const { 
    sendMessage, 
    isStreaming, 
    isStopping,
    stopStreaming,
    chatMode,
    setChatMode,
    documentOptions,
    selectedDocumentId,
    setSelectedDocumentId,
    refreshDocumentOptions
  } = useChatStore();

  React.useEffect(() => {
    refreshDocumentOptions();
  }, [refreshDocumentOptions]);

  const handleSubmit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!input.trim() || isStreaming) return;
    if (chatMode === CHAT_MODES.DOCUMENT && !selectedDocumentId) return;
    
    const content = input;
    setInput('');
    await sendMessage(content);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="w-full flex flex-col items-center">
      {/* Mode Toolbar — hidden on narrow screens, shown on desktop (xl+) */}
      <div className="hidden xl:flex flex-wrap items-center justify-center gap-2 mb-4 bg-background/60 backdrop-blur-xl px-2 py-1.5 rounded-full border border-border/50 shadow-sm transition-all">
        <button
          disabled={isStreaming}
          onClick={() => setChatMode(CHAT_MODES.DOCUMENT)}
          className={`px-4 py-1.5 text-xs font-medium rounded-full transition-colors ${chatMode === CHAT_MODES.DOCUMENT ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-secondary/80'}`}
        >
          Document
        </button>
        <button
          disabled={isStreaming}
          onClick={() => setChatMode(CHAT_MODES.AUTO_DOCUMENT)}
          className={`px-4 py-1.5 text-xs font-medium rounded-full transition-colors ${chatMode === CHAT_MODES.AUTO_DOCUMENT ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-secondary/80'}`}
        >
          Auto Knowledge
        </button>
        <button
          disabled={isStreaming}
          onClick={() => setChatMode(CHAT_MODES.OPEN_CHAT)}
          className={`px-4 py-1.5 text-xs font-medium rounded-full transition-colors ${chatMode === CHAT_MODES.OPEN_CHAT ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-secondary/80'}`}
        >
          Open Chat
        </button>
      </div>

      {chatMode === CHAT_MODES.DOCUMENT && (
        <div className="w-full mb-3 px-4">
          <select 
            value={selectedDocumentId} 
            onChange={(e) => setSelectedDocumentId(e.target.value)}
            disabled={isStreaming}
            className="w-full bg-white dark:bg-[#202126] border border-black/10 dark:border-white/10 rounded-lg p-2 text-sm text-gray-700 dark:text-gray-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/50"
          >
            <option value="">-- Select a document --</option>
            {documentOptions.map(doc => (
              <option key={doc.documentId} value={doc.documentId}>
                {doc.documentName}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Stop Button */}
      {isStreaming && (
        <button 
          onClick={stopStreaming}
          disabled={isStopping}
          className="mb-3 flex items-center gap-2 px-4 py-1.5 rounded-full bg-background border border-border text-sm font-medium text-muted-foreground hover:bg-secondary/50 shadow-sm transition-colors"
        >
          <StopCircle size={16} className={isStopping ? "animate-pulse text-destructive" : "text-muted-foreground"} />
          {isStopping ? 'Stopping...' : 'Stop generating'}
        </button>
      )}

      {/* Input Box */}
      <form 
        onSubmit={handleSubmit}
        className="w-full bg-secondary/30 backdrop-blur-xl border border-border/50 rounded-2xl flex flex-col shadow-sm focus-within:shadow-md focus-within:bg-background/80 focus-within:border-primary/30 transition-all duration-300"
      >
        <TextareaAutosize
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isStreaming}
          placeholder={chatMode === CHAT_MODES.DOCUMENT ? "Ask about the document..." : "Message Pipeline RAG..."}
          className="w-full min-h-[52px] bg-transparent resize-none outline-none py-3 px-4 text-foreground placeholder-muted-foreground disabled:opacity-50"
          minRows={1}
          maxRows={8}
        />
        
        <div className="flex justify-end items-center px-2 pb-2">
          <button
            type="submit"
            disabled={!input.trim() || isStreaming || (chatMode === CHAT_MODES.DOCUMENT && !selectedDocumentId)}
            className="p-1.5 rounded-lg bg-primary text-primary-foreground disabled:opacity-50 disabled:bg-secondary disabled:text-muted-foreground transition-colors"
          >
            <ArrowUp size={20} />
          </button>
        </div>
      </form>
    </div>
  );
};
