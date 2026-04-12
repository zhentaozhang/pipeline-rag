import React, { useState, useEffect, useRef, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { manageApi, APIError } from '../../lib/api';
import { formatDateTime, formatFileSize, hasCode } from '../../lib/manageFormat';
import { AdminStatusBadge } from '../../components/admin/AdminStatusBadge';

const OPERATOR_ID = '10001';
const DEFAULT_PAGE_SIZE = 12;

export const AdminDocumentListView: React.FC = () => {
  const navigate = useNavigate();

  const [uploadForm, setUploadForm] = useState({
    documentName: '',
    knowledgeScopeCode: '',
    knowledgeScopeName: '',
    businessCategory: '',
    documentTags: '',
    file: null as File | null
  });
  
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [listLoading, setListLoading] = useState(false);
  const [keyword, setKeyword] = useState('');
  const [documents, setDocuments] = useState<any[]>([]);
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [total, setTotal] = useState(0);
  const [deletingDocumentId, setDeletingDocumentId] = useState('');
  const [pageNotice, setPageNotice] = useState({ type: 'info', message: '' });

  const totalPages = useMemo(() => Math.max(1, Math.ceil(total / pageSize)), [total, pageSize]);
  const visibleParseReadyCount = useMemo(() => documents.filter((item) => hasCode(item.parseStatus, 3)).length, [documents]);
  const visibleStrategyReadyCount = useMemo(() => documents.filter((item) => hasCode(item.strategyStatus, 3)).length, [documents]);
  const visibleIndexReadyCount = useMemo(() => documents.filter((item) => hasCode(item.indexStatus, 3)).length, [documents]);

  const showNotice = (message: string, type: 'info' | 'success' | 'danger' = 'info') => {
    setPageNotice({ type, message });
  };

  const clearNotice = () => setPageNotice({ type: 'info', message: '' });

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setUploadForm({ ...uploadForm, file: e.target.files?.[0] || null });
  };

  const clearSelectedFile = () => {
    setUploadForm({
      documentName: '',
      knowledgeScopeCode: '',
      knowledgeScopeName: '',
      businessCategory: '',
      documentTags: '',
      file: null
    });
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const normalizeError = (error: any, fallbackMessage: string) => {
    if (error instanceof APIError && error.message) return error.message;
    if (error instanceof Error && error.message) return error.message;
    return fallbackMessage;
  };

  const loadDocuments = async (page = currentPage) => {
    setListLoading(true);
    try {
      const data = await manageApi.queryDocumentPage({
        pageNo: page,
        pageSize,
        keyword: keyword.trim()
      });
      setDocuments(Array.isArray(data?.records) ? data.records : []);
      setCurrentPage(Number(data?.pageNo || page));
      setPageSize(Number(data?.pageSize || pageSize));
      setTotal(Number(data?.total || 0));
    } catch (error) {
      console.error('加载文档列表失败', error);
      showNotice(normalizeError(error, '加载文档列表失败'), 'danger');
      setDocuments([]);
    } finally {
      setListLoading(false);
    }
  };

  const submitSearch = () => {
    setCurrentPage(1);
    loadDocuments(1);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') submitSearch();
  };

  const changePage = (page: number) => {
    if (page < 1 || page > totalPages || page === currentPage) return;
    loadDocuments(page);
  };

  const openDocumentDetail = (documentId: string | number) => {
    if (documentId == null) return;
    navigate(`/admin/documents/${documentId}`);
  };

  const isDeletingDocument = (documentId: string | number) => {
    return String(deletingDocumentId) === String(documentId || '');
  };

  const hasRunningDocumentTask = (item: any) => {
    return hasCode(item?.latestTaskStatus, 1)
      || hasCode(item?.latestTaskStatus, 2)
      || hasCode(item?.parseStatus, 2)
      || hasCode(item?.indexStatus, 2);
  };

  const canDeleteDocument = (item: any) => {
    if (!item?.documentId) return false;
    return !listLoading && !deletingDocumentId && !hasRunningDocumentTask(item);
  };

  const buildDeleteTitle = (item: any) => {
    if (hasRunningDocumentTask(item)) return '请等待当前任务完成后再删除';
    if (deletingDocumentId) return '当前有文档正在删除';
    return '删除文档以及关联的索引、存储文件';
  };

  const submitUpload = async () => {
    if (!uploadForm.file) {
      showNotice('请先选择要上传的文档。', 'danger');
      return;
    }

    setUploading(true);
    clearNotice();

    try {
      const result = await manageApi.uploadDocument({
        file: uploadForm.file,
        documentName: uploadForm.documentName.trim(),
        operatorId: OPERATOR_ID,
        knowledgeScopeCode: uploadForm.knowledgeScopeCode.trim(),
        knowledgeScopeName: uploadForm.knowledgeScopeName.trim(),
        businessCategory: uploadForm.businessCategory.trim(),
        documentTags: uploadForm.documentTags.trim()
      });
      clearSelectedFile();
      showNotice(`文档已上传，任务 ${result.taskId} 已进入解析与策略推荐队列。`, 'success');
      await loadDocuments(1);
      openDocumentDetail(result.documentId);
    } catch (error) {
      console.error('上传文档失败', error);
      showNotice(normalizeError(error, '上传文档失败'), 'danger');
    } finally {
      setUploading(false);
    }
  };

  const deleteDocument = async (item: any) => {
    if (!item?.documentId) return;

    if (hasRunningDocumentTask(item)) {
      showNotice('当前文档存在进行中的任务，请等待任务完成后再删除。', 'danger');
      return;
    }

    const documentId = String(item.documentId);
    const documentName = item.documentName || item.originalFileName || documentId;
    const confirmed = window.confirm(
      `确认删除文档《${documentName}》吗？\n\n将同时删除 MySQL 记录、向量库数据和 MinIO 存储文件，删除后不可恢复。`
    );
    if (!confirmed) return;

    setDeletingDocumentId(documentId);
    clearNotice();

    try {
      await manageApi.deleteDocument({ documentId });
      const nextPage = documents.length === 1 && currentPage > 1 ? currentPage - 1 : currentPage;
      await loadDocuments(nextPage);
      showNotice(`文档《${documentName}》已删除，关联数据已同步清理。`, 'success');
    } catch (error) {
      console.error('删除文档失败', error);
      showNotice(normalizeError(error, '删除文档失败'), 'danger');
    } finally {
      setDeletingDocumentId('');
    }
  };

  useEffect(() => {
    loadDocuments();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="p-6 md:p-8 flex flex-col gap-6 max-w-7xl mx-auto w-full">
      {/* Top Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-[1.1fr_0.9fr] gap-6">
        {/* Upload Card */}
        <div className="bg-background border border-border rounded-xl shadow-sm p-5 md:p-6 flex flex-col h-full">
          <div className="mb-4 pb-4 border-b border-gray-100 dark:border-gray-800">
            <h3 className="text-lg font-bold text-gray-900 dark:text-white">上传新文档</h3>
            <p className="text-sm text-gray-500 mt-1">支持 PDF / DOC / DOCX / TXT / MD / HTML</p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-bold text-gray-600 dark:text-gray-400">文档名称</label>
              <input 
                type="text" 
                value={uploadForm.documentName}
                onChange={(e) => setUploadForm({ ...uploadForm, documentName: e.target.value })}
                placeholder="不填则使用原始文件名" 
                className="w-full px-3 py-2 bg-background border border-input rounded-md text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring transition-colors"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-bold text-gray-600 dark:text-gray-400">知识域编码</label>
              <input 
                type="text" 
                value={uploadForm.knowledgeScopeCode}
                onChange={(e) => setUploadForm({ ...uploadForm, knowledgeScopeCode: e.target.value })}
                placeholder="例如 operation_rule" 
                className="w-full px-3 py-2 bg-background border border-input rounded-md text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring transition-colors"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-bold text-gray-600 dark:text-gray-400">知识域名称</label>
              <input 
                type="text" 
                value={uploadForm.knowledgeScopeName}
                onChange={(e) => setUploadForm({ ...uploadForm, knowledgeScopeName: e.target.value })}
                placeholder="例如 运营规则" 
                className="w-full px-3 py-2 bg-background border border-input rounded-md text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring transition-colors"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-bold text-gray-600 dark:text-gray-400">业务分类</label>
              <input 
                type="text" 
                value={uploadForm.businessCategory}
                onChange={(e) => setUploadForm({ ...uploadForm, businessCategory: e.target.value })}
                placeholder="例如 手册 / 规则 / 介绍" 
                className="w-full px-3 py-2 bg-background border border-input rounded-md text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring transition-colors"
              />
            </div>
            <div className="flex flex-col gap-1.5 sm:col-span-2">
              <label className="text-xs font-bold text-gray-600 dark:text-gray-400">文档标签</label>
              <input 
                type="text" 
                value={uploadForm.documentTags}
                onChange={(e) => setUploadForm({ ...uploadForm, documentTags: e.target.value })}
                placeholder="多个标签用英文逗号分隔" 
                className="w-full px-3 py-2 bg-background border border-input rounded-md text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring transition-colors"
              />
            </div>
          </div>

          <div className="mt-auto">
            <div className="flex items-center justify-center w-full mb-4">
              <label className="flex flex-col items-center justify-center w-full h-24 border-2 border-dashed border-border rounded-lg cursor-pointer bg-secondary/30 hover:bg-secondary/80 transition-colors relative overflow-hidden group">
                <div className="flex flex-col items-center justify-center pt-5 pb-6">
                  {uploadForm.file ? (
                    <div className="text-center px-4">
                      <svg className="w-8 h-8 mb-2 text-primary mx-auto" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                      </svg>
                      <p className="text-sm font-medium text-foreground truncate max-w-[200px] sm:max-w-[300px]">
                        {uploadForm.file.name}
                      </p>
                      <p className="text-xs text-muted-foreground mt-1">{formatFileSize(uploadForm.file.size)}</p>
                    </div>
                  ) : (
                    <>
                      <svg className="w-8 h-8 mb-3 text-muted-foreground group-hover:text-primary transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                      </svg>
                      <p className="text-sm text-muted-foreground">
                        <span className="font-semibold text-primary">点击选择文件</span> 或拖拽到这里
                      </p>
                    </>
                  )}
                </div>
                <input ref={fileInputRef} type="file" className="hidden" onChange={handleFileChange} />
              </label>
            </div>

            <div className="flex justify-end gap-3">
              <button 
                type="button" 
                onClick={clearSelectedFile}
                className="px-4 py-2 bg-transparent border border-border rounded-md text-sm font-medium text-muted-foreground hover:bg-secondary/80 transition-colors"
              >
                清空
              </button>
              <button 
                type="button" 
                disabled={uploading || !uploadForm.file}
                onClick={submitUpload}
                className="px-4 py-2 bg-primary hover:bg-primary/90 text-primary-foreground rounded-md text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
              >
                {uploading ? (
                  <>
                    <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-primary-foreground" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    上传中...
                  </>
                ) : (
                  <>
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                    </svg>
                    上传并解析
                  </>
                )}
              </button>
            </div>
          </div>
        </div>

        {/* Tips Card */}
        <div className="bg-background border border-border rounded-xl shadow-sm p-5 md:p-6 flex flex-col h-full">
          <div className="mb-4 pb-4 border-b border-gray-100 dark:border-gray-800 flex items-center gap-2">
            <svg className="w-5 h-5 text-indigo-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <h3 className="text-lg font-bold text-gray-900 dark:text-white">建议操作顺序</h3>
          </div>
          <ul className="space-y-4 text-sm text-gray-600 dark:text-gray-300 mt-2">
            <li className="flex gap-3">
              <div className="flex-shrink-0 w-6 h-6 rounded-full bg-indigo-100 dark:bg-indigo-900/50 text-indigo-600 dark:text-indigo-400 flex items-center justify-center font-bold text-xs mt-0.5">1</div>
              <p className="leading-relaxed">先上传文档，系统会异步解析并生成推荐切块策略。</p>
            </li>
            <li className="flex gap-3">
              <div className="flex-shrink-0 w-6 h-6 rounded-full bg-indigo-100 dark:bg-indigo-900/50 text-indigo-600 dark:text-indigo-400 flex items-center justify-center font-bold text-xs mt-0.5">2</div>
              <p className="leading-relaxed">点击任意文档，进入详情页查看解析结果、切块和任务轨迹。</p>
            </li>
            <li className="flex gap-3">
              <div className="flex-shrink-0 w-6 h-6 rounded-full bg-indigo-100 dark:bg-indigo-900/50 text-indigo-600 dark:text-indigo-400 flex items-center justify-center font-bold text-xs mt-0.5">3</div>
              <p className="leading-relaxed">在详情页确认策略并构建索引，列表页专注浏览和筛选。</p>
            </li>
          </ul>
        </div>
      </div>

      {pageNotice.message && (
        <div className={`p-4 rounded-lg text-sm border ${
          pageNotice.type === 'success' ? 'bg-emerald-50 border-emerald-100 text-emerald-700 dark:bg-emerald-900/20 dark:border-emerald-800/50 dark:text-emerald-400' :
          pageNotice.type === 'danger' ? 'bg-red-50 border-red-100 text-red-700 dark:bg-red-900/20 dark:border-red-800/50 dark:text-red-400' :
          'bg-blue-50 border-blue-100 text-blue-700 dark:bg-blue-900/20 dark:border-blue-800/50 dark:text-blue-400'
        }`}>
          {pageNotice.message}
        </div>
      )}

      {/* List Card */}
      <div className="bg-background border border-border rounded-xl shadow-sm flex flex-col overflow-hidden">
        {/* Toolbar */}
        <div className="p-5 md:p-6 border-b border-border flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
          <div>
            <h3 className="text-lg font-bold text-foreground">文档管理</h3>
            <p className="text-sm text-muted-foreground mt-1">共 {total} 份文档，当前第 {currentPage} 页。</p>
          </div>

          <div className="flex w-full md:w-auto items-center gap-2">
            <div className="relative flex-1 md:w-64">
              <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                <svg className="h-4 w-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                </svg>
              </div>
              <input
                type="text"
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="搜索文档名称"
                className="block w-full pl-10 pr-3 py-2 bg-background border border-input rounded-md text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring transition-colors"
              />
            </div>
            <button 
              onClick={submitSearch}
              className="px-4 py-2 bg-background border border-border rounded-md text-sm font-medium text-muted-foreground hover:bg-secondary/80 transition-colors whitespace-nowrap"
            >
              搜索
            </button>
          </div>
        </div>

        {/* Stats Grid */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-px bg-border border-b border-border">
          <div className="bg-background p-4 flex flex-col justify-center items-center md:items-start md:pl-6">
            <span className="text-xs text-muted-foreground uppercase tracking-wider font-semibold mb-1">当前页文档</span>
            <span className="text-2xl font-bold text-foreground font-mono">{documents.length}</span>
          </div>
          <div className="bg-background p-4 flex flex-col justify-center items-center md:items-start md:pl-6">
            <span className="text-xs text-muted-foreground uppercase tracking-wider font-semibold mb-1">解析完成</span>
            <span className="text-2xl font-bold text-success font-mono">{visibleParseReadyCount}</span>
          </div>
          <div className="bg-background p-4 flex flex-col justify-center items-center md:items-start md:pl-6">
            <span className="text-xs text-muted-foreground uppercase tracking-wider font-semibold mb-1">策略确认</span>
            <span className="text-2xl font-bold text-primary font-mono">{visibleStrategyReadyCount}</span>
          </div>
          <div className="bg-background p-4 flex flex-col justify-center items-center md:items-start md:pl-6">
            <span className="text-xs text-muted-foreground uppercase tracking-wider font-semibold mb-1">索引可用</span>
            <span className="text-2xl font-bold text-blue-500 font-mono">{visibleIndexReadyCount}</span>
          </div>
        </div>

        {/* Table Content */}
        <div className="overflow-x-auto min-h-[400px]">
          {listLoading && !documents.length ? (
            <div className="flex flex-col items-center justify-center h-64 text-muted-foreground">
              <svg className="animate-spin h-8 w-8 text-primary mb-4" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              <p>正在加载文档列表...</p>
            </div>
          ) : !documents.length ? (
            <div className="flex flex-col items-center justify-center h-64 text-muted-foreground">
              <svg className="w-12 h-12 text-muted-foreground/30 mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M9 13h6m-3-3v6m5 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              <p>还没有文档，先上传一份资料开始体验。</p>
            </div>
          ) : (
            <table className="w-full text-left border-collapse min-w-[1000px]">
              <thead>
                <tr className="bg-secondary/30 border-b border-border">
                  <th className="px-6 py-4 text-xs font-semibold text-muted-foreground uppercase tracking-wider">文档</th>
                  <th className="px-6 py-4 text-xs font-semibold text-muted-foreground uppercase tracking-wider w-24">类型</th>
                  <th className="px-6 py-4 text-xs font-semibold text-muted-foreground uppercase tracking-wider w-24">大小</th>
                  <th className="px-6 py-4 text-xs font-semibold text-muted-foreground uppercase tracking-wider w-36">更新时间</th>
                  <th className="px-6 py-4 text-xs font-semibold text-muted-foreground uppercase tracking-wider w-24">解析</th>
                  <th className="px-6 py-4 text-xs font-semibold text-muted-foreground uppercase tracking-wider w-24">策略</th>
                  <th className="px-6 py-4 text-xs font-semibold text-muted-foreground uppercase tracking-wider w-24">索引</th>
                  <th className="px-6 py-4 text-xs font-semibold text-muted-foreground uppercase tracking-wider text-right w-40 whitespace-nowrap">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {documents.map((item: any) => (
                  <tr key={item.documentId} className="hover:bg-primary/5 transition-colors group">
                    <td className="px-6 py-4">
                      <button 
                        onClick={() => openDocumentDetail(item.documentId)}
                        className="text-left flex flex-col group/btn focus:outline-none"
                      >
                        <span className="text-sm font-semibold text-foreground group-hover/btn:text-primary transition-colors truncate max-w-[280px]">
                          {item.documentName}
                        </span>
                        <span className="text-xs text-muted-foreground mt-1 truncate max-w-[280px]">
                          {item.originalFileName}
                        </span>
                      </button>
                    </td>
                    <td className="px-6 py-4">
                      <span className="inline-flex px-2.5 py-1 rounded bg-secondary/50 text-secondary-foreground text-xs font-bold uppercase tracking-wider">
                        {item.fileTypeName || '-'}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-xs font-medium text-foreground font-mono">
                      {formatFileSize(item.fileSize)}
                    </td>
                    <td className="px-6 py-4 text-xs font-medium text-foreground font-mono">
                      {formatDateTime(item.editTime)}
                    </td>
                    <td className="px-6 py-4">
                      <AdminStatusBadge label={item.parseStatusName} code={item.parseStatus} type="parse" />
                    </td>
                    <td className="px-6 py-4">
                      <AdminStatusBadge label={item.strategyStatusName} code={item.strategyStatus} type="strategy" />
                    </td>
                    <td className="px-6 py-4">
                      <AdminStatusBadge label={item.indexStatusName} code={item.indexStatus} type="index" />
                    </td>
                    <td className="px-6 py-4 text-right whitespace-nowrap">
                      <div className="flex items-center justify-end gap-3 flex-nowrap min-w-max">
                        <button
                          onClick={() => openDocumentDetail(item.documentId)}
                          className="flex-shrink-0 px-3 py-1.5 rounded-md text-xs font-medium bg-primary/10 text-primary hover:bg-primary/20 transition-colors border border-primary/20 whitespace-nowrap min-w-[60px]"
                        >
                          详情
                        </button>
                        <button
                          disabled={!canDeleteDocument(item)}
                          title={buildDeleteTitle(item)}
                          onClick={() => deleteDocument(item)}
                          className="flex-shrink-0 px-3 py-1.5 rounded-md text-xs font-medium bg-destructive/10 text-destructive hover:bg-destructive/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed border border-destructive/20 whitespace-nowrap min-w-[60px]"
                        >
                          {isDeletingDocument(item.documentId) ? '删除中' : '删除'}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Pagination */}
        {documents.length > 0 && (
          <div className="px-6 py-4 border-t border-border bg-secondary/30 flex items-center justify-between">
            <button
              disabled={currentPage <= 1 || listLoading}
              onClick={() => changePage(currentPage - 1)}
              className="px-4 py-2 border border-border text-sm font-medium rounded-md text-foreground bg-background hover:bg-secondary/80 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              上一页
            </button>
            <div className="text-center">
              <p className="text-sm font-medium text-foreground">第 {currentPage} / {totalPages} 页</p>
              <p className="text-xs text-muted-foreground mt-1">共 {total} 条文档</p>
            </div>
            <button
              disabled={currentPage >= totalPages || listLoading}
              onClick={() => changePage(currentPage + 1)}
              className="px-4 py-2 border border-border text-sm font-medium rounded-md text-foreground bg-background hover:bg-secondary/80 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              下一页
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
