import React, { useState, useEffect } from 'react';
import { Button } from '../../../components/ui/Button';
import { Card } from '../../../components/ui/Card';
import { manageApi, APIError } from '../../../lib/api';
import type { TopicDocument } from '../../../types/api';
import type { KnowledgeScope, KnowledgeTopic, ManageDocument } from '../../../types/api';
import { formatDateTime } from '../../../lib/manageFormat';
import { errorMessage } from '../../../lib/utils';

interface AdminKnowledgeRelationViewProps {
  scopes: KnowledgeScope[];
  topics: KnowledgeTopic[];
  onRefresh: () => void;
}

export const AdminKnowledgeRelationView: React.FC<AdminKnowledgeRelationViewProps> = ({ scopes, topics, onRefresh }) => {
  const [selectedScope, setSelectedScope] = useState('');
  const [selectedTopic, setSelectedTopic] = useState('');
  const [loading, setLoading] = useState(false);
  const [relations, setRelations] = useState<TopicDocument[]>([]);
  const [errorMsg, setErrorMsg] = useState('');
  const [showBindDialog, setShowBindDialog] = useState(false);
  const [searchDocKeyword, setSearchDocKeyword] = useState('');
  const [searchDocs, setSearchDocs] = useState<ManageDocument[]>([]);
  const [searchDocLoading, setSearchDocLoading] = useState(false);
  const [bindScore, setBindScore] = useState('1.0');
  const [bindReason, setBindReason] = useState('');

  const filteredTopics = selectedScope
    ? topics.filter(t => t.scopeCode === selectedScope)
    : topics;

  const loadRelations = async (topicCode: string) => {
    setLoading(true);
    setErrorMsg('');
    try {
      const data = await manageApi.listTopicDocuments({ topicCode });
      setRelations(data);
    } catch (error) {
      setErrorMsg(error instanceof APIError ? error.message : '查询关联文档失败');
      setRelations([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (selectedTopic) {
      loadRelations(selectedTopic);
    } else {
      setRelations([]);
    }
  }, [selectedTopic]);

  const handleRemove = async (docId: string) => {
    if (!window.confirm('确定解除该文档与主题的关联吗？')) return;
    try {
      await manageApi.removeTopicDocumentRelation({ topicCode: selectedTopic, documentId: docId });
      loadRelations(selectedTopic);
      onRefresh();
    } catch (e) {
      alert(errorMessage(e, '解除关联失败'));
    }
  };

  const handleSearchDoc = async () => {
    if (!searchDocKeyword.trim()) return;
    setSearchDocLoading(true);
    try {
      const data = await manageApi.queryDocumentPage({ pageNo: 1, pageSize: 20, keyword: searchDocKeyword.trim() });
      setSearchDocs(data?.records || []);
    } catch {
      setSearchDocs([]);
    } finally {
      setSearchDocLoading(false);
    }
  };

  const handleBind = async (docId: string) => {
    try {
      await manageApi.saveTopicDocumentRelation({
        topicCode: selectedTopic,
        documentId: docId,
        relationScore: parseFloat(bindScore) || 1.0,
        relationSource: 'manual',
        reason: bindReason || '',
      });
      setShowBindDialog(false);
      setBindScore('1.0');
      setBindReason('');
      setSearchDocKeyword('');
      setSearchDocs([]);
      loadRelations(selectedTopic);
      onRefresh();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : '关联失败');
    }
  };

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h3 className="text-lg font-bold text-foreground">主题文档关联</h3>
          <p className="text-sm text-muted-foreground mt-1">将具体的文档挂载到对应的知识主题下，为自动问答提供明确的检索范围。</p>
        </div>
      </div>

      {/* 选择器 */}
      <div className="mb-4 flex flex-wrap gap-3 items-end">
        <div>
          <label className="text-xs text-muted-foreground block mb-1">知识范围</label>
          <select
            value={selectedScope}
            onChange={e => { setSelectedScope(e.target.value); setSelectedTopic(''); }}
            className="px-3 py-2 border border-input rounded-md bg-background text-foreground text-sm"
          >
            <option value="">全部范围</option>
            {scopes.map(s => (
              <option key={s.scopeCode} value={s.scopeCode}>{s.scopeName}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-muted-foreground block mb-1">知识主题</label>
          <select
            value={selectedTopic}
            onChange={e => setSelectedTopic(e.target.value)}
            className="px-3 py-2 border border-input rounded-md bg-background text-foreground text-sm"
          >
            <option value="">请选择主题</option>
            {filteredTopics.map(t => (
              <option key={t.topicCode} value={t.topicCode}>{t.topicName} ({t.topicCode})</option>
            ))}
          </select>
        </div>
        {selectedTopic && (
          <Button size="sm" onClick={() => setShowBindDialog(true)}>添加关联</Button>
        )}
      </div>

      {errorMsg && <p className="text-sm text-destructive mb-3">{errorMsg}</p>}

      {/* 绑定对话框 */}
      {showBindDialog && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center" onClick={() => setShowBindDialog(false)}>
          <div className="bg-background rounded-xl border border-border shadow-xl w-full max-w-lg max-h-[80vh] overflow-y-auto p-6" onClick={e => e.stopPropagation()}>
            <h4 className="text-lg font-bold mb-4">添加文档关联</h4>
            <div className="flex gap-2 mb-4">
              <input
                type="text"
                placeholder="搜索文档名称..."
                value={searchDocKeyword}
                onChange={e => setSearchDocKeyword(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleSearchDoc()}
                className="flex-1 px-3 py-2 border border-input rounded-md bg-background text-foreground text-sm"
              />
              <Button size="sm" onClick={handleSearchDoc} disabled={searchDocLoading}>搜索</Button>
            </div>

            {searchDocLoading ? (
              <div className="py-8 text-center text-muted-foreground text-sm">搜索中...</div>
            ) : searchDocs.length > 0 ? (
              <div className="space-y-2 mb-4 max-h-60 overflow-y-auto">
                {searchDocs.map((doc) => {
                  const alreadyBound = relations.some(r => r.docId === doc.documentId || r.documentId === doc.documentId);
                  return (
                    <div key={doc.documentId} className="flex items-center justify-between p-3 bg-secondary/20 rounded-lg border border-border/50">
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium truncate">{doc.documentName}</p>
                        <p className="text-xs text-muted-foreground truncate">{doc.documentId}</p>
                      </div>
                      {alreadyBound ? (
                        <span className="text-xs text-muted-foreground whitespace-nowrap ml-2">已关联</span>
                      ) : (
                        <Button size="sm" variant="outline" onClick={() => handleBind(doc.documentId)}>关联</Button>
                      )}
                    </div>
                  );
                })}
              </div>
            ) : searchDocKeyword ? (
              <div className="py-4 text-center text-muted-foreground text-sm">未找到文档</div>
            ) : null}

            <div className="flex gap-3 mb-4">
              <div className="flex-1">
                <label className="text-xs text-muted-foreground block mb-1">关联分数</label>
                <input
                  type="number"
                  step="0.1"
                  min="0"
                  max="10"
                  value={bindScore}
                  onChange={e => setBindScore(e.target.value)}
                  className="w-full px-3 py-2 border border-input rounded-md bg-background text-foreground text-sm"
                />
              </div>
              <div className="flex-[2]">
                <label className="text-xs text-muted-foreground block mb-1">关联理由</label>
                <input
                  type="text"
                  placeholder="可选"
                  value={bindReason}
                  onChange={e => setBindReason(e.target.value)}
                  className="w-full px-3 py-2 border border-input rounded-md bg-background text-foreground text-sm"
                />
              </div>
            </div>

            <div className="flex justify-end gap-2">
              <Button variant="outline" size="sm" onClick={() => setShowBindDialog(false)}>取消</Button>
            </div>
          </div>
        </div>
      )}

      {/* 关联列表 */}
      <Card className="min-h-[200px] border-border shadow-none overflow-hidden">
        {!selectedTopic ? (
          <div className="flex items-center justify-center h-[200px] text-muted-foreground text-sm">
            请先选择知识主题
          </div>
        ) : loading ? (
          <div className="flex items-center justify-center h-[200px] text-muted-foreground">加载中...</div>
        ) : relations.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-[200px] text-center text-muted-foreground">
            <p className="text-sm mb-2">当前主题下暂无关联文档</p>
            <Button size="sm" variant="outline" onClick={() => setShowBindDialog(true)}>添加关联</Button>
          </div>
        ) : (
          <div className="divide-y divide-border/50">
            {relations.map((rel, idx) => (
              <div key={idx} className="p-4 flex items-center justify-between hover:bg-secondary/20 transition-colors">
                <div className="flex flex-col">
                  <span className="font-bold text-foreground text-sm mb-1">{rel.documentName || rel.documentId}</span>
                  <span className="text-xs text-muted-foreground">
                    关联分数: {rel.relationScore} | 来源: {rel.relationSource}
                    {rel.reason ? ` | 理由: ${rel.reason}` : ''}
                  </span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-muted-foreground hidden sm:inline">
                    {rel.createTime ? formatDateTime(rel.createTime) : ''}
                  </span>
                  <button
                    onClick={() => handleRemove(rel.docId || rel.documentId || '')}
                    className="text-destructive hover:text-destructive/80 text-xs transition-colors"
                  >
                    解除
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
};
