import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { manageApi, APIError } from '../../lib/api';
import type { ManageDocument } from '../../types/api';
import { formatDateTime, formatFileSize } from '../../lib/manageFormat';
import { AdminStatusBadge } from '../../components/admin/AdminStatusBadge';
import { AdminDocumentStrategyView } from '../../components/admin/AdminDocumentStrategyView';
import { AdminDocumentExecutionView } from '../../components/admin/AdminDocumentExecutionView';
import { AdminDocumentChunkView } from '../../components/admin/AdminDocumentChunkView';
import { Button } from '../../components/ui/Button';

export const AdminDocumentDetailView: React.FC = () => {
  const { documentId } = useParams<{ documentId: string }>();
  const navigate = useNavigate();

  const [loading, setLoading] = useState(true);
  const [documentDetail, setDocumentDetail] = useState<ManageDocument | null>(null);
  const [activeSection, setActiveSection] = useState<'overview' | 'strategy' | 'execution' | 'chunk'>('overview');
  const [pageNotice, setPageNotice] = useState({ type: 'info', message: '' });

  const showNotice = (message: string, type: 'info' | 'success' | 'danger' = 'info') => {
    setPageNotice({ type, message });
  };

  const loadDocumentDetail = async () => {
    if (!documentId) return;
    setLoading(true);
    try {
      const data = await manageApi.queryDocumentDetail(documentId);
      setDocumentDetail(data);
    } catch (error) {
      console.error('加载文档详情失败', error);
      showNotice(error instanceof APIError ? error.message : '加载文档详情失败', 'danger');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void (async () => {
      await loadDocumentDetail();
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentId]);

  if (loading && !documentDetail) {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-[400px] text-muted-foreground">
        <svg className="animate-spin h-8 w-8 text-primary mb-4" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        <p>正在加载文档详情...</p>
      </div>
    );
  }

  if (!documentDetail) {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-[400px] text-muted-foreground">
        <p>未能找到该文档，或已被删除。</p>
        <Button onClick={() => navigate('/admin/documents')} className="mt-4">
          返回列表
        </Button>
      </div>
    );
  }

  const sections = [
    { key: 'overview', label: '文档概览', step: '概览', desc: '确认文档状态' },
    { key: 'strategy', label: '配置策略', step: '策略', desc: '调整切块策略' },
    { key: 'execution', label: '构建索引', step: '构建', desc: '执行索引构建' },
    { key: 'chunk', label: '切块验证', step: '验证', desc: '检查分块结果' },
  ];

  return (
    <div className="p-6 md:p-8 flex flex-col gap-6 max-w-7xl mx-auto w-full">
      {/* Top Navigation */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <button
            onClick={() => navigate('/admin/documents')}
            className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
            </svg>
            返回文档列表
          </button>
          <div className="h-4 w-px bg-border"></div>
          <h2 className="text-xl font-bold text-foreground truncate max-w-md">
            {documentDetail.documentName}
          </h2>
        </div>
        <Button variant="outline" onClick={loadDocumentDetail}>
          刷新详情
        </Button>
      </div>

      {pageNotice.message && (
        <div className={`p-4 rounded-lg text-sm border ${
          pageNotice.type === 'success' ? 'bg-success/10 border-success/20 text-success' :
          pageNotice.type === 'danger' ? 'bg-destructive/10 border-destructive/20 text-destructive' :
          'bg-primary/10 border-primary/20 text-primary'
        }`}>
          {pageNotice.message}
        </div>
      )}

      {/* Main Content Layout */}
      <div className="flex flex-col lg:flex-row gap-6 items-start">
        {/* Sidebar Navigation */}
        <div className="w-full lg:w-64 flex-shrink-0 flex flex-col gap-2 sticky top-6">
          {sections.map((section) => (
            <button
              key={section.key}
              onClick={() => setActiveSection(section.key as 'overview' | 'strategy' | 'execution' | 'chunk')}
              className={`flex flex-col items-start p-4 rounded-xl border text-left transition-all ${
                activeSection === section.key
                  ? 'bg-primary/5 border-primary/20'
                  : 'bg-background border-border hover:border-primary/30'
              }`}
            >
              <div className="flex items-center gap-2 mb-1">
                <span className={`text-xs font-bold px-2 py-0.5 rounded-md ${
                  activeSection === section.key 
                    ? 'bg-primary/10 text-primary' 
                    : 'bg-secondary text-muted-foreground'
                }`}>
                  {section.step}
                </span>
                <span className={`font-bold ${
                  activeSection === section.key ? 'text-primary' : 'text-foreground'
                }`}>
                  {section.label}
                </span>
              </div>
              <p className={`text-xs ${
                activeSection === section.key ? 'text-primary/70' : 'text-muted-foreground'
              }`}>
                {section.desc}
              </p>
            </button>
          ))}
        </div>

        {/* Content Area */}
        <div className="flex-1 bg-background border border-border rounded-xl shadow-sm overflow-hidden min-h-[600px]">
          
          {/* Overview Section */}
          {activeSection === 'overview' && (
            <div className="p-6 md:p-8">
              <div className="mb-8">
                <h3 className="text-lg font-bold text-foreground">文档概览</h3>
                <p className="text-sm text-muted-foreground mt-1">先确认文档状态、关键指标和当前工作焦点，再进入后续流程。</p>
              </div>

              <div className="bg-secondary/30 rounded-xl p-6 mb-8 border border-border">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div>
                    <label className="text-xs font-bold text-muted-foreground uppercase tracking-wider mb-2 block">文档名称</label>
                    <p className="font-medium text-foreground text-lg break-all">
                      {documentDetail.documentName}
                    </p>
                    {documentDetail.documentName !== documentDetail.originalFileName && (
                      <p className="text-sm text-muted-foreground mt-1 break-all">
                        {documentDetail.originalFileName}
                      </p>
                    )}
                  </div>
                  <div>
                    <label className="text-xs font-bold text-muted-foreground uppercase tracking-wider mb-2 block">状态标识</label>
                    <div className="flex flex-wrap gap-2">
                      <AdminStatusBadge label={documentDetail.parseStatusName} code={documentDetail.parseStatus} type="parse" />
                      <AdminStatusBadge label={documentDetail.strategyStatusName} code={documentDetail.strategyStatus} type="strategy" />
                      <AdminStatusBadge label={documentDetail.indexStatusName} code={documentDetail.indexStatus} type="index" />
                    </div>
                  </div>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-6 pt-6 border-t border-border">
                  <div>
                    <label className="text-xs text-muted-foreground block mb-1">文件类型</label>
                    <span className="font-mono text-sm font-medium text-foreground">
                      {documentDetail.fileTypeName || '-'}
                    </span>
                  </div>
                  <div>
                    <label className="text-xs text-muted-foreground block mb-1">文件大小</label>
                    <span className="font-mono text-sm font-medium text-foreground">
                      {formatFileSize(documentDetail.fileSize)}
                    </span>
                  </div>
                  <div>
                    <label className="text-xs text-muted-foreground block mb-1">更新时间</label>
                    <span className="font-mono text-sm font-medium text-foreground">
                      {formatDateTime(documentDetail.editTime)}
                    </span>
                  </div>
                  <div>
                    <label className="text-xs text-muted-foreground block mb-1">业务分类</label>
                    <span className="text-sm font-medium text-foreground">
                      {documentDetail.businessCategory || '-'}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Strategy Section */}
          {activeSection === 'strategy' && (
            <AdminDocumentStrategyView 
              documentId={documentId!} 
              documentDetail={documentDetail} 
              showNotice={showNotice}
              onStrategyConfirmed={loadDocumentDetail}
            />
          )}

          {/* Execution Section */}
          {activeSection === 'execution' && (
            <AdminDocumentExecutionView 
              documentId={documentId!} 
              documentDetail={documentDetail} 
              showNotice={showNotice}
              onRefresh={loadDocumentDetail}
            />
          )}

          {/* Chunk Section */}
          {activeSection === 'chunk' && (
            <AdminDocumentChunkView 
              documentId={documentId!} 
              documentDetail={documentDetail} 
              showNotice={showNotice}
            />
          )}

        </div>
      </div>
    </div>
  );
};
