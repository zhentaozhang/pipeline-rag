import React, { useMemo, useState } from 'react';
import { Layers, RefreshCw, Search } from 'lucide-react';
import { manageApi } from '../../../lib/api';
import { formatCount } from '../../../lib/manageFormat';
import { useAsyncData } from '../../../lib/useAsyncData';
import { useDebouncedValue } from '../useDebouncedValue';
import { Alert } from '../../ui/Alert';
import { Button } from '../../ui/Button';
import { DataTable, TablePagination, type DataTableColumn } from '../../ui/DataTable';
import { EmptyState } from '../../ui/EmptyState';
import { Input } from '../../ui/Field';
import { AdminPanel } from '../AdminPanel';
import { loadFailure } from '../adminFormat';

const PAGE_SIZE = 50;

interface ChunkRecord {
  chunkId?: string | number;
  chunkNo?: string | number;
  parentBlockNo?: string | number;
  sectionPath?: string;
  chunkText?: string;
  charCount?: number;
  tokenCount?: number;
  createTime?: string;
}

interface ChunkEditorProps {
  documentId: string;
  /** 只有索引构建成功后分片表才有数据，没建好时给引导而不是空表 */
  indexReady: boolean;
  onBuildIndex?: () => void;
}

/** 分片验证：按页查看切块结果，支持在当前页内按关键词过滤 */
export const ChunkEditor: React.FC<ChunkEditorProps> = ({ documentId, indexReady, onBuildIndex }) => {
  const [page, setPage] = useState(1);
  const [keyword, setKeyword] = useState('');
  const debouncedKeyword = useDebouncedValue(keyword, 250);

  const { data, loading, error, refetch } = useAsyncData(
    () => manageApi.queryDocumentChunks({ documentId, pageNo: String(page), pageSize: String(PAGE_SIZE) }),
    [documentId, page, indexReady]
  );

  const records = useMemo(() => (data?.records ?? []) as ChunkRecord[], [data]);
  const total = Number(data?.total ?? 0);

  const filtered = useMemo(() => {
    const needle = debouncedKeyword.trim().toLowerCase();
    if (!needle) return records;
    return records.filter((item) =>
      [item.sectionPath, item.chunkText].some((value) => String(value ?? '').toLowerCase().includes(needle))
    );
  }, [records, debouncedKeyword]);

  if (!indexReady) {
    return (
      <AdminPanel title="切块验证">
        <EmptyState
          icon={<Layers size={22} aria-hidden="true" />}
          title="索引还没构建完成"
          description="分片表在索引构建成功后才会生成。可以先在「构建」分区触发构建，进度完成后回到这里查看切块效果。"
          action={
            onBuildIndex ? (
              <Button size="sm" onClick={onBuildIndex}>
                去构建索引
              </Button>
            ) : null
          }
        />
      </AdminPanel>
    );
  }

  const columns: DataTableColumn<ChunkRecord>[] = [
    {
      key: 'chunkNo',
      header: '#',
      align: 'right',
      width: '4rem',
      render: (item) => (
        <span className="font-mono text-xs tabular-nums text-muted-foreground">
          {String(item.chunkNo ?? '—')}
        </span>
      ),
    },
    {
      key: 'sectionPath',
      header: '章节路径',
      width: '14rem',
      render: (item) => (
        <span className="line-clamp-2 text-xs text-muted-foreground" title={item.sectionPath ?? ''}>
          {item.sectionPath || '—'}
        </span>
      ),
    },
    {
      key: 'chunkText',
      header: '分片内容',
      render: (item) => (
        <p className="max-w-[520px] text-xs leading-relaxed text-foreground" title={item.chunkText ?? ''}>
          {item.chunkText || '（空分片）'}
        </p>
      ),
    },
    {
      key: 'charCount',
      header: '字数',
      align: 'right',
      width: '5.5rem',
      render: (item) => <span className="font-mono tabular-nums">{formatCount(item.charCount ?? 0)}</span>,
    },
    {
      key: 'tokenCount',
      header: 'Token',
      align: 'right',
      width: '5.5rem',
      render: (item) => <span className="font-mono tabular-nums">{formatCount(item.tokenCount ?? 0)}</span>,
    },
  ];

  return (
    <AdminPanel
      title="切块验证"
      description={`共 ${formatCount(total)} 个分片，每页 ${PAGE_SIZE} 条，可在当前页按关键词过滤`}
      actions={
        <Button size="sm" variant="outline" onClick={refetch} loading={loading}>
          <RefreshCw size={13} aria-hidden="true" />
          刷新
        </Button>
      }
    >
      {error ? (
        <Alert variant="destructive" title="加载分片失败" action={<Button size="sm" variant="outline" onClick={refetch}>重试</Button>}>
          {loadFailure(error, '文档分片')}
        </Alert>
      ) : (
        <div className="flex flex-col gap-3">
          <div className="relative max-w-sm">
            <Search
              size={14}
              aria-hidden="true"
              className="pointer-events-none absolute inset-y-0 left-2.5 my-auto text-muted-foreground"
            />
            <Input
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              placeholder="在本页分片里搜索章节或正文"
              aria-label="按关键词过滤当前页分片"
              className="pl-8"
            />
          </div>
          <DataTable
            columns={columns}
            rows={filtered}
            rowKey={(row) => String(row.chunkId ?? row.chunkNo)}
            caption="文档分片列表：分片序号、章节路径、正文内容与字数/Token 统计"
            loading={loading}
            error={error}
            onRetry={refetch}
            emptyTitle={debouncedKeyword ? '本页没有匹配的分片' : '这一页没有分片'}
            emptyDescription={
              debouncedKeyword
                ? '换个关键词，或清空搜索框后翻页查看其他分片。'
                : '索引可能还在构建中。等构建完成后再刷新本页。'
            }
            footer={<TablePagination page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />}
          />
        </div>
      )}
    </AdminPanel>
  );
};
