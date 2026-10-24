import React from 'react';
import ReactMarkdown from 'react-markdown';
import type { Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { CodeBlock } from './CodeBlock';

interface CodeProps extends React.HTMLAttributes<HTMLElement> {
  inline?: boolean;
  className?: string;
  children?: React.ReactNode;
}

interface MarkdownRendererProps {
  content: string;
}

/** 流式过程中最后一个代码块可能还没闭合，先补上闭合标记，避免整段降级成正文 */
function fixStreamingMarkdown(content: string) {
  const codeBlockCount = (content.match(/```/g) || []).length;
  if (codeBlockCount % 2 !== 0) {
    return content + '\n```';
  }
  return content;
}

const headingClass = {
  h1: 'text-2xl font-bold mt-6 mb-4',
  h2: 'text-xl font-bold mt-6 mb-3',
  h3: 'text-lg font-bold mt-5 mb-2',
  h4: 'text-base font-semibold mt-4 mb-2',
  h5: 'text-sm font-semibold mt-3 mb-1.5',
  h6: 'text-2xs font-semibold uppercase tracking-wide text-muted-foreground mt-3 mb-1.5',
} as const;

export const MarkdownRenderer: React.FC<MarkdownRendererProps> = ({ content }) => {
  const safeContent = fixStreamingMarkdown(content);

  const components: Components = {
    code({ inline, className, children, ...props }: CodeProps) {
      const match = /language-(\w+)/.exec(className || '');
      const language = match ? match[1] : '';

      if (!inline && language) {
        return <CodeBlock language={language} value={String(children).replace(/\n$/, '')} />;
      }

      return (
        <code className="bg-secondary/50 text-foreground rounded-md px-1.5 py-0.5 text-sm font-mono" {...props}>
          {children}
        </code>
      );
    },
    p({ children }) {
      return <p className="mb-4 text-base leading-[1.6] text-foreground">{children}</p>;
    },
    h1({ children }) {
      return <h1 className={headingClass.h1}>{children}</h1>;
    },
    h2({ children }) {
      return <h2 className={headingClass.h2}>{children}</h2>;
    },
    h3({ children }) {
      return <h3 className={headingClass.h3}>{children}</h3>;
    },
    h4({ children }) {
      return <h4 className={headingClass.h4}>{children}</h4>;
    },
    h5({ children }) {
      return <h5 className={headingClass.h5}>{children}</h5>;
    },
    h6({ children }) {
      return <h6 className={headingClass.h6}>{children}</h6>;
    },
    ul({ children }) {
      return <ul className="list-disc pl-6 mb-4 space-y-1">{children}</ul>;
    },
    ol({ children }) {
      return <ol className="list-decimal pl-6 mb-4 space-y-1">{children}</ol>;
    },
    li({ children }) {
      return <li className="text-base leading-[1.6]">{children}</li>;
    },
    blockquote({ children }) {
      return (
        <blockquote className="border-l-4 border-border/50 pl-4 py-1 my-4 text-muted-foreground italic">
          {children}
        </blockquote>
      );
    },
    a({ href, children }) {
      return (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background rounded-sm"
        >
          {children}
          {/* 新标签页打开这件事对读屏用户是不可见的，用 sr-only 补一句提示 */}
          <span className="sr-only">（在新标签页打开）</span>
        </a>
      );
    },
    table({ children }) {
      // 窄屏下表格必须能横向滚动，否则整段回答会把布局撑破
      return (
        <div className="overflow-x-auto my-4 -mx-1 px-1">
          <table className="min-w-full border border-border/50 rounded-lg">{children}</table>
        </div>
      );
    },
    th({ children }) {
      return (
        <th className="bg-secondary/30 text-muted-foreground px-4 py-2 text-left font-semibold border-b border-border/50">
          {children}
        </th>
      );
    },
    td({ children }) {
      return <td className="px-4 py-2 border-b border-border/50">{children}</td>;
    }
  };

  return (
    <div className="max-w-none break-words">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {safeContent}
      </ReactMarkdown>
    </div>
  );
};
