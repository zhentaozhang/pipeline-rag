import React, { useState, useEffect, useMemo } from 'react';
import { Card } from '../../../components/ui/Card';
import { manageApi, APIError } from '../../../lib/api';

const QUALITY_LABELS = ['未知', '低', '中', '高'];

function ProfileDetailView({ profile, onBack }: { profile: any; onBack: () => void }) {
  return (
    <div className="flex flex-col gap-6">
      <button onClick={onBack} className="text-sm text-primary hover:underline self-start">
        &larr; 返回列表
      </button>
      <div className="flex justify-between items-start border-b border-border/50 pb-4">
        <div>
          <h4 className="text-xl font-bold text-foreground">{profile.documentName || '未知文档'}</h4>
          <p className="text-sm text-muted-foreground mt-1">Doc ID: {profile.documentId}</p>
        </div>
        <div className="px-3 py-1 bg-primary/10 text-primary rounded-full text-xs font-medium">
          内容质量: {QUALITY_LABELS[profile.contentQualityLevel] || '未知'}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="space-y-4">
          <div>
            <h5 className="text-sm font-bold text-foreground mb-2">文档摘要</h5>
            <p className="text-sm text-muted-foreground bg-secondary/20 p-4 rounded-lg leading-relaxed">
              {profile.summary || '暂无摘要'}
            </p>
          </div>
          <div>
            <h5 className="text-sm font-bold text-foreground mb-2">核心主题</h5>
            <div className="flex flex-wrap gap-2">
              {(profile.coreTopics ? JSON.parse(profile.coreTopics) : []).map((topic: string, i: number) => (
                <span key={i} className="px-2 py-1 bg-secondary text-foreground text-xs rounded border border-border/50">
                  {topic}
                </span>
              ))}
            </div>
          </div>
        </div>

        <div className="space-y-4">
          <div>
            <h5 className="text-sm font-bold text-foreground mb-2">能力标签</h5>
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between p-3 bg-secondary/10 rounded-lg border border-border/50">
                <span className="text-sm text-foreground">结构清晰度</span>
                <span className="text-xs font-mono">{QUALITY_LABELS[profile.structureLevel] || '未知'}</span>
              </div>
              <div className="flex items-center justify-between p-3 bg-secondary/10 rounded-lg border border-border/50">
                <span className="text-sm text-foreground">图谱友好</span>
                <span className={`text-xs px-2 py-0.5 rounded ${profile.graphFriendly ? 'bg-emerald-500/10 text-emerald-500' : 'bg-secondary text-muted-foreground'}`}>
                  {profile.graphFriendly ? '是' : '否'}
                </span>
              </div>
              <div className="flex items-center justify-between p-3 bg-secondary/10 rounded-lg border border-border/50">
                <span className="text-sm text-foreground">支持条目检索</span>
                <span className={`text-xs px-2 py-0.5 rounded ${profile.supportsItemLookup ? 'bg-emerald-500/10 text-emerald-500' : 'bg-secondary text-muted-foreground'}`}>
                  {profile.supportsItemLookup ? '是' : '否'}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export const AdminKnowledgeProfileView: React.FC = () => {
  const [keyword, setKeyword] = useState('');
  const [docs, setDocs] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [profile, setProfile] = useState<any>(null);
  const [errorMsg, setErrorMsg] = useState('');

  const loadDocs = async () => {
    setLoading(true);
    try {
      const data = await manageApi.queryDocumentPage({ pageNo: 1, pageSize: 50 });
      setDocs(data?.records || []);
    } catch (e) {
      setErrorMsg('加载文档列表失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadDocs(); }, []);

  const filteredDocs = useMemo(() => {
    if (!keyword.trim()) return docs;
    const q = keyword.trim().toLowerCase();
    return docs.filter((d: any) =>
      (d.documentName || '').toLowerCase().includes(q) ||
      (d.documentId || '').toLowerCase().includes(q) ||
      (d.originalFileName || '').toLowerCase().includes(q)
    );
  }, [docs, keyword]);

  const handleSelectDoc = async (docId: string) => {
    setSelectedDocId(docId);
    setProfile(null);
    try {
      const data = await manageApi.queryDocumentProfile({ documentId: docId });
      setProfile(data);
    } catch (e) {
      setErrorMsg(e instanceof APIError ? e.message : '查询画像失败');
    }
  };

  if (selectedDocId && profile) {
    return (
      <div className="p-6">
        <div className="mb-6">
          <h3 className="text-lg font-bold text-foreground">文档画像</h3>
          <p className="text-sm text-muted-foreground mt-1">文档类型与能力分析。</p>
        </div>
        <Card className="p-6 border-border shadow-none">
          <ProfileDetailView profile={profile} onBack={() => { setSelectedDocId(null); setProfile(null); setErrorMsg(''); }} />
        </Card>
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h3 className="text-lg font-bold text-foreground">文档画像</h3>
          <p className="text-sm text-muted-foreground mt-1">分析文档的能力属性，系统会根据画像自动匹配回答模式。</p>
        </div>
      </div>

      <div className="mb-4">
        <input
          type="text"
          placeholder="筛选文档名称..."
          value={keyword}
          onChange={e => setKeyword(e.target.value)}
          className="w-full max-w-sm px-3 py-2 border border-input rounded-md bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
        />
      </div>

      {loading ? (
        <div className="flex items-center justify-center h-[300px] text-muted-foreground">加载中...</div>
      ) : errorMsg && docs.length === 0 ? (
        <div className="flex items-center justify-center h-[300px] text-destructive">{errorMsg}</div>
      ) : filteredDocs.length === 0 ? (
        <div className="flex items-center justify-center h-[300px] text-muted-foreground">
          {keyword ? '没有匹配的文档' : '暂无文档数据'}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredDocs.map((doc: any) => {
            const isComplete = doc.indexStatus === 3;
            return (
              <Card
                key={doc.documentId}
                className="p-4 bg-secondary/30 hover:border-primary/50 cursor-pointer transition-colors shadow-none"
                onClick={() => handleSelectDoc(doc.documentId)}
              >
                <h4 className="font-bold text-foreground mb-1 truncate">{doc.documentName}</h4>
                <p className="text-xs text-muted-foreground mb-3 truncate">{doc.documentId}</p>
                <div className="flex items-center gap-2 text-xs mb-3">
                  {!isComplete && (
                    <span className="px-2 py-0.5 bg-amber-500/10 text-amber-600 rounded">
                      画像未完成
                    </span>
                  )}
                  {doc.knowledgeScopeName && (
                    <span className="px-2 py-0.5 bg-secondary text-muted-foreground rounded">
                      {doc.knowledgeScopeName}
                    </span>
                  )}
                </div>
                <div className="flex items-center justify-between text-xs text-muted-foreground border-t border-border pt-3">
                  <span>解析: {doc.parseStatusName || '-'}</span>
                  <span>索引: {doc.indexStatusName || '-'}</span>
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
};
