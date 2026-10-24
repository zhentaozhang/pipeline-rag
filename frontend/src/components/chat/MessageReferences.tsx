import React, { useState } from 'react';
import { FileText } from 'lucide-react';
import type { ExchangeReference } from '../../types/api';
import { Button } from '../ui/Button';
import { useChatStore } from '../../store/chatStore';

interface MessageReferencesProps {
  references: ExchangeReference[];
  recommendations: string[];
}

/**
 * 引用溯源：来源卡片是「可展开的原文」而不是跳转链接，必须能被键盘操作，
 * 所以用 button + aria-expanded/aria-controls，列表语义用 ol/li，
 * Escape 收起（避免用户为了关掉它去找鼠标）。
 */
export const MessageReferences: React.FC<MessageReferencesProps> = ({ references, recommendations }) => {
  const [openKey, setOpenKey] = useState<string | null>(null);
  const isStreaming = useChatStore((state) => state.isStreaming);
  const sendMessage = useChatStore((state) => state.sendMessage);
  const panelId = React.useId();

  return (
    <>
      <section aria-label="参考来源" className="pt-2" onKeyDown={(event) => {
        if (event.key === 'Escape') setOpenKey(null);
      }}>
        <h3 className="mb-2 text-xs font-medium text-muted-foreground">参考来源（{references.length}）</h3>
        <ol className="flex flex-wrap gap-2">
          {references.map((reference, index) => {
            const key = String(reference.id ?? index);
            const title = String(reference.title ?? reference.name ?? reference.section_title ?? '未命名来源');
            const passage = typeof reference.content === 'string' ? reference.content : '';
            const url = typeof reference.url === 'string' ? reference.url : '';
            const meta = [reference.section_title, reference.source_type, reference.doc_id]
              .filter((value) => typeof value === 'string' && value)
              .join(' · ');
            const isOpen = openKey === key;
            const cardClass =
              'block w-full rounded-lg border border-border/50 bg-secondary/30 px-3 py-2 text-left transition-colors hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background';
            const body = (
              <>
                <span className="flex items-center gap-1.5 text-sm font-medium text-foreground">
                  <FileText size={14} aria-hidden="true" className="shrink-0 text-muted-foreground" />
                  <span className="truncate">{title}</span>
                </span>
                {meta ? <span className="mt-1 block truncate text-2xs text-muted-foreground">{meta}</span> : null}
              </>
            );
            return (
              <li key={key} className="min-w-[220px] max-w-[280px] flex-1">
                {passage ? (
                  <>
                    <button
                      type="button"
                      aria-expanded={isOpen}
                      aria-controls={`${panelId}-ref-${index}`}
                      onClick={() => setOpenKey(isOpen ? null : key)}
                      className={cardClass}
                    >
                      {body}
                      <span className="mt-1 block text-2xs text-muted-foreground">
                        {isOpen ? '收起原文' : '展开原文段落'}
                      </span>
                    </button>
                    {isOpen ? (
                      <div
                        id={`${panelId}-ref-${index}`}
                        className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded-md border border-border/50 bg-background p-3 text-xs leading-relaxed text-muted-foreground"
                      >
                        {passage}
                      </div>
                    ) : null}
                  </>
                ) : (
                  <a
                    href={url || undefined}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={cardClass}
                    aria-label={`打开外部来源：${title}`}
                  >
                    {body}
                  </a>
                )}
              </li>
            );
          })}
        </ol>
      </section>

      {recommendations.length > 0 ? (
        <section aria-label="推荐追问" className="pt-1">
          <h3 className="mb-2 text-xs font-medium text-muted-foreground">推荐追问</h3>
          <ul className="flex flex-wrap gap-2">
            {recommendations.map((item) => (
              <li key={item}>
                <Button
                  size="sm"
                  variant="outline"
                  className="rounded-full font-normal"
                  disabled={isStreaming}
                  onClick={() => void sendMessage(item)}
                >
                  {item}
                </Button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </>
  );
};
