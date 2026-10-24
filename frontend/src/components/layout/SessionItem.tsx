import { useEffect, useRef, useState } from 'react';
import { MessageSquare, MoreHorizontal, Pencil, Pin, PinOff, Trash2 } from 'lucide-react';
import { clsx } from 'clsx';
import { ConfirmDialog } from '../ui/ConfirmDialog';
import { Dropdown, type DropdownItem } from '../ui/Dropdown';
import { IconButton } from '../ui/IconButton';
import { Input } from '../ui/Field';
import { sessionTitle } from '../../lib/sessionUtils';
import { formatRelativeTime, sessionTime } from '../../lib/sessionGrouping';
import type { ChatSession } from '../../types/api';

export interface SessionItemProps {
  session: ChatSession;
  /** 当前正在浏览的会话 */
  active: boolean;
  /** 流式生成中：切换会打断回答，所以只禁用跳转，不隐藏条目 */
  disabled?: boolean;
  now: number;
  onSelect: (conversationId: string) => void;
  onRename: (conversationId: string, title: string) => void;
  onTogglePin: (conversationId: string, pinned: boolean) => void;
  onDelete: (conversationId: string) => void;
}

/**
 * 侧栏里的单个会话条目。
 * 整条是一个按钮（Tab 可达、aria-current 标记当前项），操作收进 IconButton +
 * Dropdown 菜单：原来这里的菜单是手写 div，没有 role、没有方向键、也不回收焦点。
 */
export function SessionItem({
  session,
  active,
  disabled = false,
  now,
  onSelect,
  onRename,
  onTogglePin,
  onDelete,
}: SessionItemProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  // Esc 取消后输入框还要失焦一次，用 ref 标记跳过那次「失焦即提交」
  const skipBlurSubmit = useRef(false);

  const title = sessionTitle(session);
  const timestamp = sessionTime(session);
  const iso = timestamp > 0 ? new Date(timestamp).toISOString() : undefined;
  const relative = formatRelativeTime(iso, now);

  useEffect(() => {
    if (editing) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [editing]);

  const beginEdit = () => {
    setDraft(session.title || title);
    setEditing(true);
  };

  const commitEdit = () => {
    if (!editing) return;
    skipBlurSubmit.current = true;
    setEditing(false);
    const next = draft.trim();
    // 空标题等于没改（store 也拒绝空标题），保持原样比清空更符合预期
    if (!next || next === session.title) return;
    onRename(session.conversationId, next);
  };

  const cancelEdit = () => {
    skipBlurSubmit.current = true;
    setEditing(false);
  };

  const menuItems: DropdownItem[] = [
    {
      key: 'pin',
      label: session.isPinned ? '取消置顶' : '置顶',
      icon: session.isPinned ? <PinOff size={12} /> : <Pin size={12} />,
      onSelect: () => onTogglePin(session.conversationId, !session.isPinned),
    },
    {
      key: 'rename',
      label: '重命名',
      icon: <Pencil size={12} />,
      onSelect: beginEdit,
    },
    {
      key: 'delete',
      label: '删除',
      icon: <Trash2 size={12} />,
      danger: true,
      onSelect: () => setConfirmingDelete(true),
    },
  ];

  return (
    <li
      className={clsx(
        'group relative rounded-md transition-colors',
        active ? 'bg-secondary' : 'hover:bg-secondary/60'
      )}
    >
      {/* 当前会话的选中态：左侧 2px 主色条 + 底色，不单靠颜色深浅区分 */}
      <span
        aria-hidden="true"
        className={clsx(
          'absolute inset-y-1 left-0 w-0.5 rounded-full',
          active ? 'bg-primary' : 'bg-transparent'
        )}
      />

      {editing ? (
        <div className="py-1 pl-3 pr-1.5">
          <Input
            ref={inputRef}
            value={draft}
            aria-label="会话标题"
            className="h-7 px-1.5 text-xs"
            onChange={(event) => setDraft(event.target.value)}
            onBlur={() => {
              if (skipBlurSubmit.current) {
                skipBlurSubmit.current = false;
                return;
              }
              commitEdit();
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
                commitEdit();
              } else if (event.key === 'Escape') {
                event.preventDefault();
                event.stopPropagation();
                cancelEdit();
              }
            }}
          />
        </div>
      ) : (
        <div className="flex items-center gap-0.5 pr-1">
          <button
            type="button"
            onClick={() => onSelect(session.conversationId)}
            disabled={disabled}
            aria-current={active ? 'page' : undefined}
            className="flex min-w-0 flex-1 items-start gap-2 rounded-md py-1.5 pl-3 pr-1 text-left disabled:cursor-not-allowed disabled:opacity-60"
          >
            <MessageSquare
              size={14}
              aria-hidden="true"
              className={clsx('mt-0.5 shrink-0', active ? 'text-primary' : 'text-muted-foreground')}
            />
            <span className="min-w-0 flex-1">
              <span
                className={clsx(
                  'block truncate text-xs',
                  active ? 'font-medium text-foreground' : 'text-foreground/90'
                )}
              >
                {title}
              </span>
              <span className="mt-0.5 flex items-center gap-1.5 text-2xs text-muted-foreground">
                {relative ? <time dateTime={iso}>{relative}</time> : <span>时间未知</span>}
                {session.running ? (
                  <>
                    <span className="h-1.5 w-1.5 rounded-full bg-primary" aria-hidden="true" />
                    <span>生成中</span>
                  </>
                ) : null}
              </span>
            </span>
          </button>

          {/* hover / 键盘聚焦到菜单时才显形，避免每行都挂一个常驻图标；
              Tab 到它时 group-focus-within 生效，所以不会聚焦到一个看不见的按钮 */}
          <div className="shrink-0 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
            <Dropdown
              menuLabel={`会话操作：${title}`}
              items={menuItems}
              trigger={(props) => (
                <IconButton
                  {...props}
                  label={`会话操作：${title}`}
                  icon={<MoreHorizontal size={14} aria-hidden="true" />}
                  size="sm"
                  disabled={disabled}
                />
              )}
            />
          </div>
        </div>
      )}

      <ConfirmDialog
        open={confirmingDelete}
        title="删除这个会话？"
        description={`「${title}」及其中全部问答将被永久删除，无法恢复。`}
        confirmLabel="删除"
        cancelLabel="取消"
        danger
        onCancel={() => setConfirmingDelete(false)}
        onConfirm={() => {
          setConfirmingDelete(false);
          onDelete(session.conversationId);
        }}
      />
    </li>
  );
}
