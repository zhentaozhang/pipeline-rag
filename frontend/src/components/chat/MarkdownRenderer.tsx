import React from 'react';
import ReactMarkdown from 'react-markdown';
import type { Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { CodeBlock } from './CodeBlock';

interface MarkdownRendererProps {
  content: string;
}

// Ensure codeblocks are closed for syntax highlighter during streaming
function fixStreamingMarkdown(content: string) {
  const codeBlockCount = (content.match(/```/g) || []).length;
  if (codeBlockCount % 2 !== 0) {
    return content + '\n```';
  }
  return content;
}

export const MarkdownRenderer: React.FC<MarkdownRendererProps> = ({ content }) => {
  const safeContent = fixStreamingMarkdown(content);
  
  const components: Components = {
    code({ node, inline, className, children, ...props }: any) {
      const match = /language-(\w+)/.exec(className || '');
      const language = match ? match[1] : '';
      
      if (!inline && language) {
        return (
          <CodeBlock
            language={language}
            value={String(children).replace(/\n$/, '')}
          />
        );
      }
      
      return (
        <code className="bg-secondary/50 text-foreground rounded-md px-1.5 py-0.5 text-sm font-mono" {...props}>
          {children}
        </code>
      );
    },
    p({ children }) {
      return <p className="mb-4 text-[16px] leading-[1.6] text-foreground">{children}</p>;
    },
    h1({ children }) {
      return <h1 className="text-2xl font-bold mt-6 mb-4">{children}</h1>;
    },
    h2({ children }) {
      return <h2 className="text-xl font-bold mt-6 mb-3">{children}</h2>;
    },
    h3({ children }) {
      return <h3 className="text-lg font-bold mt-5 mb-2">{children}</h3>;
    },
    ul({ children }) {
      return <ul className="list-disc pl-6 mb-4 space-y-1">{children}</ul>;
    },
    ol({ children }) {
      return <ol className="list-decimal pl-6 mb-4 space-y-1">{children}</ol>;
    },
    li({ children }) {
      return <li className="text-[16px] leading-[1.6]">{children}</li>;
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
        <a href={href} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
          {children}
        </a>
      );
    },
    table({ children }) {
      return (
        <div className="overflow-x-auto my-4">
          <table className="min-w-full border border-border/50 rounded-lg">
            {children}
          </table>
        </div>
      );
    },
    th({ children }) {
      return <th className="bg-secondary/30 text-muted-foreground px-4 py-2 text-left font-semibold border-b border-border/50">{children}</th>;
    },
    td({ children }) {
      return <td className="px-4 py-2 border-b border-border/50">{children}</td>;
    }
  };

  return (
    <div className="max-w-none break-words">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={components}
      >
        {safeContent}
      </ReactMarkdown>
    </div>
  );
};
