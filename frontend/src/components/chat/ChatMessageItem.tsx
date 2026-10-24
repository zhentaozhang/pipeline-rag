import React, { useState } from 'react';
import { ChevronDown, ChevronRight, Pencil } from 'lucide-react';
import type { Message } from './MessageList';
import { MarkdownRenderer } from './MarkdownRenderer';
import { MessageFeedback } from './MessageFeedback';
import { MessageReferences } from './MessageReferences';
import { Alert } from '../ui/Alert';
import { Button } from '../ui/Button';
import { IconButton } from '../ui/IconButton';
import { useChatStore } from '../../store/chatStore';

/** 折叠区（知识路由 / 思考过程）：统一 aria-expanded + aria-controls，键盘可达 */
function Disclosure({
  id,
  label,
  open,
  onToggle,
  children,
}: {
  id: string;
  label: string;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-3">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={onToggle}
        className="inline-flex items-center gap-1.5 rounded-md px-1.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
      >
        {open ? <ChevronDown size={14} aria-hidden="true" /> : <ChevronRight size={14} aria-hidden="true" />}
        {label}
      </button>
      {open ? (
        <div id={id} className="mt-2">
          {children}
        </div>
      ) : null}
    </div>
  );
}

const ChatMessageItemImpl: React.FC<{ message: Message }> = ({ message }) => {
  const isStreaming = useChatStore((state) => state.isStreaming);
  const regenerate = useChatStore((state) => state.regenerate);
  const editAndResend = useChatStore((state) => state.editAndResend);

  const [thinkingOpen, setThinkingOpen] = useState(false);
  const [routeOpen, setRouteOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draftText, setDraftText] = useState(message.content);
  const panelId = React.useId();

  const thinkingSteps = message.thinkingSteps ?? [];
  const isFailed = message.status === 'FAILED';
  const isRunning = message.status === 'RUNNING';
  const showActions = !isRunning && !isFailed && Boolean(message.content);

  if (message.role === 'user') {
    return (
      <div className="mt-8 mb-6">
        <div className="flex items-start justify-between gap-2">
          <h2 className="font-heading text-2xl font-semibold leading-snug break-words text-foreground">
            {message.content}
          </h2>
          <IconButton
            label="编辑这条提问并重新发送"
            icon={<Pencil size={14} />}
            size="sm"
            variant="ghost"
            disabled={isStreaming}
            onClick={() => {
              setDraftText(message.content);
              setEditing((open) => !open);
            }}
          />
        </div>
        {editing ? (
          <form
            className="mt-3 space-y-2"
            onSubmit={(event) => {
              event.preventDefault();
              setEditing(false);
              void editAndResend(message.id, draftText);
            }}
          >
            <label className="sr-only" htmlFor={`${panelId}-edit`}>
              修改提问内容
            </label>
            <textarea
              id={`${panelId}-edit`}
              value={draftText}
              rows={3}
              onChange={(event) => setDraftText(event.target.value)}
              className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
            <div className="flex gap-2">
              <Button type="submit" size="sm" disabled={!draftText.trim()}>
                重新发送
              </Button>
              <Button type="button" size="sm" variant="ghost" onClick={() => setEditing(false)}>
                取消
              </Button>
            </div>
          </form>
        ) : null}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {isFailed ? (
        <Alert
          variant="destructive"
          title="这一轮回答失败了"
          action={
            <Button size="sm" variant="outline" disabled={isStreaming} onClick={() => void regenerate(message.id)}>
              重试
            </Button>
          }
        >
          {message.errorMessage || '模型执行失败，可能是连接中断。重试会重新生成这条回答。'}
        </Alert>
      ) : null}

      {isRunning && !message.content ? (
        <p className="text-sm text-muted-foreground" aria-live="polite">
          <span className="animate-pulse">正在生成回答…</span>
        </p>
      ) : null}

      {message.statusText ? <p className="text-xs text-muted-foreground">{message.statusText}</p> : null}

      {message.routeExplain ? (
        <Disclosure
          id={`${panelId}-route`}
          label="知识路由详情"
          open={routeOpen}
          onToggle={() => setRouteOpen((open) => !open)}
        >
          <pre className="max-h-64 overflow-auto rounded-md bg-secondary/40 p-3 text-xs text-muted-foreground">
            {JSON.stringify(message.routeExplain, null, 2)}
          </pre>
        </Disclosure>
      ) : null}

      {thinkingSteps.length > 0 ? (
        <Disclosure
          id={`${panelId}-thinking`}
          label={`思考过程（${thinkingSteps.length}）`}
          open={thinkingOpen}
          onToggle={() => setThinkingOpen((open) => !open)}
        >
          <ol className="space-y-2">
            {thinkingSteps.map((step, index) => (
              <li
                key={`${panelId}-step-${index}`}
                className="flex gap-2 text-xs leading-relaxed text-muted-foreground"
              >
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-secondary text-2xs">
                  {index + 1}
                </span>
                <span className="min-w-0 whitespace-pre-wrap break-words">{step}</span>
              </li>
            ))}
          </ol>
        </Disclosure>
      ) : null}

      {message.content ? <MarkdownRenderer content={message.content} /> : null}

      {message.references && message.references.length > 0 ? (
        <MessageReferences references={message.references} recommendations={message.recommendations ?? []} />
      ) : null}

      {showActions ? <MessageFeedback message={message} /> : null}
    </div>
  );
};

/** 历史消息靠这个 memo 保持稳定：流式 token 只改 streamingDraft，不会让它们重渲染 */
export const ChatMessageItem = React.memo(ChatMessageItemImpl);
