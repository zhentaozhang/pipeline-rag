import React, { useState } from 'react';
import { Unlink } from 'lucide-react';
import { manageApi } from '../../../lib/api';
import type { TopicDocument } from '../../../types/api';
import { Button } from '../../../components/ui/Button';
import { ConfirmDialog } from '../../../components/ui/ConfirmDialog';
import { DataTable, type DataTableColumn } from '../../../components/ui/DataTable';
import { IconButton } from '../../../components/ui/IconButton';
import { toast } from '../../../lib/toast';
import { actionFailure } from '../adminFormat';
import { formatDateTime } from '../../../lib/manageFormat';

interface Props {
  rows: TopicDocument[];
  loading: boolean;
  error: string;
  onRetry: () => void;
  onChanged: () => void;
  onAdd: () => void;
}

/** 主题下已绑定的文档；解绑后自动问答不再检索它 */
export const RelationTable: React.FC<Props> = ({ rows, loading, error, onRetry, onChanged, onAdd }) => {
  const [pending, setPending] = useState<TopicDocument | null>(null);

  const confirmRemove = async () => {
    if (!pending) return;
    const target = pending;
    setPending(null);
    const documentId = target.docId || target.documentId || '';
    try {
      await manageApi.removeTopicDocumentRelation({ topicCode: target.topicCode ?? '', documentId });
      toast({ title: '已解除关联', description: '这个文档不会再被该主题的问答检索到。', variant: 'success' });
      onChanged();
    } catch (removeError) {
      toast({ title: '解除关联失败', description: actionFailure(removeError, '解除关联'), variant: 'error' });
    }
  };

  const columns: DataTableColumn<TopicDocument>[] = [
    {
      key: 'document',
      header: '文档',
      render: (row) => (
        <span className="min-w-0">
          <span className="block truncate text-xs font-medium text-foreground">{row.documentName || row.title || row.documentId}</span>
          <span className="block truncate font-mono text-2xs text-muted-foreground">{row.documentId || row.docId}</span>
        </span>
      ),
    },
    { key: 'score', header: '关联分数', align: 'right', render: (row) => Number(row.relationScore ?? 0).toFixed(2) },
    { key: 'source', header: '来源', render: (row) => (row.relationSource === 'manual' ? '手动绑定' : row.relationSource || '未知') },
    {
      key: 'reason',
      header: '理由',
      render: (row) => <span className="line-clamp-2 max-w-[20rem] text-2xs text-muted-foreground">{row.reason || '未填写'}</span>,
    },
    { key: 'time', header: '绑定时间', align: 'right', render: (row) => formatDateTime(row.createTime) },
    {
      key: 'action',
      header: '操作',
      align: 'right',
      render: (row) => (
        <IconButton
          label={`解除关联 ${row.documentName || row.documentId || ''}`}
          hint="解除后该主题不再检索它"
          variant="ghost"
          icon={<Unlink size={13} aria-hidden="true" />}
          onClick={() => setPending(row)}
        />
      ),
    },
  ];

  return (
    <>
      <DataTable
        caption="主题下已绑定的文档及其关联分数"
        columns={columns}
        rows={rows}
        rowKey={(row, index) => `${row.docId ?? row.documentId ?? 'doc'}-${index}`}
        loading={loading}
        error={error}
        onRetry={onRetry}
        dense
        emptyTitle="这个主题还没有绑定文档"
        emptyDescription="绑上相关文档后，自动问答才会在这个主题下检索到内容。"
        emptyAction={
          <Button size="sm" onClick={onAdd}>
            添加关联
          </Button>
        }
      />

      <ConfirmDialog
        open={pending !== null}
        title="解除这条关联？"
        description={pending ? `主题将不再检索「${pending.documentName || pending.documentId}」。之后可以重新绑定。` : ''}
        confirmLabel="解除"
        danger
        onConfirm={confirmRemove}
        onCancel={() => setPending(null)}
      />
    </>
  );
};
