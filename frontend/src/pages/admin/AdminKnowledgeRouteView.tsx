import React from 'react';
import { RefreshCw, Sparkles } from 'lucide-react';
import { manageApi } from '../../lib/api';
import type { KnowledgeScope, KnowledgeTopic } from '../../types/api';
import { Button } from '../../components/ui/Button';
import { ConfirmDialog } from '../../components/ui/ConfirmDialog';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../components/ui/Tabs';
import { AdminPageHeader } from '../../components/admin/AdminPageHeader';
import { AdminPanel } from '../../components/admin/AdminPanel';
import { AdminStatGrid } from '../../components/admin/AdminStatGrid';
import { ScopeGrid } from '../../components/admin/knowledge/ScopeGrid';
import { AdminKnowledgeTopicView } from '../../components/admin/knowledge/AdminKnowledgeTopicView';
import { AdminKnowledgeProfileView } from '../../components/admin/knowledge/AdminKnowledgeProfileView';
import { AdminKnowledgeRelationView } from '../../components/admin/knowledge/AdminKnowledgeRelationView';
import { useAsyncData } from '../../lib/useAsyncData';
import { useUrlFilters } from '../../lib/useUrlFilters';
import { toast } from '../../lib/toast';
import { loadFailure, actionFailure } from '../../components/admin/adminFormat';
import { useState } from 'react';

const TAB_LIST = [
  { key: 'scope', label: '知识范围', step: '01', hint: '系统划定的大领域划分' },
  { key: 'topic', label: '知识主题', step: '02', hint: '领域下的可回答单元' },
  { key: 'profile', label: '文档画像', step: '03', hint: '文档类型与能力分析' },
  { key: 'relation', label: '主题文档关联', step: '04', hint: '主题与文档的绑定关系' },
];
const FILTER_DEFAULTS = { tab: 'scope' };
// 首屏没有数据时先占位，避免统计卡整块消失造成布局跳动
const PLACEHOLDER_STATS = [
  { label: '知识范围', value: '—', hint: '领域划分数量' },
  { label: '知识主题', value: '—', hint: '可回答单元总数' },
  { label: '文档画像', value: '—', hint: '已接入的文档数' },
  { label: '有效关联', value: '—', hint: '主题文档绑定数' },
];

interface RouteOverview {
  scopes: KnowledgeScope[];
  topics: KnowledgeTopic[];
  documentTotal: number;
  relationCount: number;
}

/** 路由配置：范围 → 主题 → 画像 → 关联，四步把问答的候选范围收窄 */
export const AdminKnowledgeRouteView: React.FC = () => {
  const [filters, updateFilters] = useUrlFilters(FILTER_DEFAULTS);
  const [rebuilding, setRebuilding] = useState(false);
  const [confirmRebuild, setConfirmRebuild] = useState(false);

  const { data, loading, error, refetch } = useAsyncData<RouteOverview>(async () => {
    const [scopeRows, topicRows, docPage] = await Promise.all([
      manageApi.listKnowledgeScopes(),
      manageApi.listKnowledgeTopics(),
      manageApi.queryDocumentPage({ pageNo: 1, pageSize: 1 }),
    ]);
    const scopes = Array.isArray(scopeRows) ? scopeRows : [];
    const topics = Array.isArray(topicRows) ? topicRows : [];
    // 关联总数要把每个主题都查一遍，主题多时比较慢，所以放在同一批里一次拿完
    const relations = await Promise.all(
      topics.map((topic) => manageApi.listTopicDocuments({ topicCode: topic.topicCode }).catch(() => []))
    );
    const relationCount = relations.reduce((sum, list) => sum + (Array.isArray(list) ? list.length : 0), 0);
    return { scopes, topics, documentTotal: Number(docPage?.total ?? 0), relationCount };
  }, []);

  const scopes = data?.scopes ?? [];
  const topics = data?.topics ?? [];
  const overview = data
    ? [
        { label: '知识范围', value: String(scopes.length), hint: '领域划分数量' },
        { label: '知识主题', value: String(topics.length), hint: '可回答单元总数' },
        { label: '文档画像', value: String(data.documentTotal), hint: '已接入的文档数' },
        { label: '有效关联', value: String(data.relationCount), hint: '主题文档绑定数' },
      ]
    : [];

  const rebuildAll = async () => {
    setConfirmRebuild(false);
    setRebuilding(true);
    try {
      await manageApi.batchRegenerateDocumentProfiles({ documentIds: [] });
      toast({
        title: '已提交批量重建画像',
        description: '后台会逐份重建，完成情况可以在「文档画像」里抽查。',
        variant: 'success',
      });
      refetch();
    } catch (rebuildError) {
      toast({ title: '批量重建失败', description: actionFailure(rebuildError, '批量重建画像', '请确认后端任务队列可用，然后重试。'), variant: 'error' });
    } finally {
      setRebuilding(false);
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-4">
      <AdminPageHeader
        eyebrow="路由配置"
        title="路由配置"
        description="按 范围 → 主题 → 画像 → 关联 的顺序配置，自动问答才能稳定地在正确的文档池里预选。"
        actions={
          <>
            <Button variant="outline" loading={loading} onClick={() => refetch()}>
              <RefreshCw size={14} aria-hidden="true" />
              刷新数据
            </Button>
            <Button loading={rebuilding} onClick={() => setConfirmRebuild(true)}>
              <Sparkles size={14} aria-hidden="true" />
              批量重建画像
            </Button>
          </>
        }
      />

      {error ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-destructive/30 bg-card p-3">
          <p className="text-xs text-destructive">{loadFailure(error, '路由配置数据')}</p>
          <Button size="sm" variant="outline" onClick={() => refetch()}>
            重试
          </Button>
        </div>
      ) : null}

      <AdminStatGrid stats={overview.length > 0 ? overview : PLACEHOLDER_STATS} columns={4} />

      <Tabs value={filters.tab} onValueChange={(tab) => updateFilters({ tab })} className="flex flex-col gap-4">
        <TabsList>
          {TAB_LIST.map((tab) => (
            <TabsTrigger key={tab.key} value={tab.key} step={tab.step} hint={tab.hint}>
              {tab.label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="scope">
          <AdminPanel title="知识范围" description="先把大范围定清楚，自动问答才会在正确的文档池里预选。">
            <ScopeGrid scopes={scopes} topics={topics} onRefresh={() => refetch()} />
          </AdminPanel>
        </TabsContent>
        <TabsContent value="topic">
          <AdminPanel title="知识主题" description="主题是范围下的可回答单元，问答会尽量收敛到某个主题。">
            <AdminKnowledgeTopicView scopes={scopes} topics={topics} onRefresh={() => refetch()} />
          </AdminPanel>
        </TabsContent>
        <TabsContent value="profile">
          <AdminPanel title="文档画像" description="画像决定系统怎么用这份文档回答问题。">
            <AdminKnowledgeProfileView />
          </AdminPanel>
        </TabsContent>
        <TabsContent value="relation">
          <AdminPanel title="主题文档关联" description="主题和文档绑定后，问答才有明确的检索范围。">
            <AdminKnowledgeRelationView scopes={scopes} topics={topics} onRefresh={() => refetch()} />
          </AdminPanel>
        </TabsContent>
      </Tabs>

      <ConfirmDialog
        open={confirmRebuild}
        title="重建全部文档画像？"
        description="会为所有文档重新排队画像任务，文档较多时需要几分钟，期间问答仍可正常进行。"
        confirmLabel="开始重建"
        onConfirm={rebuildAll}
        onCancel={() => setConfirmRebuild(false)}
      />
    </div>
  );
};
