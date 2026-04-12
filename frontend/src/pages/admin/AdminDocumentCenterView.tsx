import React, { useState, useEffect } from 'react';
import { manageApi } from '../../lib/api';
import { formatDateTime, formatFileSize, normalizeCode } from '../../lib/manageFormat';
import { AdminStatusBadge } from '../../components/admin/AdminStatusBadge';
import { AdminDocumentStrategyView } from '../../components/admin/AdminDocumentStrategyView';
import { AdminDocumentExecutionView } from '../../components/admin/AdminDocumentExecutionView';
import { AdminDocumentChunkView } from '../../components/admin/AdminDocumentChunkView';

type TabType = 'strategy' | 'execution' | 'chunk';

export const AdminDocumentCenterView: React.FC = () => {
  const [documents, setDocuments] = useState<any[]>([]);
  const [keyword, setKeyword] = useState('');
  const [listLoading, setListLoading] = useState(false);
  const [selectedDocumentId, setSelectedDocumentId] = useState<string>('');
  const [activeTab, setActiveTab] = useState<TabType>('strategy');
  const [toastMsg, setToastMsg] = useState<{msg: string, type: string} | null>(null);
  
  const selectedDocument = documents.find(d => normalizeCode(d.documentId) === normalizeCode(selectedDocumentId));

  const loadDocuments = async () => {
    setListLoading(true);
    try {
      const data = await manageApi.queryDocumentPage({
        pageNo: 1,
        pageSize: 50,
        keyword: keyword.trim()
      });
      setDocuments(Array.isArray(data?.records) ? data.records : []);
    } catch (error) {
      console.error('加载文档列表失败', error);
    } finally {
      setListLoading(false);
    }
  };

  useEffect(() => {
    loadDocuments();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const showNotice = (msg: string, type: 'info' | 'success' | 'danger' = 'info') => {
    setToastMsg({ msg, type });
    setTimeout(() => setToastMsg(null), 3000);
  };

  return (
    <div className="p-6 md:p-8 flex flex-col md:flex-row gap-6 max-w-[1600px] mx-auto w-full h-[calc(100vh-64px)] overflow-hidden relative">
      
      {toastMsg && (
        <div className={`absolute top-4 right-4 px-4 py-2 rounded-md shadow-md z-50 text-sm font-medium ${
          toastMsg.type === 'success' ? 'bg-emerald-50 text-emerald-600 border border-emerald-200' :
          toastMsg.type === 'danger' ? 'bg-destructive/10 text-destructive border border-destructive/20' :
          'bg-secondary text-foreground border border-border'
        }`}>
          {toastMsg.msg}
        </div>
      )}

      {/* Master List */}
      <div className="w-full md:w-96 lg:w-[400px] flex flex-col bg-background border border-border/50 rounded-xl shadow-sm overflow-hidden flex-shrink-0 h-full">
        <div className="p-4 border-b border-border/50">
          <h3 className="text-lg font-bold text-foreground mb-3">文档工作台</h3>
          <div className="relative">
            <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
              <svg className="h-4 w-4 text-muted-foreground/60" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
            </div>
            <input
              type="text"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && loadDocuments()}
              placeholder="搜索文档名称"
              className="block w-full pl-10 pr-3 py-2 bg-secondary/30 border border-border/50 rounded-md text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-colors"
            />
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          {listLoading ? (
            <div className="p-8 text-center text-muted-foreground text-sm">加载中...</div>
          ) : documents.length === 0 ? (
            <div className="p-8 text-center text-muted-foreground text-sm">暂无文档</div>
          ) : (
            <div className="divide-y divide-border/30">
              {documents.map(item => (
                <button
                  key={item.documentId}
                  onClick={() => { setSelectedDocumentId(item.documentId); setActiveTab('strategy'); }}
                  className={`w-full text-left p-4 hover:bg-secondary/50 transition-colors ${
                    normalizeCode(selectedDocumentId) === normalizeCode(item.documentId) 
                      ? 'bg-primary/5 border-l-4 border-primary' 
                      : 'border-l-4 border-transparent'
                  }`}
                >
                  <div className="flex flex-col gap-1">
                    <span className="font-bold text-sm text-foreground truncate">
                      {item.documentName}
                    </span>
                    <span className="text-xs text-muted-foreground truncate">
                      {item.originalFileName}
                    </span>
                    <div className="flex gap-2 mt-1">
                      <AdminStatusBadge label={item.parseStatusName} code={item.parseStatus} type="parse" />
                      <AdminStatusBadge label={item.indexStatusName} code={item.indexStatus} type="index" />
                    </div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Detail Area */}
      <div className="flex-1 bg-background border border-border/50 rounded-xl shadow-sm overflow-hidden flex flex-col h-full">
        {selectedDocument ? (
          <div className="flex flex-col h-full">
            <div className="p-6 border-b border-border/50 flex-shrink-0">
              <h2 className="text-xl font-bold text-foreground mb-1">
                {selectedDocument.documentName}
              </h2>
              <p className="text-sm text-muted-foreground mb-4">{selectedDocument.originalFileName}</p>
              
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 bg-secondary/20 p-4 rounded-lg border border-border/50 mb-4">
                <div>
                  <span className="text-xs text-muted-foreground block mb-1">类型</span>
                  <span className="font-mono text-sm">{selectedDocument.fileTypeName || '-'}</span>
                </div>
                <div>
                  <span className="text-xs text-muted-foreground block mb-1">大小</span>
                  <span className="font-mono text-sm">{formatFileSize(selectedDocument.fileSize)}</span>
                </div>
                <div>
                  <span className="text-xs text-muted-foreground block mb-1">字符数</span>
                  <span className="font-mono text-sm">{selectedDocument.charCount || 0}</span>
                </div>
                <div>
                  <span className="text-xs text-muted-foreground block mb-1">更新时间</span>
                  <span className="font-mono text-sm">{formatDateTime(selectedDocument.editTime)}</span>
                </div>
              </div>

              {/* Tabs */}
              <div className="flex gap-1 border-b border-border/50 mt-2">
                <button
                  onClick={() => setActiveTab('strategy')}
                  className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 ${
                    activeTab === 'strategy' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'
                  }`}
                >
                  策略配置
                </button>
                <button
                  onClick={() => setActiveTab('execution')}
                  className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 ${
                    activeTab === 'execution' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'
                  }`}
                >
                  构建执行
                </button>
                <button
                  onClick={() => setActiveTab('chunk')}
                  className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 ${
                    activeTab === 'chunk' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'
                  }`}
                >
                  切块验证
                </button>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto">
              {activeTab === 'strategy' && (
                <AdminDocumentStrategyView 
                  documentId={selectedDocument.documentId} 
                  documentDetail={selectedDocument}
                  showNotice={showNotice}
                  onStrategyConfirmed={loadDocuments}
                />
              )}
              {activeTab === 'execution' && (
                <AdminDocumentExecutionView 
                  documentId={selectedDocument.documentId} 
                  documentDetail={selectedDocument}
                  showNotice={showNotice}
                  onRefresh={loadDocuments}
                />
              )}
              {activeTab === 'chunk' && (
                <AdminDocumentChunkView 
                  documentId={selectedDocument.documentId} 
                  documentDetail={selectedDocument}
                  showNotice={showNotice}
                />
              )}
            </div>
          </div>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center p-8 text-center text-muted-foreground">
            <svg className="w-16 h-16 text-muted-foreground/30 mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M8 14v3m4-3v3m4-3v3M3 21h18M3 10h18M3 7l9-4 9 4M4 10h16v11H4V10z" />
            </svg>
            <p className="text-lg font-medium text-foreground mb-2">未选择文档</p>
            <p className="text-sm">请在左侧列表中选择一份文档以查看详情和进行策略配置。</p>
          </div>
        )}
      </div>
    </div>
  );
};
