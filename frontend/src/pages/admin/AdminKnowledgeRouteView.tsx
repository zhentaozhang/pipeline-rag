import React, { useState, useEffect } from 'react';
import { manageApi } from '../../lib/api';
import type { KnowledgeScope, KnowledgeTopic } from '../../types/api';
import { Button } from '../../components/ui/Button';
import { Card, CardContent } from '../../components/ui/Card';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../../components/ui/Tabs';
import { AdminKnowledgeTopicView } from '../../components/admin/knowledge/AdminKnowledgeTopicView';
import { AdminKnowledgeProfileView } from '../../components/admin/knowledge/AdminKnowledgeProfileView';
import { AdminKnowledgeRelationView } from '../../components/admin/knowledge/AdminKnowledgeRelationView';
import { errorMessage } from '../../lib/utils';

const TAB_LIST = [
  { key: 'scope', label: '知识范围', step: '01', hint: '系统划定的大领域划分' },
  { key: 'topic', label: '知识主题', step: '02', hint: '领域下的可回答单元' },
  { key: 'profile', label: '文档画像', step: '03', hint: '文档类型与能力分析' },
  { key: 'relation', label: '主题文档关联', step: '04', hint: '主题与文档的绑定关系' }
];

export const AdminKnowledgeRouteView: React.FC = () => {
  const [activeTab, setActiveTab] = useState('scope');
  const [loading, setLoading] = useState(false);
  const [scopes, setScopes] = useState<KnowledgeScope[]>([]);
  const [topics, setTopics] = useState<KnowledgeTopic[]>([]);
  const [documentTotal, setDocumentTotal] = useState<number | null>(null);
  const [relationCount, setRelationCount] = useState<number | null>(null);

  const loadData = async () => {
    setLoading(true);
    try {
      const [scopesData, topicsData, docPageData] = await Promise.all([
        manageApi.listKnowledgeScopes(),
        manageApi.listKnowledgeTopics(),
        manageApi.queryDocumentPage({pageNo: 1, pageSize: 1})
      ]);
      const scopesList = Array.isArray(scopesData) ? scopesData : [];
      const topicsList = Array.isArray(topicsData) ? topicsData : [];
      setScopes(scopesList);
      setTopics(topicsList);
      setDocumentTotal(docPageData?.total ?? 0);

      if (topicsList.length > 0) {
        const counts = await Promise.all(
          topicsList.map(t => manageApi.listTopicDocuments({topicCode: t.topicCode}))
        );
        setRelationCount(counts.reduce((sum, list) => sum + (Array.isArray(list) ? list.length : 0), 0));
      } else {
        setRelationCount(0);
      }
    } catch (error) {
      console.error('加载知识路由数据失败', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void (async () => {
      await loadData();
    })();
  }, []);

  return (
    <div className="p-6 md:p-8 flex flex-col gap-6 max-w-7xl mx-auto w-full h-full">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 border-b pb-6">
        <div>
          <span className="text-xs font-bold text-primary uppercase tracking-wider mb-1 block">
            路由配置
          </span>
          <h2 className="text-2xl font-bold text-foreground">路由配置</h2>
          <p className="text-sm text-muted-foreground mt-2 max-w-2xl">
            按 范围 → 主题 → 画像 → 关联 的顺序逐步配置，构建自动知识问答的候选预选体系。
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Button variant="outline" onClick={loadData} disabled={loading}>
            {loading ? '刷新中...' : '刷新数据'}
          </Button>
          <Button disabled={loading} onClick={async () => {
            if (!window.confirm('确定要批量重建画像任务吗？')) return;
            try {
              await manageApi.batchRegenerateDocumentProfiles({ documentIds: [] });
              alert('批量重建任务已发起');
            } catch (e) {
              alert(errorMessage(e, '发起失败'));
            }
          }}>
            批量重建画像
          </Button>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-5">
            <span className="text-sm text-muted-foreground block mb-1">知识范围</span>
            <strong className="text-2xl font-bold font-mono">{scopes.length}</strong>
            <p className="text-xs text-muted-foreground mt-1">领域划分数量</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <span className="text-sm text-muted-foreground block mb-1">知识主题</span>
            <strong className="text-2xl font-bold font-mono">{topics.length}</strong>
            <p className="text-xs text-muted-foreground mt-1">可回答单元总数</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <span className="text-sm text-muted-foreground block mb-1">文档画像</span>
            <strong className="text-2xl font-bold font-mono">{documentTotal ?? '-'}</strong>
            <p className="text-xs text-muted-foreground mt-1">已分析的文档数</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <span className="text-sm text-muted-foreground block mb-1">有效关联</span>
            <strong className="text-2xl font-bold font-mono">{relationCount ?? '-'}</strong>
            <p className="text-xs text-muted-foreground mt-1">主题文档绑定数</p>
          </CardContent>
        </Card>
      </div>

      <div className="w-full h-px bg-border my-2"></div>

      <Tabs value={activeTab} onValueChange={setActiveTab} className="flex-1 flex flex-col min-h-[400px]">
        {/* Tabs */}
        <TabsList>
          {TAB_LIST.map(tab => (
            <TabsTrigger
              key={tab.key}
              value={tab.key}
              step={tab.step}
              hint={tab.hint}
            >
              {tab.label}
            </TabsTrigger>
          ))}
        </TabsList>

        {/* Tab Content Area */}
        <TabsContent value="scope" className="flex-1">
          <Card className="p-6 border-none shadow-none bg-transparent">
            <div className="flex items-center justify-between mb-6">
              <div>
                <h3 className="text-lg font-bold text-foreground">知识范围</h3>
                <p className="text-sm text-muted-foreground mt-1">先把大范围定清楚，自动知识问答才能稳定地在正确文档池里预选。</p>
              </div>
              <Button onClick={async () => {
                const name = window.prompt('请输入新范围名称:');
                if (!name) return;
                const code = window.prompt('请输入新范围编码 (如 domain_a):');
                if (!code) return;
                try {
                    await manageApi.saveKnowledgeScope({ scopeCode: code, scopeName: name });
                    alert('新建成功');
                    loadData();
                } catch (e) {
                    alert(errorMessage(e, '新建失败'));
                }
              }}>新建范围</Button>
            </div>
            
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {scopes.map(item => (
                <Card key={item.scopeCode} className="p-4 bg-secondary/30 hover:border-primary/50 cursor-pointer transition-colors shadow-none">
                  <h4 className="font-bold text-foreground mb-1">{item.scopeName}</h4>
                  <p className="text-xs text-muted-foreground mb-3">{item.scopeCode}</p>
                  <p className="text-sm text-muted-foreground line-clamp-2 mb-4 h-10">
                    {item.description || '暂无描述'}
                  </p>
                  <div className="flex items-center justify-between text-xs text-muted-foreground border-t border-border pt-3">
                    <span>主题数: {topics.filter(t => t.scopeCode === item.scopeCode).length}</span>
                    <button
                      onClick={async (e) => {
                        e.stopPropagation();
                        if (!window.confirm(`确定删除知识范围「${item.scopeName}」吗？`)) return;
                        try {
                          await manageApi.deleteKnowledgeScope({ scopeCode: item.scopeCode });
                          loadData();
                        } catch (e) {
                          alert(errorMessage(e, '删除失败'));
                        }
                      }}
                      className="text-destructive hover:text-destructive/80 transition-colors"
                    >
                      删除
                    </button>
                  </div>
                </Card>
              ))}
              {scopes.length === 0 && !loading && (
                <div className="col-span-full py-12 text-center text-muted-foreground">
                  没有知识范围数据
                </div>
              )}
            </div>
          </Card>
        </TabsContent>

        <TabsContent value="topic" className="flex-1"><AdminKnowledgeTopicView scopes={scopes} topics={topics} onRefresh={loadData} /></TabsContent>
        <TabsContent value="profile" className="flex-1"><AdminKnowledgeProfileView /></TabsContent>
        <TabsContent value="relation" className="flex-1"><AdminKnowledgeRelationView scopes={scopes} topics={topics} onRefresh={loadData} /></TabsContent>
      </Tabs>
    </div>
  );
};
