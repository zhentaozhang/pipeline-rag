import React from 'react';
import { Button } from '../../../components/ui/Button';
import { Card } from '../../../components/ui/Card';

interface AdminKnowledgeTopicViewProps {
  scopes: any[];
  topics: any[];
  onRefresh: () => void;
}

export const AdminKnowledgeTopicView: React.FC<AdminKnowledgeTopicViewProps> = ({ scopes, topics, onRefresh }) => {
  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h3 className="text-lg font-bold text-foreground">知识主题</h3>
          <p className="text-sm text-muted-foreground mt-1">在知识范围下定义更细粒度的主题单元，方便后续挂载具体的文档。</p>
        </div>
        <Button onClick={async () => {
          const scope = window.prompt('请输入所属范围编码 (scopeCode):');
          if (!scope) return;
          const name = window.prompt('请输入新主题名称:');
          if (!name) return;
          const code = window.prompt('请输入新主题编码 (如 topic_a):');
          if (!code) return;
          try {
            const m = await import('../../../lib/api');
            await m.manageApi.saveKnowledgeTopic({ 
              topicCode: code, 
              topicName: name,
              scopeCode: scope
            });
            onRefresh();
          } catch (e: any) {
            alert(e.message || '新建失败');
          }
        }}>
          新建主题
        </Button>
      </div>
      
      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="bg-secondary/30 border-b border-border">
                <th className="px-4 py-3 text-xs font-semibold text-muted-foreground uppercase">主题编码</th>
                <th className="px-4 py-3 text-xs font-semibold text-muted-foreground uppercase">主题名称</th>
                <th className="px-4 py-3 text-xs font-semibold text-muted-foreground uppercase">所属范围</th>
                <th className="px-4 py-3 text-xs font-semibold text-muted-foreground uppercase">描述</th>
                <th className="px-4 py-3 text-xs font-semibold text-muted-foreground uppercase">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {topics.map(topic => {
                const scope = scopes.find(s => s.scopeCode === topic.scopeCode);
                return (
                  <tr key={topic.topicCode} className="hover:bg-primary/5 transition-colors">
                    <td className="px-4 py-3 text-sm font-mono text-muted-foreground">{topic.topicCode}</td>
                    <td className="px-4 py-3 text-sm font-medium text-foreground">{topic.topicName}</td>
                    <td className="px-4 py-3 text-sm text-muted-foreground">
                      {scope ? scope.scopeName : topic.scopeCode}
                    </td>
                    <td className="px-4 py-3 text-sm text-muted-foreground max-w-xs truncate" title={topic.description}>
                      {topic.description || '-'}
                    </td>
                    <td className="px-4 py-3">
                      <button
                        onClick={async () => {
                          if (!window.confirm(`确定删除主题「${topic.topicName}」吗？`)) return;
                          try {
                            const m = await import('../../../lib/api');
                            await m.manageApi.deleteKnowledgeTopic({ topicCode: topic.topicCode });
                            onRefresh();
                          } catch (e: any) {
                            alert(e.message || '删除失败');
                          }
                        }}
                        className="text-destructive hover:text-destructive/80 text-sm transition-colors"
                      >
                        删除
                      </button>
                    </td>
                  </tr>
                );
              })}
              {topics.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground text-sm">
                    暂无知识主题数据
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
};
