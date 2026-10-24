import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, FileText, RefreshCw } from 'lucide-react';
import { manageApi } from '../../lib/api';
import { formatDateTime, formatFileSize, normalizeCode } from '../../lib/manageFormat';
import { useAsyncData } from '../../lib/useAsyncData';
import { useDebouncedValue } from '../../components/admin/useDebouncedValue';
import type { DocumentPageResponse, ManageDocument } from '../../types/api';
import { Alert } from '../../components/ui/Alert';
import { Button } from '../../components/ui/Button';
import { EmptyState } from '../../components/ui/EmptyState';
import { Input } from '../../components/ui/Field';
import { Skeleton } from '../../components/ui/Skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../components/ui/Tabs';
import { AdminPageHeader } from '../../components/admin/AdminPageHeader';
import { AdminPanel } from '../../components/admin/AdminPanel';
import { AdminStatusBadge } from '../../components/admin/AdminStatusBadge';
import { StrategyPanel } from '../../components/admin/document/StrategyPanel';
import { ExecutionPanel } from '../../components/admin/document/ExecutionPanel';
import { ChunkEditor } from '../../components/admin/document/ChunkEditor';
import { loadFailure } from '../../components/admin/adminFormat';

/** 文档中心：左侧选文档、右侧连续处理策略/构建/验证，适合一次性把多篇文档跑通 */
export const AdminDocumentCenterView: React.FC = () => {
  const navigate = useNavigate();
  const [keyword, setKeyword] = useState('');
  const debouncedKeyword = useDebouncedValue(keyword, 350);
  const [selectedId, setSelectedId] = useState('');
  const [tab, setTab] = useState('strategy');

  const { data, loading, error, refetch } = useAsyncData<DocumentPageResponse>(
    () => manageApi.queryDocumentPage({ pageNo: 1, pageSize: 50, keyword: debouncedKeyword.trim() }),
    [debouncedKeyword]
  );

  const records = data?.records ?? [];
  const selected: ManageDocument | null =
    records.find((item) => normalizeCode(item.documentId) === normalizeCode(selectedId)) ?? null;
  const activeId = selected ? normalizeCode(selected.documentId) : '';

  const refreshDetail = () => refetch();

  return (
    <div className="flex flex-col gap-6">
      <AdminPageHeader
        eyebrow="接入文档"
        title="文档中心"
        description="左侧选一份文档，右侧依次确认策略、触发构建、抽查分片。全部在一屏内完成，不用来回跳页。"
        actions={
          <>
            <Button size="sm" variant="outline" onClick={() => navigate('/admin/documents')}>
              <ArrowLeft size={13} aria-hidden="true" />
              返回列表
            </Button>
            <Button size="sm" variant="outline" onClick={() => refetch()} loading={loading}>
              <RefreshCw size={13} aria-hidden="true" />
              刷新
            </Button>
          </>
        }
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[320px_1fr]">
        <AdminPanel title="文档" description={`最近 50 篇，共 ${Number(data?.total ?? 0)} 篇`} bodyClassName="p-3">
          <Input
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            placeholder="按名称或文件名筛选"
            aria-label="筛选文档"
          />
          <div className="mt-3 flex max-h-[560px] flex-col gap-1.5 overflow-y-auto pr-1">
            {loading && records.length === 0 ? <Skeleton lines={6} /> : null}
            {error ? (
              <p className="p-2 text-xs text-destructive">{loadFailure(error, '文档列表')}</p>
            ) : null}
            {!loading && !error && records.length === 0 ? (
              <p className="p-2 text-xs text-muted-foreground">没有匹配的文档。清空筛选或先去上传一份资料。</p>
            ) : null}
            {records.map((item) => {
              const id = normalizeCode(item.documentId);
              const active = id === activeId;
              return (
                <button
                  key={id}
                  type="button"
                  aria-current={active ? 'true' : undefined}
                  onClick={() => setSelectedId(id)}
                  className={`flex flex-col gap-1 rounded-lg border px-3 py-2 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                    active ? 'border-primary bg-primary/5' : 'border-transparent hover:bg-secondary'
                  }`}
                >
                  <span className="flex items-center gap-1.5">
                    <FileText size={13} aria-hidden="true" className="shrink-0 text-muted-foreground" />
                    <span className="min-w-0 flex-1 truncate text-xs font-medium text-foreground">
                      {item.documentName || item.originalFileName}
                    </span>
                  </span>
                  <span className="text-2xs text-muted-foreground">
                    {item.fileTypeName || '—'} · {formatFileSize(item.fileSize)} · {formatDateTime(item.editTime)}
                  </span>
                  <span className="flex gap-1">
                    <AdminStatusBadge label={item.parseStatusName} code={item.parseStatus} type="parse" />
                    <AdminStatusBadge label={item.indexStatusName} code={item.indexStatus} type="index" />
                  </span>
                </button>
              );
            })}
          </div>
        </AdminPanel>

        {selected ? (
          <div className="flex flex-col gap-4">
            <Alert variant="info" title={selected.documentName || '已选中文档'}>
              当前处理：{selected.originalFileName || '—'}。任何一步成功后左侧状态会自动刷新。
            </Alert>
            <Tabs value={tab} onValueChange={setTab}>
              <TabsList>
                <TabsTrigger value="strategy" step="01" hint="确认切块策略">
                  策略配置
                </TabsTrigger>
                <TabsTrigger value="execution" step="02" hint="触发索引构建">
                  构建执行
                </TabsTrigger>
                <TabsTrigger value="chunk" step="03" hint="抽查分片">
                  切块验证
                </TabsTrigger>
              </TabsList>
              <TabsContent value="strategy">
                <StrategyPanel documentId={String(selected.documentId)} onConfirmed={refreshDetail} />
              </TabsContent>
              <TabsContent value="execution">
                <ExecutionPanel
                  documentId={String(selected.documentId)}
                  documentDetail={selected}
                  onRefresh={refreshDetail}
                />
              </TabsContent>
              <TabsContent value="chunk">
                <ChunkEditor
                  documentId={String(selected.documentId)}
                  indexReady={normalizeCode(selected.indexStatus) === '3'}
                />
              </TabsContent>
            </Tabs>
          </div>
        ) : (
          <AdminPanel>
            <EmptyState
              icon={<FileText size={22} aria-hidden="true" />}
              title="还没有选中文档"
              description="请在左侧列表中选择一份文档。选中后可以在这里确认策略、触发构建并抽查分片。"
              action={
                <Button size="sm" variant="secondary" onClick={() => navigate('/admin/documents')}>
                  去上传文档
                </Button>
              }
            />
          </AdminPanel>
        )}
      </div>
    </div>
  );
};
