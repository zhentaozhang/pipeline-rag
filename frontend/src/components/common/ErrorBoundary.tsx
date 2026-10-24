import { Component, type ErrorInfo, type ReactNode } from 'react';
import { AlertTriangle, Copy, RefreshCw } from 'lucide-react';
import { Button } from '../ui/Button';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
  copied: boolean;
}

/**
 * 渲染兜底。之前只有一句"刷新页面"，用户既不知道发生了什么，
 * 也没法把错误信息交给开发排查。现在给出：发生了什么 / 可以怎么做 / 错误详情（可复制）。
 */
export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
    copied: false,
  };

  public static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error, copied: false };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    // 保留完整堆栈：生产环境没有 sourcemap 时，这行日志是唯一线索
    console.error('[ErrorBoundary] 未捕获的渲染错误:', error, errorInfo.componentStack);
  }

  private handleReload = () => {
    window.location.reload();
  };

  private handleCopy = async () => {
    const detail = [
      this.state.error?.message ?? '未知错误',
      '',
      this.state.error?.stack ?? '',
      '',
      `URL: ${window.location.href}`,
      `UA: ${navigator.userAgent}`,
    ].join('\n');
    try {
      await navigator.clipboard.writeText(detail);
      this.setState({ copied: true });
      window.setTimeout(() => this.setState({ copied: false }), 2000);
    } catch {
      this.setState({ copied: false });
    }
  };

  public render() {
    if (!this.state.hasError) return this.props.children;
    if (this.props.fallback) return this.props.fallback;

    return (
      <div className="flex h-full min-h-[60vh] items-center justify-center bg-background p-8">
        <div className="w-full max-w-md rounded-xl border border-border bg-card p-6 text-center shadow-sm">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-destructive/10 text-destructive">
            <AlertTriangle size={24} aria-hidden="true" />
          </div>
          <h1 className="text-base font-semibold text-foreground">页面出错了</h1>
          <p className="mt-2 text-fine leading-relaxed text-muted-foreground">
            这个页面在渲染时抛出了未捕获的异常，其他功能不受影响。可以先刷新重试，若反复出现，请复制错误详情反馈给维护者。
          </p>

          <p className="mt-3 rounded-md bg-destructive/5 px-3 py-2 text-left font-mono text-2xs leading-relaxed text-destructive break-words">
            {this.state.error?.message || '未知错误'}
          </p>

          <div className="mt-5 flex justify-center gap-2">
            <Button size="sm" onClick={this.handleReload}>
              <RefreshCw size={14} aria-hidden="true" />
              刷新页面
            </Button>
            <Button size="sm" variant="outline" onClick={this.handleCopy}>
              <Copy size={14} aria-hidden="true" />
              {this.state.copied ? '已复制' : '复制错误详情'}
            </Button>
          </div>

          {this.state.error?.stack ? (
            <details className="mt-5 text-left">
              <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">
                查看技术细节
              </summary>
              <pre className="mt-2 max-h-48 overflow-auto rounded-md bg-secondary/60 p-3 text-2xs leading-relaxed text-muted-foreground">
                {this.state.error.stack}
              </pre>
            </details>
          ) : null}
        </div>
      </div>
    );
  }
}
