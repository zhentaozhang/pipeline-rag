import React, { useState, useEffect } from 'react';
import { manageApi } from '../../lib/api';
import type { RouteTrace } from '../../types/api';

export const AdminKnowledgeRouteTraceView: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [records, setRecords] = useState<RouteTrace[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  
  const [filters, setFilters] = useState({
    conversationId: '',
    mode: '',
    routeStatus: ''
  });

  const [page, setPage] = useState({
    pageNo: 1,
    pageSize: 20,
    totalSize: 0,
    totalPages: 0
  });

  const selectedRecord = records.find(r => `${r.conversationId}_${r.exchangeId}` === selectedId);

  const loadTraces = async (pageNo = 1) => {
    setLoading(true);
    try {
      const data = await manageApi.queryKnowledgeRouteTracePage({
        ...filters,
        pageNo: String(pageNo),
        pageSize: String(page.pageSize)
      });
      setRecords(Array.isArray(data?.records) ? data.records : []);
      setPage({
        pageNo: Number(data?.pageNo || 1),
        pageSize: Number(data?.pageSize || 20),
        totalSize: Number(data?.total || 0),
        totalPages: Number(data?.totalPages || 0)
      });
      if (pageNo === 1) setSelectedId(null);
    } catch (error) {
      console.error('加载知识路由追踪失败', error);
      setRecords([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void (async () => {
      await loadTraces();
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleFilterChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const { name, value } = e.target;
    setFilters(prev => ({ ...prev, [name]: value }));
  };

  const handleSearch = () => {
    loadTraces(1);
  };

  const resetFilters = () => {
    setFilters({ conversationId: '', mode: '', routeStatus: '' });
    // setTimeout to allow state to update before fetch, or we can just fetch with empty params
    setTimeout(() => loadTraces(1), 0);
  };

  return (
    <div className="p-6 md:p-8 flex flex-col gap-6 max-w-[1600px] mx-auto w-full h-[calc(100vh-64px)] overflow-hidden">
      
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 border-b border-border/50 pb-4 flex-shrink-0">
        <div>
          <span className="text-xs font-bold text-primary uppercase tracking-wider mb-1 block opacity-80">
            路由追踪
          </span>
          <h2 className="text-2xl font-bold text-foreground tracking-tight">路由追踪</h2>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => loadTraces(page.pageNo)}
            disabled={loading}
            className="px-4 py-2 bg-background border border-border rounded-md text-sm font-medium text-muted-foreground hover:bg-secondary/80 hover:text-foreground transition-colors disabled:opacity-50"
          >
            {loading ? '刷新中...' : '刷新追踪'}
          </button>
        </div>
      </div>

      <div className="flex-1 flex flex-col md:flex-row gap-6 min-h-0">
        {/* Sidebar */}
        <div className="w-full md:w-80 lg:w-96 flex flex-col bg-background border border-border/50 rounded-xl shadow-sm overflow-hidden flex-shrink-0 h-full">
          <div className="p-4 border-b border-border/50 space-y-3 bg-secondary/10">
            <input
              type="text"
              name="conversationId"
              value={filters.conversationId}
              onChange={handleFilterChange}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
              placeholder="按会话 ID 筛选..."
              className="w-full px-3 py-2 bg-background border border-border rounded-md text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary/50 focus:border-primary/50 transition-all"
            />
            <div className="flex gap-2">
              <select
                name="mode"
                value={filters.mode}
                onChange={handleFilterChange}
                className="flex-1 px-2 py-1.5 bg-background border border-border rounded-md text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary/50"
              >
                <option value="">全部模式</option>
                <option value="shadow">shadow</option>
                <option value="auto">auto</option>
              </select>
              <select
                name="routeStatus"
                value={filters.routeStatus}
                onChange={handleFilterChange}
                className="flex-1 px-2 py-1.5 bg-background border border-border rounded-md text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary/50"
              >
                <option value="">全部状态</option>
                <option value="1">成功</option>
                <option value="2">低置信</option>
                <option value="3">失败</option>
              </select>
            </div>
            <div className="flex justify-end gap-2 pt-1">
              <button
                onClick={resetFilters}
                disabled={loading}
                className="px-3 py-1.5 bg-transparent border border-border rounded text-xs font-medium text-muted-foreground hover:bg-secondary/80 hover:text-foreground transition-colors"
              >
                重置
              </button>
              <button
                onClick={handleSearch}
                disabled={loading}
                className="px-3 py-1.5 bg-primary text-primary-foreground rounded text-xs font-medium hover:bg-primary/90 transition-colors disabled:opacity-50"
              >
                筛选
              </button>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-2 space-y-1">
            {loading ? (
              <div className="p-8 text-center text-muted-foreground text-sm">正在加载...</div>
            ) : records.length === 0 ? (
              <div className="p-8 text-center text-muted-foreground text-sm">暂无追踪记录</div>
            ) : (
              records.map(item => {
                const id = `${item.conversationId}_${item.exchangeId}`;
                return (
                <button
                  key={id}
                  onClick={() => setSelectedId(id)}
                  className={`w-full text-left p-3 rounded-lg border text-sm transition-all ${
                    selectedId === id
                      ? 'bg-primary/5 border-primary/20 shadow-sm'
                      : 'bg-transparent border-transparent hover:bg-secondary/50'
                  }`}
                >
                  <div className="flex flex-wrap gap-1.5 mb-2">
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-secondary text-muted-foreground border border-border/50">
                      {item.mode || 'unknown'}
                    </span>
                    <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium border ${
                      item.routeStatus === '1' ? 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20' :
                      item.routeStatus === '2' ? 'bg-amber-500/10 text-amber-500 border-amber-500/20' :
                      'bg-destructive/10 text-destructive border-destructive/20'
                    }`}>
                      {item.routeStatus === '1' ? '成功' : item.routeStatus === '2' ? '低置信' : '失败'}
                    </span>
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-primary/10 text-primary border border-primary/20">
                      {item.confidence != null ? (Number(item.confidence) * 100).toFixed(1) + '%' : '-'}
                    </span>
                  </div>
                  <p className="text-foreground line-clamp-2 mb-2 leading-relaxed">
                    {item.question || '未记录问题'}
                  </p>
                  <div className="flex justify-between items-center text-xs text-muted-foreground opacity-80">
                    <span className="truncate max-w-[60%]">
                       {item.conversationId ? `会话: ${item.conversationId.substring(0, 8)}...` : '未知会话'}
                    </span>
                    <span>{item.createdAt || '-'}</span>
                  </div>
                </button>
              )})
            )}
          </div>

          <div className="p-3 border-t border-border/50 flex items-center justify-between text-xs text-muted-foreground bg-secondary/5">
            <button
              disabled={page.pageNo <= 1 || loading}
              onClick={() => loadTraces(page.pageNo - 1)}
              className="px-2 py-1 hover:text-primary transition-colors disabled:opacity-50 disabled:hover:text-muted-foreground"
            >
              上一页
            </button>
            <span className="font-medium">{page.pageNo} / {page.totalPages || 1}</span>
            <button
              disabled={page.pageNo >= page.totalPages || loading}
              onClick={() => loadTraces(page.pageNo + 1)}
              className="px-2 py-1 hover:text-primary transition-colors disabled:opacity-50 disabled:hover:text-muted-foreground"
            >
              下一页
            </button>
          </div>
        </div>

        {/* Detail Panel */}
        <div className="flex-1 bg-background border border-border/50 rounded-xl shadow-sm overflow-hidden flex flex-col h-full">
          {selectedRecord ? (
            <div className="flex-1 overflow-y-auto p-6">
              <div className="mb-6">
                 <div className="flex flex-wrap gap-2 mb-4">
                    <span className="px-2 py-1 rounded text-xs font-medium bg-secondary text-muted-foreground border border-border/50">
                      模式: {selectedRecord.mode || 'unknown'}
                    </span>
                    <span className={`px-2 py-1 rounded text-xs font-medium border ${
                      selectedRecord.routeStatus === '1' ? 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20' :
                      selectedRecord.routeStatus === '2' ? 'bg-amber-500/10 text-amber-500 border-amber-500/20' :
                      'bg-destructive/10 text-destructive border-destructive/20'
                    }`}>
                      状态: {selectedRecord.routeStatus === '1' ? '成功' : selectedRecord.routeStatus === '2' ? '低置信' : '失败'}
                    </span>
                    <span className="px-2 py-1 rounded text-xs font-medium bg-primary/10 text-primary border border-primary/20">
                      置信度: {selectedRecord.confidence != null ? (Number(selectedRecord.confidence) * 100).toFixed(2) + '%' : '未知'}
                    </span>
                 </div>
                 <h3 className="text-xl font-bold text-foreground mb-3 tracking-tight leading-relaxed">
                   {selectedRecord.question || '未记录问题'}
                 </h3>
                 <p className="text-sm text-muted-foreground bg-secondary/20 p-4 rounded-md border border-border/50">
                   <strong className="text-foreground">改写问题：</strong> {selectedRecord.rewriteQuestion || '未记录改写问题'}
                 </p>
                 <div className="flex gap-6 mt-4 text-xs text-muted-foreground opacity-80 font-mono">
                   <span>{selectedRecord.createdAt || '-'}</span>
                   <span>会话: {selectedRecord.conversationId || '-'}</span>
                   <span>轮次: {selectedRecord.exchangeId || '-'}</span>
                 </div>
              </div>

              </div>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center p-8 text-center text-muted-foreground">
              <svg className="w-12 h-12 text-muted-foreground/30 mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              <p className="text-sm">从左侧选择一条追踪记录查看详情</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
