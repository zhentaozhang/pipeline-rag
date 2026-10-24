import React, { useMemo, useState } from 'react';
import { manageApi } from '../../../lib/api';
import type { DocumentProfile, ManageDocument } from '../../../types/api';
import { Button } from '../../../components/ui/Button';
import { FilterBar, FilterSearch } from '../../../components/ui/FilterBar';
import { AdminPanel } from '../AdminPanel';
import { useAsyncData } from '../../../lib/useAsyncData';
import { useDebouncedValue } from '../useDebouncedValue';
import { loadFailure } from '../adminFormat';
import { ProfileDetail } from './ProfileDetail';
import { ProfileDocumentGrid } from './ProfileDocumentGrid';

/** 文档画像：先从最近 50 份文档里挑一份，再看它的画像详情 */
export const AdminKnowledgeProfileView: React.FC = () => {
  const [keyword, setKeyword] = useState('');
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const debounced = useDebouncedValue(keyword, 250).trim().toLowerCase();

  const { data: docs, loading, error, refetch } = useAsyncData<ManageDocument[]>(async () => {
    const response = await manageApi.queryDocumentPage({ pageNo: 1, pageSize: 50 });
    return response?.records ?? [];
  }, []);

  const { data: profile, loading: profileLoading, error: profileError, refetch: refetchProfile } = useAsyncData<DocumentProfile | null>(
    async () => (selectedDocId ? manageApi.queryDocumentProfile({ documentId: selectedDocId }) : null),
    [selectedDocId]
  );

  // 画像接口一次性只接一份文档，所以关键词过滤走客户端
  const filtered = useMemo(() => {
    const list = docs ?? [];
    if (!debounced) return list;
    return list.filter((doc) =>
      [doc.documentName, doc.documentId, doc.originalFileName].some((field) => String(field ?? '').toLowerCase().includes(debounced))
    );
  }, [docs, debounced]);

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h3 className="text-sm font-medium text-foreground">文档画像</h3>
        <p className="mt-1 text-xs text-muted-foreground">
          画像描述文档的结构与内容质量，系统据此决定回答方式；从这里可以抽查某份文档的画像是否正确。
        </p>
      </div>

      {selectedDocId ? (
        <AdminPanel
          title="画像详情"
          description="解析后的摘要、核心主题与能力标签。"
          actions={
            <Button size="sm" variant="outline" loading={profileLoading} onClick={() => refetchProfile()}>
              重新读取
            </Button>
          }
        >
          {profileError ? (
            <div className="flex flex-col items-start gap-2">
              <p className="text-xs text-destructive">{loadFailure(profileError, '文档画像')}</p>
              <Button size="sm" variant="outline" onClick={() => refetchProfile()}>
                重试
              </Button>
            </div>
          ) : profileLoading && !profile ? (
            <p className="text-xs text-muted-foreground">正在读取画像……</p>
          ) : profile ? (
            <ProfileDetail
              profile={profile}
              onBack={() => {
                setSelectedDocId(null);
              }}
            />
          ) : (
            <p className="text-xs text-muted-foreground">这份文档还没有画像。先完成解析，再重建画像。</p>
          )}
        </AdminPanel>
      ) : (
        <>
          <FilterBar
            actions={
              <Button size="sm" variant="ghost" loading={loading} onClick={() => refetch()}>
                刷新文档
              </Button>
            }
          >
            <FilterSearch
              label="筛选文档"
              value={keyword}
              onChange={setKeyword}
              placeholder="按文档名称或 ID 筛选（最近 50 份）"
            />
          </FilterBar>

          <ProfileDocumentGrid
            docs={filtered}
            loading={loading}
            error={error ? loadFailure(error, '文档列表') : ''}
            keyword={debounced}
            onRetry={() => refetch()}
            onSelect={setSelectedDocId}
          />
        </>
      )}
    </div>
  );
};
