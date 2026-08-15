import React, { useState } from 'react';
import { manageApi, APIError } from '../../lib/api';
import type { ManageDocument } from '../../types/api';

interface TaskLogItem {
  id?: string | number;
  stageTypeName?: string;
  eventTypeName?: string;
  createTime?: string;
  content?: string;
  detailJson?: string;
  [key: string]: unknown;
}

interface AdminDocumentExecutionViewProps {
  documentId: string;
  documentDetail: ManageDocument | null;
  showNotice: (msg: string, type?: 'info' | 'success' | 'danger') => void;
  onRefresh: () => void;
}

export const AdminDocumentExecutionView: React.FC<AdminDocumentExecutionViewProps> = ({ 
  documentId, 
  documentDetail, 
  showNotice,
  onRefresh
}) => {
  const [building, setBuilding] = useState(false);
  const [logs, setLogs] = useState<TaskLogItem[]>([]);
  const [loadingLogs, setLoadingLogs] = useState(false);

  const hasStrategyConfirmed = documentDetail?.strategyStatus === 3;
  const hasIndexStarted =
    documentDetail?.indexStatus != null && [1, 2, 3].includes(documentDetail.indexStatus);
  const hasIndexSuccess = documentDetail?.indexStatus === 3;

  const submitBuildIndex = async () => {
    setBuilding(true);
    try {
      await manageApi.buildIndex({ documentId });
      showNotice('已发起构建索引任务，请等待任务完成', 'success');
      onRefresh();
    } catch (error) {
      showNotice(error instanceof APIError ? error.message : '发起构建失败', 'danger');
    } finally {
      setBuilding(false);
    }
  };

  const loadTaskLogs = async () => {
    setLoadingLogs(true);
    try {
      const data = await manageApi.queryTaskLogs({
        documentId,
        pageNo: '1',
        pageSize: '50'
      });
      setLogs((data?.logs || []) as TaskLogItem[]);
    } catch (error) {
      console.error('加载任务日志失败', error);
    } finally {
      setLoadingLogs(false);
    }
  };

  return (
    <div className="p-6 md:p-8">
      <div className="mb-8">
        <h3 className="text-lg font-bold text-foreground tracking-tight">构建索引</h3>
        <p className="text-sm text-muted-foreground mt-1">先确认策略方案，再执行构建索引，并在下方查看执行轨迹。</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
        <div className="bg-secondary/30 rounded-xl border border-border/50 p-6 flex flex-col items-center justify-center text-center transition-all hover:border-border">
          <div className={`w-12 h-12 rounded-full flex items-center justify-center mb-4 transition-colors ${
            hasStrategyConfirmed ? 'bg-emerald-500/10 text-emerald-500' : 'bg-secondary text-muted-foreground'
          }`}>
            <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h4 className="font-bold text-foreground mb-2">策略确认</h4>
          <p className="text-sm text-muted-foreground mb-4 h-10">
            {hasStrategyConfirmed ? '当前方案已确认，可以进行构建。' : '还未完成最终确认，请在"配置策略"中保存。'}
          </p>
        </div>

        <div className="bg-secondary/30 rounded-xl border border-border/50 p-6 flex flex-col items-center justify-center text-center transition-all hover:border-border">
          <div className={`w-12 h-12 rounded-full flex items-center justify-center mb-4 transition-colors ${
            hasIndexSuccess ? 'bg-emerald-500/10 text-emerald-500' : hasIndexStarted ? 'bg-primary/10 text-primary' : 'bg-secondary text-muted-foreground'
          }`}>
            <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </div>
          <h4 className="font-bold text-foreground mb-2">构建执行</h4>
          <p className="text-sm text-muted-foreground mb-4 h-10">
            {hasIndexSuccess ? '构建已完成，可前往验证切块。' : hasIndexStarted ? '系统正在执行构建，请留意任务状态。' : '策略确认完成后即可发起构建。'}
          </p>
          <button
            onClick={submitBuildIndex}
            disabled={!hasStrategyConfirmed || building || hasIndexStarted}
            className="px-6 py-2 bg-primary text-primary-foreground rounded-md text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {building ? '发起中...' : hasIndexStarted ? '已开始构建' : '发起构建'}
          </button>
        </div>
      </div>

      <div className="bg-background border border-border/50 rounded-xl overflow-hidden">
        <div className="p-4 border-b border-border/50 flex justify-between items-center bg-secondary/20">
          <h4 className="font-bold text-foreground">任务执行日志</h4>
          <button onClick={loadTaskLogs} disabled={loadingLogs} className="text-sm font-medium text-primary hover:text-primary/80 transition-colors">
            {loadingLogs ? '刷新中...' : '刷新日志'}
          </button>
        </div>
        <div className="p-6">
          {logs.length === 0 ? (
            <div className="text-center text-muted-foreground py-8">
              暂无日志记录，点击刷新或等待任务执行。
            </div>
          ) : (
            <div className="space-y-6">
              {logs.map((log, idx) => (
                <div key={log.id || idx} className="flex gap-4">
                  <div className="flex flex-col items-center">
                    <div className="w-2.5 h-2.5 rounded-full bg-primary mt-1.5 shadow-sm shadow-primary/20"></div>
                    {idx < logs.length - 1 && <div className="w-px h-full bg-border/50 mt-2"></div>}
                  </div>
                  <div className="flex-1 pb-4">
                    <div className="flex justify-between items-start mb-1">
                      <strong className="text-sm font-medium text-foreground">{log.stageTypeName} · {log.eventTypeName}</strong>
                      <span className="text-xs font-mono text-muted-foreground opacity-80">{log.createTime}</span>
                    </div>
                    <p className="text-sm text-muted-foreground mt-1">{log.content}</p>
                    {log.detailJson && (
                      <pre className="mt-3 p-4 bg-secondary/10 rounded-lg text-xs font-mono text-muted-foreground overflow-x-auto border border-border/30">
                        {log.detailJson}
                      </pre>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
