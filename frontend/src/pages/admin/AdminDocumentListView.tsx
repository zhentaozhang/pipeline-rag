import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { RefreshCw, Search } from 'lucide-react';
import { manageApi } from '../../lib/api';
import { normalizeCode } from '../../lib/manageFormat';
import { useAsyncData } from '../../lib/useAsyncData';
import { useUrlFilters } from '../../lib/useUrlFilters';
import { toast } from '../../lib/toast';
import type { DocumentPageResponse, ManageDocument } from '../../types/api';
import { Button } from '../../components/ui/Button';
import { ConfirmDialog } from '../../components/ui/ConfirmDialog';
import { FilterBar, FilterSearch } from '../../components/ui/FilterBar';
import { AdminPageHeader } from '../../components/admin/AdminPageHeader';
import { AdminStatGrid } from '../../components/admin/AdminStatGrid';
import { UploadPanel } from '../../components/admin/document/UploadPanel';
import { DocumentTable } from '../../components/admin/document/DocumentTable';
import { actionFailure } from '../../components/admin/adminFormat';
import { useDebouncedValue } from '../../components/admin/useDebouncedValue';

const PAGE_SIZE = 12;
/** defaults 必须是稳定引用，否则 useUrlFilters 的 memo 每次都会重算 */
const DEFAULT_FILTERS = { q: '', page: '1' };

/** 文档接入：上传 + 列表浏览，详情与策略/构建/验证在文档详情页完成 */
export const AdminDocumentListView: React.FC = () => {
  const navigate = useNavigate();
  const [filters, patchFilters] = useUrlFilters(DEFAULT_FILTERS);
  const [pendingDelete, setPendingDelete] = useState<ManageDocument | null>(null);
  const [deletingId, setDeletingId] = useState('');

  const page = Math.max(1, Number(filters.page) || 1);
  const keyword = useDebouncedValue(filters.q, 350);

  const { data, loading, error, refetch } = useAsyncData<DocumentPageResponse>(
    () => manageApi.queryDocumentPage({ pageNo: page, pageSize: PAGE_SIZE, keyword: keyword.trim() }),
    [page, keyword]
  );

  const records = data?.records ?? [];
  const total = Number(data?.total ?? 0);
  const summary = {
    current: records.length,
    parsed: records.filter((item) => normalizeCode(item.parseStatus) === '3').length,
    confirmed: records.filter((item) => normalizeCode(item.strategyStatus) === '3').length,
    indexed: records.filter((item) => normalizeCode(item.indexStatus) === '3').length,
  };

  const scrollToList = () => {
    document.getElementById('document-table')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  /** 空态里的「上传文档」按钮：滚回上传面板并把焦点交给文件输入，避免用户自己找 */
  const focusUpload = () => {
    const panel = document.getElementById('upload-panel');
    panel?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    panel?.querySelector<HTMLInputElement>('input[type="file"]')?.focus();
  };

  const handleUploaded = (result: Record<string, unknown>) => {
    refetch();
    const documentId = String(result?.documentId ?? '');
    if (documentId) {
      navigate(`/admin/documents/${documentId}`);
      return;
    }
    scrollToList();
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    const documentId = String(pendingDelete.documentId ?? '');
    setDeletingId(documentId);
    try {
      await manageApi.deleteDocument({ documentId });
      toast({
        title: '已删除文档',
        description: 'Mysql 元数据、向量索引与对象存储文件已一并清理。',
        variant: 'success',
      });
      setPendingDelete(null);
      if (records.length === 1 && page > 1) {
        patchFilters({ page: String(page - 1) });
      } else {
        refetch();
      }
    } catch (deleteError) {
      toast({
        title: '删除文档失败',
        description: actionFailure(deleteError, '删除文档', '请确认没有进行中的任务，然后重试。'),
        variant: 'error',
      });
    } finally {
      setDeletingId('');
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <AdminPageHeader
        eyebrow="接入文档"
        title="文档接入与切块"
        description="上传资料后系统会自动解析并推荐切块策略。列表用于筛选与删除，点开任意文档进入详情页做策略确认、索引构建与分片验证。"
        actions={
          <>
            <Button size="sm" variant="outline" onClick={() => refetch()} loading={loading}>
              <RefreshCw size={13} aria-hidden="true" />
              刷新
            </Button>
            <Button size="sm" variant="secondary" onClick={() => navigate('/admin/documents/center')}>
              文档中心
            </Button>
          </>
        }
      />

      <UploadPanel onUploaded={handleUploaded} />

      <section id="document-table" className="flex flex-col gap-4">
        <AdminStatGrid
          stats={[
            { label: '本页文档', value: summary.current, hint: `共 ${total} 篇，当前第 ${page} 页` },
            { label: '本页解析完成', value: summary.parsed, tone: summary.parsed ? 'success' : 'default' },
            { label: '本页策略已确认', value: summary.confirmed, tone: summary.confirmed ? 'success' : 'default' },
            { label: '本页索引可用', value: summary.indexed, tone: summary.indexed ? 'primary' : 'default' },
          ]}
        />

        <FilterBar
          actions={
            <Button
              size="sm"
              variant="ghost"
              onClick={() => patchFilters({ q: '', page: '1' })}
              disabled={!filters.q && page === 1}
            >
              清空筛选
            </Button>
          }
        >
          <FilterSearch
            label="搜索文档"
            value={filters.q}
            onChange={(value) => patchFilters({ q: value, page: '1' })}
            placeholder="按名称、文件名或标签搜索"
          />
          <p className="flex items-center gap-1.5 pb-1 text-2xs text-muted-foreground">
            <Search size={12} aria-hidden="true" />
            筛选条件会写进 URL，刷新和后退都不会丢
          </p>
        </FilterBar>

        <DocumentTable
          rows={records}
          total={total}
          page={page}
          pageSize={PAGE_SIZE}
          loading={loading}
          error={error}
          deletingId={deletingId}
          onRetry={() => refetch()}
          onPageChange={(next) => patchFilters({ page: String(next) })}
          onOpen={(documentId) => navigate(`/admin/documents/${documentId}`)}
          onDelete={(item) => setPendingDelete(item)}
          onUpload={focusUpload}
        />

      </section>

      <ConfirmDialog
        open={Boolean(pendingDelete)}
        title="确认删除这份文档？"
        description={
          pendingDelete
            ? `${pendingDelete.documentName || pendingDelete.originalFileName} 的 Mysql 元数据、向量索引和 MinIO 原始文件都会被删除，且无法恢复。`
            : ''
        }
        confirmLabel="删除"
        danger
        onConfirm={confirmDelete}
        onCancel={() => setPendingDelete(null)}
      />
    </div>
  );
};
