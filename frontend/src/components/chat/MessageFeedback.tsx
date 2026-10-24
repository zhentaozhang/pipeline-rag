import React, { useState } from 'react';
import { Copy, ThumbsDown, ThumbsUp } from 'lucide-react';
import type { Message } from './MessageList';
import { Button } from '../ui/Button';
import { IconButton } from '../ui/IconButton';
import { useChatStore } from '../../store/chatStore';
import { chatApi } from '../../lib/api';
import { toast } from '../../lib/toast';
import { errorMessage } from '../../lib/utils';

/** 反馈接口要的是 exchange 号；新消息可能还没有，只能从 id 里反推 */
function resolveExchangeId(message: Message): string | null {
  if (typeof message.exchangeId === 'number') return String(message.exchangeId);
  const match = /^exchange-(\d+)-/.exec(message.id);
  return match ? match[1] : null;
}

/** 一条回答的操作行：复制、点赞、点踩（点踩展开"期望答案"表单） */
export const MessageFeedback: React.FC<{ message: Message }> = ({ message }) => {
  const currentConversationId = useChatStore((state) => state.currentConversationId);
  const [panelOpen, setPanelOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [groundTruth, setGroundTruth] = useState('');
  const fieldId = React.useId();

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      toast({ title: '回答已复制', variant: 'success' });
    } catch {
      // 非安全上下文下 clipboard 不可用，明确提示而不是假装成功
      toast({ title: '复制失败', description: '当前环境不允许访问剪贴板，请手动选中复制', variant: 'error' });
    }
  };

  const submit = async (value: string) => {
    const exchangeId = resolveExchangeId(message);
    if (!exchangeId) {
      toast({ title: '无法提交反馈', description: '这条回答还没有对应的交换记录', variant: 'error' });
      return;
    }
    setBusy(true);
    try {
      await chatApi.submitFeedback(currentConversationId, exchangeId, value);
      setDone(true);
      setPanelOpen(false);
      toast({ title: '反馈已提交', description: '感谢校对，我们会用它改进检索与生成', variant: 'success' });
    } catch (error) {
      toast({ title: '反馈提交失败', description: errorMessage(error, '请稍后重试'), variant: 'error' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-1 border-t border-border/40 pt-2">
      <IconButton label="复制这条回答" hint="复制" icon={<Copy size={14} />} size="sm" onClick={() => void handleCopy()} />
      <IconButton
        label="这条回答有帮助"
        hint="有帮助"
        icon={<ThumbsUp size={14} />}
        size="sm"
        disabled={busy || done}
        onClick={() => void submit(message.content)}
      />
      <IconButton
        label="这条回答有问题，填写正确答案"
        hint="有问题"
        icon={<ThumbsDown size={14} />}
        size="sm"
        aria-expanded={panelOpen}
        aria-controls={`${fieldId}-panel`}
        disabled={busy}
        onClick={() => setPanelOpen((open) => !open)}
      />
      {done ? <span className="text-xs text-muted-foreground">反馈已提交</span> : null}
      {panelOpen ? (
        <form
          id={`${fieldId}-panel`}
          className="mt-2 w-full space-y-2"
          onSubmit={(event) => {
            event.preventDefault();
            void submit(groundTruth.trim());
          }}
        >
          <label className="sr-only" htmlFor={`${fieldId}-ground-truth`}>
            期望的正确答案
          </label>
          <textarea
            id={`${fieldId}-ground-truth`}
            value={groundTruth}
            rows={3}
            placeholder="写下你期望的正确答案，帮助改进检索与生成"
            onChange={(event) => setGroundTruth(event.target.value)}
            className="w-full rounded-md border border-border bg-background px-3 py-2 text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          <div className="flex gap-2">
            <Button type="submit" size="sm" loading={busy} disabled={!groundTruth.trim()}>
              提交
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setPanelOpen(false)}>
              取消
            </Button>
          </div>
        </form>
      ) : null}
    </div>
  );
};
