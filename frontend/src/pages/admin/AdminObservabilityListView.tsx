import React, { useState, useEffect, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { chatApi } from '../../lib/api';
import { Button } from '../../components/ui/Button';
import { Card, CardContent } from '../../components/ui/Card';
import { Badge } from '../../components/ui/Badge';
import {
  formatChatMode,
  formatStatusLabel,
  formatTime,
  normalizeError,
  sessionMessageCount,
  sessionPreview,
  sessionTitle,
  statusTone,
  truncate
} from '../../lib/observabilityHelpers';

export const AdminObservabilityListView: React.FC = () => {
  const [sessions, setSessions] = useState<any[]>([]);
  const [loadingSessions, setLoadingSessions] = useState(false);
  const [pageError, setPageError] = useState('');
  const [keyword, setKeyword] = useState('');
  const [modeFilter, setModeFilter] = useState('ALL');
  const [statusFilter, setStatusFilter] = useState('ALL');
  const [pageNo, setPageNo] = useState('1');
  const [pageSize, setPageSize] = useState('12');
  const [totalSize, setTotalSize] = useState('0');
  const [totalPages, setTotalPages] = useState('0');

  const currentPageNumber = Number(pageNo) || 1;
  const totalPagesCount = Number(totalPages) || 0;
  const canPrev = currentPageNumber > 1;
  const canNext = totalPagesCount > 0 && currentPageNumber < totalPagesCount;

  const loadSessions = async (options: any = {}) => {
    setLoadingSessions(true);
    setPageError('');

    try {
      const page = await chatApi.listSessionsPage({
        keyword: options.keyword ?? keyword,
        chatMode: options.chatMode ?? modeFilter,
        turnStatus: options.turnStatus ?? statusFilter,
        pageNo: options.pageNo || pageNo,
        pageSize: options.pageSize || pageSize
      });
      setSessions(page.sessions || []);
      setPageNo(page.pageNo || '1');
      setPageSize(page.pageSize || pageSize);
      setTotalSize(page.totalSize || '0');
      setTotalPages(page.totalPages || '0');
    } catch (error) {
      setPageError(normalizeError(error, '加载会话列表失败'));
    } finally {
      setLoadingSessions(false);
    }
  };

  useEffect(() => {
    loadSessions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const summaryStats = useMemo(() => {
    const total = totalSize;
    const running = sessions.filter((item) => item.running).length;
    const documentMode = sessions.filter((item) => item.chatMode === 'DOCUMENT').length;
    const failed = sessions.filter((item) => item.latestTurnStatus === 'FAILED').length;

    return [
      { label: '会话总数', value: total, description: '后台当前可回看的全部业务会话数' },
      { label: '本页运行中', value: running, description: '正在生成中的会话会在详情页实时轮询' },
      { label: '本页文档问答', value: documentMode, description: '当前页里走 RAG 编排链路的会话规模' },
      { label: '本页最近失败', value: failed, description: '优先进入这些会话可更快定位问题' }
    ];
  }, [sessions, totalSize]);

  const applyFilters = () => {
    loadSessions({ pageNo: '1' });
  };

  const resetFilters = () => {
    setKeyword('');
    setModeFilter('ALL');
    setStatusFilter('ALL');
    loadSessions({
      keyword: '',
      chatMode: 'ALL',
      turnStatus: 'ALL',
      pageNo: '1',
      pageSize: pageSize
    });
  };

  const goPage = (nextPageNo: string) => {
    if (!nextPageNo || nextPageNo === pageNo || loadingSessions) return;
    loadSessions({ pageNo: nextPageNo });
  };

  const handlePageSizeChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const newSize = e.target.value;
    setPageSize(newSize);
    loadSessions({ pageNo: '1', pageSize: newSize });
  };

  const getStatusVariant = (tone: string) => {
    if (tone === 'running') return 'default';
    if (tone === 'completed') return 'success';
    if (tone === 'failed') return 'destructive';
    if (tone === 'warning') return 'warning';
    return 'secondary';
  };

  return (
    <div className="p-6 md:p-8 flex flex-col gap-6 max-w-7xl mx-auto w-full">
      {/* Header */}
      <div className="border-b border-border pb-6">
        <div className="flex justify-between items-start gap-4 mb-4">
          <div>
            <span className="text-xs font-mono text-muted-foreground uppercase tracking-widest">对话观测</span>
            <h2 className="text-2xl font-bold font-heading text-foreground mt-1 mb-2">选择会话，查看执行详情</h2>
            <p className="text-muted-foreground max-w-3xl leading-relaxed">
              观测每轮对话的执行路径、RAG 召回和模型用量。
            </p>
          </div>
          <Button onClick={() => loadSessions()} disabled={loadingSessions}>
            {loadingSessions ? '正在刷新...' : '刷新会话列表'}
          </Button>
        </div>

        <div className="flex gap-2 flex-wrap">
          {summaryStats.map(stat => (
            <div key={stat.label} title={stat.description} className="flex items-center gap-2 bg-secondary border border-border px-3 py-1.5 rounded-lg">
              <span className="text-sm text-muted-foreground">{stat.label}</span>
              <strong className="text-sm font-mono text-foreground">{stat.value}</strong>
            </div>
          ))}
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-end gap-3 pb-6 border-b border-border">
        <label className="flex flex-col gap-1 flex-1 min-w-[200px]">
          <span className="text-xs text-muted-foreground uppercase tracking-wider">搜索会话</span>
          <input 
            type="text" 
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && applyFilters()}
            placeholder="按会话ID、文档名、问题或回答筛选" 
            className="w-full border border-input bg-background rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
        </label>
        
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground uppercase tracking-wider">提问模式</span>
          <select 
            value={modeFilter} 
            onChange={(e) => setModeFilter(e.target.value)}
            className="border border-input bg-background rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          >
            <option value="ALL">全部模式</option>
            <option value="DOCUMENT">当前文档问答</option>
            <option value="AUTO_DOCUMENT">自动知识问答</option>
            <option value="OPEN_CHAT">开放式提问</option>
          </select>
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground uppercase tracking-wider">最近状态</span>
          <select 
            value={statusFilter} 
            onChange={(e) => setStatusFilter(e.target.value)}
            className="border border-input bg-background rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          >
            <option value="ALL">全部状态</option>
            <option value="RUNNING">进行中</option>
            <option value="COMPLETED">已完成</option>
            <option value="FAILED">失败</option>
            <option value="STOPPED">已停止</option>
          </select>
        </label>

        <div className="flex gap-2">
          <Button variant="outline" onClick={resetFilters}>重置筛选</Button>
          <Button onClick={applyFilters}>应用筛选</Button>
        </div>
      </div>

      {pageError && (
        <div className="p-4 bg-destructive/10 text-destructive rounded-lg text-sm border border-destructive/20">
          {pageError}
        </div>
      )}

      {/* List */}
      {loadingSessions ? (
        <div className="p-12 text-center text-muted-foreground border border-dashed border-border rounded-xl">
          正在加载会话列表...
        </div>
      ) : sessions.length === 0 ? (
        <div className="p-12 text-center text-muted-foreground border border-dashed border-border rounded-xl">
          当前筛选条件下没有匹配的会话。可以先清空筛选，或者去聊天页发起一轮对话再回来观察。
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {sessions.map(session => {
            const tone = session.running ? 'running' : statusTone(session.latestTurnStatus);
            return (
              <Card key={session.conversationId} className="relative overflow-hidden group border-border/40 shadow-sm hover:shadow-md hover:border-primary/30 transition-all">
                <div className={`absolute left-0 top-0 bottom-0 w-1 ${
                  tone === 'running' ? 'bg-primary animate-pulse' : 
                  tone === 'completed' ? 'bg-success' :
                  tone === 'failed' ? 'bg-destructive' : 'bg-warning'
                }`} />
                
                <CardContent className="p-5">
                  <div className="flex justify-between items-center mb-3">
                    <div className="flex gap-2">
                      <Badge variant="secondary">
                        {formatChatMode(session.chatMode)}
                      </Badge>
                      {session.running ? (
                        <Badge variant="default" className="bg-primary/10 text-primary border-primary/20 hover:bg-primary/20">
                          实时执行中
                        </Badge>
                      ) : session.latestTurnStatus ? (
                        <Badge variant={getStatusVariant(tone) as any}>
                          {formatStatusLabel(session.latestTurnStatus)}
                        </Badge>
                      ) : null}
                    </div>
                    <span className="text-xs text-muted-foreground font-mono">{formatTime(session.updatedAt)}</span>
                  </div>

                  <h3 className="text-base font-semibold font-heading text-foreground mb-2">
                    {sessionTitle(session)}
                  </h3>
                  <p className="text-sm text-muted-foreground mb-4 line-clamp-2 leading-relaxed opacity-90">
                    {sessionPreview(session)}
                  </p>

                  <div className="flex gap-4 text-xs text-muted-foreground mb-4 font-mono">
                    <span>{session.conversationId}</span>
                    <span>•</span>
                    <span>{sessionMessageCount(session)} 条消息</span>
                    {session.selectedDocumentName && (
                      <>
                        <span>•</span>
                        <span>{session.selectedDocumentName}</span>
                      </>
                    )}
                  </div>

                  {session.latestTurnErrorMessage && (
                    <div className="mb-4 p-3 bg-destructive/10 text-destructive rounded-lg text-sm">
                      最近一轮异常：{truncate(session.latestTurnErrorMessage, 88)}
                    </div>
                  )}

                  <div className="flex gap-4 border-t border-border pt-4 mt-2">
                    <Link 
                      to={`/admin/observability/${session.conversationId}`}
                      className="text-sm font-semibold text-primary hover:underline"
                    >
                      查看整页详情
                    </Link>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      {/* Pagination */}
      {!loadingSessions && totalPagesCount > 0 && (
        <div className="flex flex-col sm:flex-row justify-between items-center gap-4 pt-4 border-t border-border">
          <div className="text-sm text-muted-foreground">
            <strong className="text-foreground">第 {pageNo} / {totalPages} 页</strong>
            <span className="ml-2">共 {totalSize} 条记录</span>
          </div>
          
          <div className="flex items-center gap-4">
            <label className="flex items-center gap-2 text-sm text-muted-foreground">
              每页
              <select 
                value={pageSize} 
                onChange={handlePageSizeChange}
                className="border border-input bg-background rounded px-2 py-1"
              >
                <option value="12">12</option>
                <option value="24">24</option>
                <option value="36">36</option>
              </select>
            </label>
            
            <div className="flex gap-1">
              <Button 
                variant="outline"
                size="sm"
                disabled={!canPrev} 
                onClick={() => goPage(String(currentPageNumber - 1))}
              >
                上一页
              </Button>
              <Button 
                variant="outline"
                size="sm"
                disabled={!canNext} 
                onClick={() => goPage(String(currentPageNumber + 1))}
              >
                下一页
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
