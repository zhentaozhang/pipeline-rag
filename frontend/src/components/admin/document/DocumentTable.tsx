import React from 'react';
import { Link2, Trash2, Upload } from 'lucide-react';
import type { ManageDocument } from '../../../types/api';
import { formatDateTime, formatFileSize, hasCode } from '../../../lib/manageFormat';
import { Button } from '../../ui/Button';
import { DataTable, TablePagination, type DataTableColumn } from '../../ui/DataTable';
import { AdminStatusBadge } from '../AdminStatusBadge';

interface DocumentTableProps {
  rows: ManageDocument[];
  total: number;
  page: number;
  pageSize: number;
  loading: boolean;
  error: string;
  deletingId: string;
  onRetry: () => void;
  onPageChange: (page: number) => void;
  onOpen: (documentId: string | number) => void;
  onDelete: (document: ManageDocument) => void;
  onUpload: () => void;
}

/** 文档还有进行中的任务时不允许删除，否则会把正在读的存储文件删掉 */
function hasRunningTask(item: ManageDocument): boolean {
  return (
    hasCode(item?.latestTaskStatus, 1) ||
    hasCode(item?.latestTaskStatus, 2) ||
    hasCode(item?.parseStatus, 2) ||
    hasCode(item?.indexStatus, 2)
  );
}

function deleteHint(item: ManageDocument, deletingId: string): string {
  if (hasRunningTask(item)) return '请等待当前任务完成后再删除';
  if (deletingId) return '当前有文档正在删除';
  return '删除文档以及关联的索引、存储文件';
}

export const DocumentTable: React.FC<DocumentTableProps> = ({
  rows,
  total,
  page,
  pageSize,
  loading,
  error,
  deletingId,
  onRetry,
  onPageChange,
  onOpen,
  onDelete,
  onUpload,
}) => {
  const columns: DataTableColumn<ManageDocument>[] = [
    {
      key: 'name',
      header: '文档',
      render: (item) => (
        <div className="flex min-w-0 flex-col">
          <button
            type="button"
            onClick={() => onOpen(item.documentId)}
            className="max-w-[280px] truncate text-left text-fine font-medium text-foreground hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {item.documentName || item.originalFileName || item.documentId}
          </button>
          <span className="mt-0.5 max-w-[280px] truncate text-2xs text-muted-foreground">
            {item.originalFileName}
          </span>
        </div>
      ),
    },
    {
      key: 'type',
      header: '类型',
      width: '5rem',
      render: (item) => (
        <span className="rounded-md bg-secondary px-2 py-0.5 text-2xs font-medium uppercase text-secondary-foreground">
          {item.fileTypeName || '—'}
        </span>
      ),
    },
    {
      key: 'size',
      header: '大小',
      align: 'right',
      width: '6rem',
      render: (item) => <span className="font-mono tabular-nums">{formatFileSize(item.fileSize)}</span>,
    },
    {
      key: 'editTime',
      header: '更新时间',
      width: '9rem',
      render: (item) => <span className="font-mono text-xs tabular-nums">{formatDateTime(item.editTime)}</span>,
    },
    {
      key: 'parse',
      header: '解析',
      width: '6.5rem',
      render: (item) => <AdminStatusBadge label={item.parseStatusName} code={item.parseStatus} type="parse" />,
    },
    {
      key: 'strategy',
      header: '策略',
      width: '6.5rem',
      render: (item) => (
        <AdminStatusBadge label={item.strategyStatusName} code={item.strategyStatus} type="strategy" />
      ),
    },
    {
      key: 'index',
      header: '索引',
      width: '6.5rem',
      render: (item) => <AdminStatusBadge label={item.indexStatusName} code={item.indexStatus} type="index" />,
    },
    {
      key: 'actions',
      header: '操作',
      align: 'right',
      width: '10rem',
      render: (item) => {
        const deleting = String(deletingId) === String(item.documentId ?? '');
        const disabled = !item.documentId || deleting || loading || hasRunningTask(item) || Boolean(deletingId);
        return (
          <div className="flex items-center justify-end gap-2">
            <Button variant="outline" size="sm" onClick={() => onOpen(item.documentId)}>
              <Link2 size={13} aria-hidden="true" />
              详情
            </Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => onDelete(item)}
              disabled={disabled}
              title={deleteHint(item, deletingId)}
              loading={deleting}
            >
              <Trash2 size={13} aria-hidden="true" />
              删除
            </Button>
          </div>
        );
      },
    },
  ];

  return (
    <DataTable
      columns={columns}
      rows={rows}
      rowKey={(row) => String(row.documentId)}
      caption="文档列表：文档名称、类型、大小、更新时间，以及解析、策略、索引三段状态"
      loading={loading}
      error={error}
      onRetry={onRetry}
      emptyTitle="这轮筛选没有文档"
      emptyDescription="先上传一份资料，系统会自动完成解析并给出推荐切块策略；也可能只是搜索词把结果筛空了。"
      emptyAction={
        <Button size="sm" onClick={onUpload}>
          <Upload size={14} aria-hidden="true" />
          上传文档
        </Button>
      }
      footer={<TablePagination page={page} pageSize={pageSize} total={total} onPageChange={onPageChange} />}
    />
  );
};
