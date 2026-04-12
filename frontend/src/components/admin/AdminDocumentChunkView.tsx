import React, { useState, useEffect } from 'react';
import { manageApi } from '../../lib/api';

interface AdminDocumentChunkViewProps {
  documentId: string;
  documentDetail: any;
  showNotice: (msg: string, type?: 'info' | 'success' | 'danger') => void;
}

export const AdminDocumentChunkView: React.FC<AdminDocumentChunkViewProps> = ({ 
  documentId, 
  documentDetail, 
  showNotice
}) => {
  const [loading, setLoading] = useState(false);
  const [chunks, setChunks] = useState<any[]>([]);
  const [pageNo, setPageNo] = useState(1);
  const [total, setTotal] = useState(0);

  const hasIndexSuccess = documentDetail?.indexStatus === 3;

  const loadChunks = async (page = pageNo) => {
    if (!hasIndexSuccess) return;
    setLoading(true);
    try {
      const data = await manageApi.queryDocumentChunks({
        documentId,
        pageNo: String(page),
        pageSize: '50'
      });
      setChunks(data?.records || []);
      setTotal(Number(data?.total || 0));
      setPageNo(page);
    } catch (error) {
      console.error('加载切块失败', error);
      showNotice('加载切块数据失败', 'danger');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (documentId && hasIndexSuccess) {
      loadChunks(1);
    }
  }, [documentId, hasIndexSuccess]);

  if (!hasIndexSuccess) {
    return (
      <div className="p-8 text-center text-muted-foreground bg-secondary/30 rounded-xl border border-border/50 m-6">
        当前文档尚未完成索引构建。请先在“确认并构建”页面发起构建，等待构建完成后再来查看切块。
      </div>
    );
  }

  return (
    <div className="p-6 md:p-8">
      <div className="mb-6 flex justify-between items-end">
        <div>
          <h3 className="text-lg font-bold text-foreground tracking-tight">切块验证</h3>
          <p className="text-sm text-muted-foreground mt-1">在这里检查分块结构、分页浏览内容，并验证切块是否符合预期。</p>
        </div>
        <button
          onClick={() => loadChunks(pageNo)}
          disabled={loading}
          className="px-4 py-2 bg-background border border-border rounded-md text-sm font-medium text-muted-foreground hover:bg-secondary/80 hover:text-foreground transition-colors disabled:opacity-50"
        >
          {loading ? '刷新中...' : '刷新切块'}
        </button>
      </div>

      <div className="bg-background border border-border/50 rounded-xl overflow-hidden flex flex-col min-h-[500px]">
        {loading && chunks.length === 0 ? (
          <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground">
            <svg className="animate-spin h-8 w-8 text-primary mb-4" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            <p>正在加载切块数据...</p>
          </div>
        ) : chunks.length === 0 ? (
          <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground p-8 text-center">
            <p>未找到切块数据，请确认构建任务是否成功完成。</p>
          </div>
        ) : (
          <>
            <div className="flex-1 overflow-x-auto">
              <table className="w-full text-left min-w-[800px]">
                <thead>
                  <tr className="bg-secondary/30 border-b border-border/50">
                    <th className="px-5 py-3.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider w-28">切块编号</th>
                    <th className="px-5 py-3.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider w-28">父块编号</th>
                    <th className="px-5 py-3.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider">章节 / 标识</th>
                    <th className="px-5 py-3.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider w-24 text-right">字符数</th>
                    <th className="px-5 py-3.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider w-24 text-right">Token</th>
                  </tr>
                </thead>
                <tbody>
                  {chunks.map((item, idx) => (
                    <tr key={item.chunkId || idx} className="hover:bg-secondary/50 transition-colors border-b border-border/20 last:border-0">
                      <td className="px-5 py-4 text-sm font-medium text-foreground font-mono">
                        C#{item.chunkNo || '-'}
                      </td>
                      <td className="px-5 py-4 text-sm text-muted-foreground font-mono">
                        {item.parentBlockNo ? `P#${item.parentBlockNo}` : '-'}
                      </td>
                      <td className="px-5 py-4 text-sm text-muted-foreground">
                        <div className="truncate max-w-sm mb-1.5 font-medium text-foreground">{item.sectionPath || '-'}</div>
                        <div className="text-xs opacity-80 leading-relaxed" title={item.chunkText}>{item.chunkText}</div>
                      </td>
                      <td className="px-5 py-4 text-sm text-muted-foreground text-right font-mono">
                        {item.charCount || 0}
                      </td>
                      <td className="px-5 py-4 text-sm text-muted-foreground text-right font-mono">
                        {item.tokenCount || 0}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            
            <div className="px-5 py-4 border-t border-border/50 bg-secondary/10 flex items-center justify-between">
              <button
                disabled={pageNo <= 1 || loading}
                onClick={() => loadChunks(pageNo - 1)}
                className="px-4 py-1.5 border border-border text-sm font-medium rounded-md text-muted-foreground bg-background hover:bg-secondary/80 disabled:opacity-50 transition-colors"
              >
                上一页
              </button>
              <div className="text-center text-sm text-muted-foreground font-medium">
                第 {pageNo} 页，共 {total} 条
              </div>
              <button
                disabled={chunks.length < 50 || loading}
                onClick={() => loadChunks(pageNo + 1)}
                className="px-4 py-1.5 border border-border text-sm font-medium rounded-md text-muted-foreground bg-background hover:bg-secondary/80 disabled:opacity-50 transition-colors"
              >
                下一页
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
};
