import React, { useEffect, useRef, useState } from 'react';
import { Check, Copy } from 'lucide-react';
import { PrismLight as SyntaxHighlighter } from 'react-syntax-highlighter';
import bash from 'react-syntax-highlighter/dist/esm/languages/prism/bash';
import css from 'react-syntax-highlighter/dist/esm/languages/prism/css';
import go from 'react-syntax-highlighter/dist/esm/languages/prism/go';
import java from 'react-syntax-highlighter/dist/esm/languages/prism/java';
import javascript from 'react-syntax-highlighter/dist/esm/languages/prism/javascript';
import json from 'react-syntax-highlighter/dist/esm/languages/prism/json';
import markup from 'react-syntax-highlighter/dist/esm/languages/prism/markup';
import python from 'react-syntax-highlighter/dist/esm/languages/prism/python';
import sql from 'react-syntax-highlighter/dist/esm/languages/prism/sql';
import typescript from 'react-syntax-highlighter/dist/esm/languages/prism/typescript';
import yaml from 'react-syntax-highlighter/dist/esm/languages/prism/yaml';
import vscDarkPlus from 'react-syntax-highlighter/dist/esm/styles/prism/vsc-dark-plus';
import { toast } from '../../lib/toast';

/**
 * 只注册企业知识库场景里真正会出现的语言。
 * 之前用的是 Prism 全量构建（300+ 语言），把 vendor 包顶到了 772 kB。
 * 逐条 registerLanguage 后，未注册语言会自动退回纯文本。
 */
const LANGUAGES: Record<string, string> = {
  bash,
  css,
  go,
  java,
  javascript,
  json,
  markup,
  python,
  sql,
  typescript,
  yaml,
};

Object.entries(LANGUAGES).forEach(([name, syntax]) => {
  SyntaxHighlighter.registerLanguage(name, syntax);
});

/** 把 markdown 里五花八门的语言标记归一到已注册的语言，归一不了就走纯文本。 */
const LANGUAGE_ALIASES: Record<string, string> = {
  js: 'javascript',
  jsx: 'javascript',
  mjs: 'javascript',
  cjs: 'javascript',
  ts: 'typescript',
  tsx: 'typescript',
  py: 'python',
  sh: 'bash',
  shell: 'bash',
  zsh: 'bash',
  console: 'bash',
  yml: 'yaml',
  html: 'markup',
  xml: 'markup',
  svg: 'markup',
  vue: 'markup',
  postgres: 'sql',
  postgresql: 'sql',
  mysql: 'sql',
  golang: 'go',
  jsonc: 'json',
  json5: 'json',
  text: 'text',
  plaintext: 'text',
  '': 'text',
};

function normalizeLanguage(language: string): string {
  const key = (language || '').trim().toLowerCase();
  const mapped = LANGUAGE_ALIASES[key] ?? key;
  return Object.prototype.hasOwnProperty.call(LANGUAGES, mapped) ? mapped : 'text';
}

interface CodeBlockProps {
  language: string;
  value: string;
}

export const CodeBlock: React.FC<CodeBlockProps> = ({ language, value }) => {
  const [copied, setCopied] = useState(false);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (copyTimer.current) clearTimeout(copyTimer.current);
    };
  }, []);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      // 非安全上下文（http）下 clipboard 不可用，明确告诉用户复制失败而不是静默
      toast({ title: '复制失败', description: '当前环境不允许访问剪贴板，请手动选中代码复制', variant: 'error' });
      return;
    }
    setCopied(true);
    toast({ title: '代码已复制', variant: 'success' });
    if (copyTimer.current) clearTimeout(copyTimer.current);
    copyTimer.current = setTimeout(() => {
      setCopied(false);
      copyTimer.current = null;
    }, 2000);
  };

  const resolvedLanguage = normalizeLanguage(language);
  const displayLanguage = resolvedLanguage === 'text' ? language || '文本' : resolvedLanguage;

  return (
    <div className="relative group rounded-md overflow-hidden bg-[#1e1e1e] my-4 border border-black/10 dark:border-white/10">
      <div className="flex items-center justify-between px-4 py-1.5 bg-[#2d2d2d] text-xs text-gray-400">
        <span className="lowercase">{displayLanguage}</span>
        <button
          type="button"
          onClick={handleCopy}
          aria-label={`复制 ${displayLanguage} 代码块`}
          title={copied ? '已复制' : '复制代码'}
          className="flex items-center gap-1.5 rounded-sm hover:text-gray-200 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-[#2d2d2d]"
        >
          {copied ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
          <span aria-live="polite">{copied ? '已复制' : '复制'}</span>
        </button>
      </div>
      <div className="p-4 text-fine leading-relaxed overflow-x-auto">
        <SyntaxHighlighter
          language={resolvedLanguage}
          style={vscDarkPlus}
          customStyle={{ margin: 0, padding: 0, background: 'transparent' }}
          wrapLines={true}
        >
          {value}
        </SyntaxHighlighter>
      </div>
    </div>
  );
};
