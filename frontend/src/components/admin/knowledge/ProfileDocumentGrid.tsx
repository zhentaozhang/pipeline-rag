import React from 'react';
import { FileText, Plus } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import type { ManageDocument } from '../../../types/api';
import { AdminStatusBadge } from '../AdminStatusBadge';
import { Badge } from '../../../components/ui/Badge';
import { Button } from '../../../components/ui/Button';
import { EmptyState } from '../../../components/ui/EmptyState';
import { Skeleton } from '../../../components/ui/Skeleton';

interface Props {
  docs: ManageDocument[];
  loading: boolean;
  error: string;
  keyword: string;
  onRetry: () => void;
  onSelect: (documentId: string) => void;
}

/** 文档画像的候选列表：点卡片看画像，未完成的文档会标出来 */
export const ProfileDocumentGrid: React.FC<Props> = ({ docs, loading, error, keyword, onRetry, onSelect }) => {
  const navigate = useNavigate();
  if (loading) {
    return (
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
        {[0, 1, 2].map((key) => (
          <div key={key} className="rounded-xl border border-border bg-card p-4">
            <Skeleton lines={3} />
          </div>
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-xl border border-destructive/30 bg-card px-6 py-10 text-center">
        <p className="text-sm text-destructive">{error}</p>
        <Button size="sm" variant="outline" onClick={onRetry}>
          重试
        </Button>
      </div>
    );
  }

  if (docs.length === 0) {
    return (
      <EmptyState
        icon={<FileText size={20} aria-hidden="true" />}
        title={keyword ? '没有匹配的文档' : '还没有可分析的文档'}
        description={
          keyword
            ? '换个关键词试试，或者清空搜索框看全部文档。'
            : '画像来自已解析的文档，先去接入文档并完成解析。'
        }
        action={
          keyword ? null : (
            <Button size="sm" onClick={() => navigate('/admin/documents')}>
              <Plus size={13} aria-hidden="true" />
              去接入文档
            </Button>
          )
        }
      />
    );
  }

  return (
    <ul className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
      {docs.map((doc) => (
        <li key={doc.documentId}>
          <button
            type="button"
            onClick={() => onSelect(doc.documentId)}
            className="flex h-full w-full flex-col gap-2 rounded-xl border border-border bg-card p-4 text-left transition-colors hover:border-primary/50 hover:bg-secondary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <span className="flex items-start justify-between gap-2">
              <span className="min-w-0">
                <span className="block truncate text-sm font-medium text-foreground">{doc.documentName}</span>
                <span className="block truncate font-mono text-2xs text-muted-foreground">{doc.documentId}</span>
              </span>
              <AdminStatusBadge type="parse" label={doc.parseStatusName || '解析状态未知'} />
            </span>
            <span className="flex flex-wrap items-center gap-1.5">
              {doc.indexStatus === 3 ? (
                <Badge variant="success">画像可用</Badge>
              ) : (
                <Badge variant="warning">画像未完成</Badge>
              )}
              {doc.knowledgeScopeName ? <Badge variant="secondary">{doc.knowledgeScopeName}</Badge> : null}
            </span>
            <span className="mt-auto flex items-center justify-between gap-2 border-t border-border pt-2 text-2xs text-muted-foreground">
              <span>解析：{doc.parseStatusName || '—'}</span>
              <span>索引：{doc.indexStatusName || '—'}</span>
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
};