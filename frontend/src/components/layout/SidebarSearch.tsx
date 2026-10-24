import { useId, useRef, type KeyboardEvent, type RefObject } from 'react';
import { Search, X } from 'lucide-react';
import { Input } from '../ui/Field';
import { IconButton } from '../ui/IconButton';

interface SidebarSearchProps {
  value: string;
  onChange: (value: string) => void;
  /** 抽屉打开时由 Sidebar 聚焦到这里 */
  inputRef?: RefObject<HTMLInputElement | null>;
}

/**
 * 会话搜索框。输入即筛选（纯本地比较，没必要做防抖——防抖只会让输入看起来卡）。
 * Esc 先清空搜索词；本来就是空的就让事件冒泡，交给抽屉去关闭。
 */
export function SidebarSearch({ value, onChange, inputRef }: SidebarSearchProps) {
  const id = useId();
  const fallbackRef = useRef<HTMLInputElement>(null);
  const ref = inputRef ?? fallbackRef;

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== 'Escape' || !value) return;
    event.preventDefault();
    event.stopPropagation();
    onChange('');
  };

  return (
    <div role="search" className="px-2 pt-2 pb-1">
      <label htmlFor={id} className="sr-only">
        搜索会话
      </label>
      <div className="relative">
        <Search
          size={14}
          aria-hidden="true"
          className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground"
        />
        <Input
          id={id}
          ref={ref}
          type="text"
          value={value}
          placeholder="搜索会话标题…"
          autoComplete="off"
          className="h-8 pl-7 pr-8 text-xs"
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={handleKeyDown}
        />
        {value ? (
          <IconButton
            label="清空搜索"
            icon={<X size={14} aria-hidden="true" />}
            size="sm"
            onClick={() => {
              onChange('');
              ref.current?.focus();
            }}
            className="absolute right-0.5 top-1/2 -translate-y-1/2"
          />
        ) : null}
      </div>
    </div>
  );
}
