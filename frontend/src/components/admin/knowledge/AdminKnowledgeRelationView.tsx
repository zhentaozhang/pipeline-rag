import React, { useState } from 'react';
import { Link2 } from 'lucide-react';
import { manageApi } from '../../../lib/api';
import type { KnowledgeScope, KnowledgeTopic, TopicDocument } from '../../../types/api';
import { Button } from '../../../components/ui/Button';
import { FilterBar, FilterField, FilterSelect } from '../../../components/ui/FilterBar';
import { useAsyncData } from '../../../lib/useAsyncData';
import { loadFailure } from '../adminFormat';
import { RelationBindPanel } from './RelationBindPanel';
import { RelationTable } from './RelationTable';

interface Props {
  scopes: KnowledgeScope[];
  topics: KnowledgeTopic[];
  onRefresh: () => void;
}

/** 主题文档关联：先选主题，再看它绑了哪些文档，或者新绑一个 */
export const AdminKnowledgeRelationView: React.FC<Props> = ({ scopes, topics, onRefresh }) => {
  const [scopeCode, setScopeCode] = useState('');
  const [topicCode, setTopicCode] = useState('');
  const [binding, setBinding] = useState(false);

  const filteredTopics = scopeCode ? topics.filter((topic) => topic.scopeCode === scopeCode) : topics;

  const { data, loading, error, refetch } = useAsyncData<TopicDocument[]>(
    async () => {
      if (!topicCode) return [];
      const rows = await manageApi.listTopicDocuments({ topicCode });
      return Array.isArray(rows) ? rows : [];
    },
    [topicCode]
  );

  const rows = data ?? [];
  const boundIds = rows.map((row) => String(row.docId ?? row.documentId ?? '')).filter(Boolean);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-medium text-foreground">主题文档关联</h3>
          <p className="mt-1 text-xs text-muted-foreground">
            把具体文档挂到主题下，自动问答就有了明确的检索范围。
          </p>
        </div>
        {topicCode ? (
          <Button size="sm" variant="outline" onClick={() => setBinding((prev) => !prev)}>
            <Link2 size={13} aria-hidden="true" />
            添加关联
          </Button>
        ) : null}
      </div>

      <FilterBar>
        <FilterSelect
          label="知识范围"
          value={scopeCode}
          onChange={(value) => {
            setScopeCode(value);
            setTopicCode('');
            setBinding(false);
          }}
          options={[{ value: '', label: '全部范围' }, ...scopes.map((scope) => ({ value: scope.scopeCode, label: scope.scopeName }))]}
        />
        <FilterField label="知识主题">
          <select
            value={topicCode}
            onChange={(event) => {
              setTopicCode(event.target.value);
              setBinding(false);
            }}
            className="h-9 w-full rounded-md border border-input bg-background px-2.5 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <option value="">请选择主题</option>
            {filteredTopics.map((topic) => (
              <option key={topic.topicCode} value={topic.topicCode}>
                {topic.topicName}（{topic.topicCode}）
              </option>
            ))}
          </select>
        </FilterField>
      </FilterBar>

      {!topicCode ? (
        <div className="rounded-xl border border-dashed border-border px-5 py-10 text-center">
          <p className="text-sm font-medium text-foreground">先选一个知识主题</p>
          <p className="mt-1 text-xs text-muted-foreground">选好主题后，这里会列出它已绑定的文档。</p>
        </div>
      ) : (
        <>
          {binding ? (
            <RelationBindPanel
              topicCode={topicCode}
              boundIds={boundIds}
              onBound={() => {
                refetch();
                onRefresh();
              }}
              onClose={() => setBinding(false)}
            />
          ) : null}

          <RelationTable
            rows={rows}
            loading={loading}
            error={error ? loadFailure(error, '主题关联文档') : ''}
            onRetry={() => refetch()}
            onChanged={() => {
              refetch();
              onRefresh();
            }}
            onAdd={() => setBinding(true)}
          />
        </>
      )}
    </div>
  );
};
