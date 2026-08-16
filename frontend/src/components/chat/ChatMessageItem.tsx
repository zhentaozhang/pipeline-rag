import React, { useState } from 'react';
import { ChevronDown, ChevronRight, FileText, ThumbsUp, ThumbsDown, Check, RefreshCw } from 'lucide-react';
import { MarkdownRenderer } from './MarkdownRenderer';
import type { Message } from './MessageList';
import { useChatStore } from '../../store/chatStore';
import { chatApi } from '../../lib/api';

interface ChatMessageItemProps {
  message: Message;
}

export const ChatMessageItem: React.FC<ChatMessageItemProps> = React.memo(({ message }) => {
  const [thinkingOpen, setThinkingOpen] = useState(false);
  const [routeOpen, setRouteOpen] = useState(false);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [groundTruth, setGroundTruth] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [feedbackSuccess, setFeedbackSuccess] = useState(false);
  const [expandedRefs, setExpandedRefs] = useState<Record<string, boolean>>({});
  const sendMessage = useChatStore((state) => state.sendMessage);
  const isStreaming = useChatStore((state) => state.isStreaming);

  const currentConversationId = useChatStore((state) => state.currentConversationId);

  const handleFeedbackSubmit = async () => {
    if (!groundTruth.trim() || !currentConversationId) return;
    try {
      setIsSubmitting(true);
      // We extract exchangeId from the message id, or just assume message.id is the exchangeId for assistant messages
      // Wait, in useChatStore, the message.id for assistant is the exchangeId, unless it's a temp id.
      // Usually it's just message.id
      const exchangeIdStr = message.id; 
      
      await chatApi.submitFeedback(currentConversationId, exchangeIdStr, groundTruth);
      setFeedbackSuccess(true);
      setFeedbackOpen(false);
    } catch (e) {
      console.error('Failed to submit feedback:', e);
    } finally {
      setIsSubmitting(false);
    }
  };

  if (message.role === 'user') {
    return (
      <div className="flex w-full justify-start mt-8 mb-6">
        <div className="max-w-3xl w-full text-foreground text-2xl font-semibold font-heading tracking-tight leading-tight">
          <div className="whitespace-pre-wrap">{message.content}</div>
        </div>
      </div>
    );
  }

  // Assistant Message
  return (
    <div className="flex w-full mb-12">
      <div className="flex-1 min-w-0">
        
        {/* Error State */}
        {message.status === 'FAILED' && (
          <div className="mb-6 p-4 bg-destructive/10 text-destructive rounded-xl text-sm border border-destructive/20 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
            <div className="flex items-start gap-3">
              <svg className="w-5 h-5 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
              <div>
                <strong className="block font-medium mb-1">执行失败</strong>
                {message.errorMessage || '请求处理过程中发生了未知错误。'}
              </div>
            </div>
            {!isStreaming && (
              <button 
                onClick={() => {
                  const state = useChatStore.getState();
                  const idx = state.messages.findIndex(m => m.id === message.id);
                  if (idx > 0) {
                    for (let i = idx - 1; i >= 0; i--) {
                      if (state.messages[i].role === 'user') {
                        state.sendMessage(state.messages[i].content);
                        break;
                      }
                    }
                  }
                }}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-destructive text-destructive-foreground hover:bg-destructive/90 rounded-md text-xs font-medium transition-colors shrink-0 shadow-sm"
              >
                <RefreshCw size={14} />
                重试
              </button>
            )}
          </div>
        )}

        {/* Status indicator for running */}
        {message.status === 'RUNNING' && !message.content && (!message.thinkingSteps || message.thinkingSteps.length === 0) && (
          <div className="flex items-center gap-2 text-muted-foreground text-sm italic mb-4">
            <span className="relative flex h-3 w-3">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary/50 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-3 w-3 bg-primary"></span>
            </span>
            思考中...
          </div>
        )}
        
        {/* Route Explanations */}
        {message.routeExplain && Object.keys(message.routeExplain).length > 0 && (
          <div className="mb-6 text-sm text-muted-foreground overflow-hidden">
             <button 
               onClick={() => setRouteOpen(!routeOpen)}
               className="flex items-center gap-2 px-1 py-1 hover:text-foreground transition-colors group"
             >
               {routeOpen ? <ChevronDown size={14} className="opacity-70" /> : <ChevronRight size={14} className="opacity-70" />}
               <span className="font-medium text-xs tracking-wider uppercase opacity-70 group-hover:opacity-100 transition-opacity">知识路由详情</span>
             </button>
             {routeOpen && (
               <div className="mt-2 p-3 border-l-2 border-border text-muted-foreground bg-secondary/10">
                 <pre className="text-xs font-mono overflow-x-auto whitespace-pre-wrap leading-relaxed">
                   {JSON.stringify(message.routeExplain, null, 2)}
                 </pre>
               </div>
             )}
          </div>
        )}

        {/* Thinking Steps */}
        {message.thinkingSteps && message.thinkingSteps.length > 0 && (
          <div className="mb-6 text-sm text-muted-foreground overflow-hidden">
             <button 
               onClick={() => setThinkingOpen(!thinkingOpen)}
               className="flex items-center gap-2 px-1 py-1 hover:text-foreground transition-colors group"
             >
               {thinkingOpen ? <ChevronDown size={14} className="opacity-70" /> : <ChevronRight size={14} className="opacity-70" />}
               <span className="font-medium text-xs tracking-wider uppercase opacity-70 group-hover:opacity-100 transition-opacity">思考过程 ({message.thinkingSteps.length})</span>
               {message.status === 'RUNNING' && (
                 <span className="flex h-2 w-2 relative ml-1">
                   <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary/50 opacity-75"></span>
                   <span className="relative inline-flex rounded-full h-2 w-2 bg-primary"></span>
                 </span>
               )}
             </button>
             {thinkingOpen && (
               <div className="mt-2 p-3 border-l-2 border-border text-muted-foreground space-y-3 bg-secondary/5">
                 {message.thinkingSteps.map((step, idx) => (
                   <div key={idx} className="flex gap-3 text-xs leading-relaxed items-start">
                     <span className="shrink-0 flex items-center justify-center w-5 h-5 rounded-full bg-blue-500/90 text-white text-[10px] font-bold select-none">{idx + 1}</span>
                     <span className="opacity-80 pt-0.5">{step}</span>
                   </div>
                 ))}
               </div>
             )}
          </div>
        )}

        {/* Markdown Content */}
        {message.content && (
          <div className="text-foreground text-base leading-relaxed tracking-normal mt-2">
            <MarkdownRenderer content={message.content} />
          </div>
        )}
        
        {/* References */}
        {message.references && message.references.length > 0 && (
          <div className="mt-8 pt-6 border-t border-border/50">
            <div className="text-xs font-bold text-muted-foreground uppercase tracking-wider mb-4 opacity-80">Sources</div>
            <div className="flex flex-wrap gap-2">
              {message.references.map((ref, idx) => {
                const refKey = String(ref.id ?? idx);
                const expanded = !!expandedRefs[refKey];
                const isClickable = !!ref.url;
                const Component = isClickable ? 'a' : 'div';
                const props = isClickable ? { href: ref.url, target: "_blank", rel: "noopener noreferrer" } : {};
                const hasContent = !!ref.content;
                return (
                  <div key={idx} className="flex flex-col gap-1">
                    <Component
                      {...props}
                      onClick={hasContent && !isClickable ? () => setExpandedRefs((prev) => ({ ...prev, [refKey]: !prev[refKey] })) : undefined}
                      className={`flex flex-col gap-1.5 p-3 bg-secondary/30 border border-border/50 rounded-xl text-xs hover:bg-secondary/50 transition-colors ${isClickable ? 'cursor-pointer hover:border-primary/50 shadow-sm hover:shadow' : hasContent ? 'cursor-pointer hover:border-primary/50 shadow-sm' : 'cursor-default shadow-sm'} min-w-[220px] max-w-[280px]`}
                    >
                      <div className="flex items-center gap-2 font-medium text-foreground">
                        <FileText size={14} className="text-primary/70 shrink-0" />
                        <span className="truncate">{ref.title || ref.name || `[${idx + 1}] Reference`}</span>
                        {hasContent && !isClickable && (
                          <span className="ml-auto text-muted-foreground/60 flex items-center">
                            {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                          </span>
                        )}
                      </div>
                      {ref.section_title && <div className="text-muted-foreground/80 truncate">章节: {ref.section_title}</div>}
                      <div className="flex items-center gap-2 mt-0.5">
                        {ref.source_type && <span className="px-1.5 py-0.5 rounded bg-primary/10 text-primary text-[9px] uppercase tracking-wider font-semibold">{ref.source_type}</span>}
                        {ref.doc_id && <span className="text-muted-foreground/60 text-[10px] font-mono bg-secondary/80 px-1.5 py-0.5 rounded">ID: {ref.doc_id}</span>}
                      </div>
                    </Component>
                    {/* P1-1 引用溯源：点击展开原文段落 */}
                    {expanded && hasContent && (
                      <div className="max-w-[280px] p-3 bg-card border border-border/40 rounded-xl text-xs text-foreground/90 leading-relaxed whitespace-pre-wrap">
                        {ref.content}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Recommendations */}
        {message.recommendations && message.recommendations.length > 0 && (
          <div className="mt-8">
            <div className="text-xs font-bold text-muted-foreground uppercase tracking-wider mb-4 opacity-80">Suggested Questions</div>
            <div className="flex flex-col gap-2 items-start">
              {message.recommendations.map((rec, idx) => (
                <button 
                  key={idx}
                  onClick={() => sendMessage(rec)}
                  className="text-left px-4 py-2.5 bg-secondary/30 hover:bg-secondary/80 border border-transparent rounded-xl text-sm text-muted-foreground hover:text-foreground transition-colors flex items-center gap-2 group w-full max-w-2xl"
                >
                  <span className="flex-1">{rec}</span>
                  <svg className="w-4 h-4 opacity-0 -ml-2 group-hover:opacity-100 group-hover:ml-0 transition-all text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" /></svg>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Feedback Section */}
        {message.status !== 'RUNNING' && message.status !== 'FAILED' && (
          <div className="mt-6 flex flex-col gap-3">
            <div className="flex items-center gap-2">
              <button
                onClick={async () => {
                  if (feedbackSuccess) return;
                  // Auto-submit thumbs up with current answer as ground truth
                  if (!currentConversationId) return;
                  try {
                    setIsSubmitting(true);
                    await chatApi.submitFeedback(currentConversationId, message.id, message.content);
                    setFeedbackSuccess(true);
                    setFeedbackOpen(false);
                  } catch (e) {
                    console.error('Failed to submit positive feedback:', e);
                  } finally {
                    setIsSubmitting(false);
                  }
                }}
                className={`p-1.5 rounded hover:bg-secondary text-muted-foreground transition-colors ${feedbackSuccess && !feedbackOpen ? 'text-green-500' : 'hover:text-foreground'}`}
                title="Good answer!"
                disabled={feedbackSuccess || isSubmitting}
              >
                <ThumbsUp size={16} />
              </button>
              <button
                onClick={() => setFeedbackOpen(!feedbackOpen)}
                className={`p-1.5 rounded hover:bg-secondary text-muted-foreground transition-colors ${feedbackOpen || (feedbackSuccess && feedbackOpen) ? 'text-primary' : 'hover:text-foreground'}`}
                title="Bad answer? Provide ground truth."
                disabled={feedbackSuccess && !feedbackOpen}
              >
                {feedbackSuccess && feedbackOpen ? <Check size={16} className="text-green-500" /> : <ThumbsDown size={16} />}
              </button>
              {feedbackSuccess && <span className="text-xs text-green-500">Feedback submitted!</span>}
            </div>

            {feedbackOpen && !feedbackSuccess && (
              <div className="p-4 bg-secondary/20 border border-border/50 rounded-xl max-w-2xl space-y-3">
                <div className="text-sm font-medium text-foreground">Provide Expected Answer (Ground Truth)</div>
                <div className="text-xs text-muted-foreground">Your feedback will be used to automatically test and improve the RAG pipeline.</div>
                <textarea
                  value={groundTruth}
                  onChange={(e) => setGroundTruth(e.target.value)}
                  className="w-full h-24 bg-background border border-border/50 rounded-lg p-3 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/30 transition-colors resize-none"
                  placeholder="Type the expected correct answer here..."
                />
                <div className="flex justify-end gap-2">
                  <button
                    onClick={() => setFeedbackOpen(false)}
                    className="px-3 py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleFeedbackSubmit}
                    disabled={isSubmitting || !groundTruth.trim()}
                    className="px-3 py-1.5 bg-primary text-primary-foreground text-xs font-medium rounded hover:bg-primary/90 transition-colors disabled:opacity-50 flex items-center gap-2"
                  >
                    {isSubmitting ? 'Submitting...' : 'Submit Feedback'}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
});
