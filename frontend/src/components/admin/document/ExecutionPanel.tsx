import React, { useState } from 'react';
import { Hammer, RefreshCw } from 'lucide-react';
import { manageApi } from '../../../lib/api';
import { formatDateTime, hasCode, normalizeCode } from '../../../lib/manageFormat';
import type { ManageDocument } from '../../../types/api';
import { useAsyncData } from '../../../lib/useAsyncData';
import { toast } from '../../../lib/toast';
import { Alert } from '../../ui/Alert';
import { Button } from '../../ui/Button';
import { DataTable, type DataTableColumn } from '../../ui/DataTable';
import { AdminPanel } from '../AdminPanel';
import { actionFailure } from '../adminFormat';

interface TaskLog {
  id?: string | number;
  stageTypeName?: string;
  eventTypeName?: string;
  createTime?: string;
  content?: string;
  detailJson?: string;
}

interface ExecutionPanelProps {
  documentId: string;
  documentDetail: ManageDocument | null;
  onRefresh?: () => void;
}

/** 构建执行：触发索引构建 + 查看任务日志 */
export const ExecutionPanel: React.FC<ExecutionPanelProps> = ({ documentId, documentDetail, onRefresh }) => {
  const [building, setBuilding] = useState(false);
  const [tick, setTick] = useState(0);

  const strategyReady = hasCode(documentDetail?.strategyStatus, 3);
  const indexCode = normalizeCode(documentDetail?.indexStatus);
  const indexStarted = ['1', '2', '3'].includes(indexCode);
  const indexDone = indexCode === '3';

  const { data, loading, error, refetch } = useAsyncData(
    () => manageApi.queryTaskLogs({ documentId, pageNo: '1', pageSize: '50' }),
    [documentId, tick]
  );
  const logs = (data?.logs ?? []) as TaskLog[];

  const build = async () => {
    if (!strategyReady) {
      toast({
        title: '还不能构建索引',
        description: '请先在「策略」分区确认切块策略，确认后才能触发构建。',
        variant: 'error',
      });
      return;
    }
    setBuilding(true);
    try {
      await manageApi.buildIndex({ documentId });
      toast({ title: '构建任务已提交', description: '索引构建在后台执行，可点「刷新日志」查看进度。', variant: 'success' });
      setTick((value) => value + 1);
      onRefresh?.();
    } catch (buildError) {
      toast({
        title: '触发构建失败',
        description: actionFailure(buildError, '触发索引构建', '请确认策略已确认、后端服务在线，然后重试。'),
        variant: 'error',
      });
    } finally {
      setBuilding(false);
    }
  };

  const columns: DataTableColumn<TaskLog>[] = [
    {
      key: 'stage',
      header: '阶段',
      width: '8rem',
      render: (item) => (
        <span className="rounded-md bg-secondary px-2 py-0.5 text-2xs font-medium text-secondary-foreground">
          {item.stageTypeName || '—'}
        </span>
      ),
    },
    {
      key: 'event',
      header: '事件',
      width: '8rem',
      render: (item) => <span className="text-xs text-foreground">{item.eventTypeName || '—'}</span>,
    },
    {
      key: 'time',
      header: '时间',
      width: '9rem',
      render: (item) => (
        <span className="font-mono text-xs tabular-nums text-muted-foreground">{formatDateTime(item.createTime)}</span>
      ),
    },
    {
      key: 'content',
      header: '内容',
      render: (item) => (
        <div className="max-w-[560px]">
          <p className="text-xs leading-relaxed text-foreground">{item.content || '—'}</p>
          {item.detailJson ? (
            <details className="mt-1">
              <summary className="cursor-pointer text-2xs text-primary">查看原始明细</summary>
              <pre className="mt-1 max-h-48 overflow-auto rounded-md bg-secondary p-2 text-2xs leading-relaxed text-muted-foreground">
                {item.detailJson}
              </pre>
            </details>
          ) : null}
        </div>
      ),
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      <AdminPanel
        title="索引构建"
        description="策略确认后触发，构建期间可以继续停留本页查看日志"
        actions={
          <Button size="sm" onClick={build} loading={building} disabled={!strategyReady}>
            <Hammer size={13} aria-hidden="true" />
            {indexDone ? '重新构建' : '构建索引'}
          </Button>
        }
      >
        {!strategyReady ? (
          <Alert variant="warning" title="策略尚未确认">
            请先在「策略」分区确认切块策略。没有确认的策略，构建出来的分片无法与问答链路对齐。
          </Alert>
        ) : indexDone ? (
          <Alert variant="success" title="索引已可用">
            当前文档的索引构建已完成，可以到「验证」分区检查分片质量。
          </Alert>
        ) : indexStarted ? (
          <Alert variant="info" title="构建进行中">
            构建任务已提交。完成后解析与索引状态会自动更新，可点下方「刷新日志」查看最新进度。
          </Alert>
        ) : (
          <p className="text-sm text-muted-foreground">还没有开始构建。点击右上角「构建索引」提交任务。</p>
        )}
      </AdminPanel>

      <AdminPanel
        title="任务日志"
        description="最近 50 条任务事件，按时间倒序"
        actions={
          <Button
            size="sm"
            variant="outline"
            onClick={() => setTick((value) => value + 1)}
            loading={loading}
          >
            <RefreshCw size={13} aria-hidden="true" />
            刷新日志
          </Button>
        }
      >
        <DataTable
          columns={columns}
          rows={logs}
          rowKey={(row) => String(row.id ?? `${row.createTime}-${row.eventTypeName}`)}
          caption="文档构建任务日志：阶段、事件、时间与执行内容"
          loading={loading}
          error={error}
          onRetry={refetch}
          emptyTitle="还没有任务日志"
          emptyDescription="触发一次索引构建后，这里会记录解析、切块、向量化的每一步。"
          skeletonRows={4}
        />
      </AdminPanel>
    </div>
  );
};
