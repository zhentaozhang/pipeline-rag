import React from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, RefreshCw } from 'lucide-react';
import { manageApi } from '../../lib/api';
import { formatDateTime, formatFileSize, normalizeCode } from '../../lib/manageFormat';
import { useAsyncData } from '../../lib/useAsyncData';
import { useUrlFilters } from '../../lib/useUrlFilters';
import type { ManageDocument } from '../../types/api';
import { Alert } from '../../components/ui/Alert';
import { Button } from '../../components/ui/Button';
import { EmptyState } from '../../components/ui/EmptyState';
import { Skeleton } from '../../components/ui/Skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../components/ui/Tabs';
import { AdminPageHeader } from '../../components/admin/AdminPageHeader';
import { AdminPanel } from '../../components/admin/AdminPanel';
import { AdminStatusBadge } from '../../components/admin/AdminStatusBadge';
import { StrategyPanel } from '../../components/admin/document/StrategyPanel';
import { ExecutionPanel } from '../../components/admin/document/ExecutionPanel';
import { ChunkEditor } from '../../components/admin/document/ChunkEditor';
import { loadFailure } from '../../components/admin/adminFormat';

const DEFAULT_FILTERS = { tab: 'overview' };
const TABS = [
  { value: 'overview', label: '概览', step: '01', hint: '文档元信息与三段状态' },
  { value: 'strategy', label: '策略', step: '02', hint: '确认父子块流水线' },
  { value: 'execution', label: '构建', step: '03', hint: '触发索引并看任务日志' },
  { value: 'chunk', label: '验证', step: '04', hint: '抽查切块结果' },
];

const MetaRow: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <div className="flex flex-col gap-1 border-b border-border py-2.5 last:border-b-0 sm:flex-row sm:items-baseline sm:gap-4">
    <dt className="w-24 shrink-0 text-xs text-muted-foreground">{label}</dt>
    <dd className="min-w-0 break-words text-sm text-foreground">{children}</dd>
  </div>
);

/** 文档详情：把策略确认、索引构建、切块验证按步骤分到四个分区，避免一屏堆满 */
export const AdminDocumentDetailView: React.FC = () => {
  const { documentId = '' } = useParams();
  const navigate = useNavigate();
  const [filters, patchFilters] = useUrlFilters(DEFAULT_FILTERS);

  const { data: detail, loading, error, refetch } = useAsyncData<ManageDocument>(
    () => manageApi.queryDocumentDetail(documentId),
    [documentId]
  );

  const tab = TABS.some((item) => item.value === filters.tab) ? filters.tab : 'overview';
  const parseDone = normalizeCode(detail?.parseStatus) === '3';
  const indexReady = normalizeCode(detail?.indexStatus) === '3';

  if (!documentId) {
    return (
      <EmptyState
        title="没有指定文档"
        description="请回到文档列表，从列表里点开一份文档查看详情。"
        action={
          <Button size="sm" onClick={() => navigate('/admin/documents')}>
            返回文档列表
          </Button>
        }
      />
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <AdminPageHeader
        eyebrow="接入文档"
        title={detail?.documentName || '文档详情'}
        description={detail?.originalFileName ? `原始文件：${detail.originalFileName}` : '正在加载文档信息…'}
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

      {loading && !detail ? (
        <AdminPanel title="文档信息">
          <Skeleton lines={6} />
        </AdminPanel>
      ) : error ? (
        <Alert
          variant="destructive"
          title="加载文档详情失败"
          action={<Button size="sm" variant="outline" onClick={() => refetch()}>重试</Button>}
        >
          {loadFailure(error, '文档详情')}
        </Alert>
      ) : (
        <Tabs value={tab} onValueChange={(value) => patchFilters({ tab: value })}>
          <TabsList>
            {TABS.map((item) => (
              <TabsTrigger key={item.value} value={item.value} step={item.step} hint={item.hint}>
                {item.label}
              </TabsTrigger>
            ))}
          </TabsList>

          <TabsContent value="overview">
            <div className="flex flex-col gap-4">
              <AdminPanel title="三段状态" description="解析 → 策略 → 索引，任一段卡住都看这里">
                <div className="flex flex-wrap gap-2">
                  <AdminStatusBadge label={detail?.parseStatusName} code={detail?.parseStatus} type="parse" />
                  <AdminStatusBadge label={detail?.strategyStatusName} code={detail?.strategyStatus} type="strategy" />
                  <AdminStatusBadge label={detail?.indexStatusName} code={detail?.indexStatus} type="index" />
                </div>
                {detail?.parseErrorMsg ? (
                  <Alert variant="destructive" title="解析失败原因" className="mt-3">
                    {detail.parseErrorMsg}
                  </Alert>
                ) : null}
              </AdminPanel>

              <AdminPanel title="文档元信息">
                <dl className="flex flex-col">
                  <MetaRow label="文档名称">{detail?.documentName || '—'}</MetaRow>
                  <MetaRow label="原始文件">{detail?.originalFileName || '—'}</MetaRow>
                  <MetaRow label="文件类型">{detail?.fileTypeName || '—'}</MetaRow>
                  <MetaRow label="文件大小">{formatFileSize(detail?.fileSize)}</MetaRow>
                  <MetaRow label="知识域">
                    {detail?.knowledgeScopeName || detail?.knowledgeScopeCode || '未归属'}
                  </MetaRow>
                  <MetaRow label="业务分类">{detail?.businessCategory || '—'}</MetaRow>
                  <MetaRow label="文档标签">{detail?.documentTags || '—'}</MetaRow>
                  <MetaRow label="更新时间">{formatDateTime(detail?.editTime)}</MetaRow>
                  <MetaRow label="文档 ID">
                    <span className="font-mono text-xs">{documentId}</span>
                  </MetaRow>
                </dl>
              </AdminPanel>
            </div>
          </TabsContent>

          <TabsContent value="strategy">
            {parseDone ? (
              <StrategyPanel documentId={documentId} onConfirmed={() => refetch()} />
            ) : (
              <Alert variant="info" title="还在等待解析">
                解析完成后才能确认切块策略。如果解析失败，请回到列表重新上传。
              </Alert>
            )}
          </TabsContent>

          <TabsContent value="execution">
            <ExecutionPanel documentId={documentId} documentDetail={detail} onRefresh={() => refetch()} />
          </TabsContent>

          <TabsContent value="chunk">
            <ChunkEditor
              documentId={documentId}
              indexReady={indexReady}
              onBuildIndex={() => patchFilters({ tab: 'execution' })}
            />
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
};
