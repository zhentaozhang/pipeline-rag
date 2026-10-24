import React, { useState } from 'react';
import { Link2 } from 'lucide-react';
import { manageApi } from '../../../lib/api';
import type { ManageDocument } from '../../../types/api';
import { Button } from '../../../components/ui/Button';
import { Field, Input } from '../../../components/ui/Field';
import { Skeleton } from '../../../components/ui/Skeleton';
import { toast } from '../../../lib/toast';
import { useAsyncData } from '../../../lib/useAsyncData';
import { useDebouncedValue } from '../useDebouncedValue';
import { actionFailure, loadFailure } from '../adminFormat';

interface Props {
  topicCode: string;
  /** 已绑定的文档 ID，用来把搜索结果里的重复项标成「已关联」 */
  boundIds: string[];
  onBound: () => void;
  onClose: () => void;
}

/** 绑定文档：按名称搜文档，选中后写入主题-文档关系 */
export const RelationBindPanel: React.FC<Props> = ({ topicCode, boundIds, onBound, onClose }) => {
  const [keyword, setKeyword] = useState('');
  const [score, setScore] = useState('1.0');
  const [reason, setReason] = useState('');
  const [formError, setFormError] = useState('');
  const [bindingId, setBindingId] = useState<string | null>(null);
  const debounced = useDebouncedValue(keyword, 350).trim();

  const { data, loading, error, refetch } = useAsyncData<ManageDocument[]>(
    async () => {
      if (!debounced) return [];
      const response = await manageApi.queryDocumentPage({ pageNo: 1, pageSize: 20, keyword: debounced });
      return response?.records ?? [];
    },
    [debounced]
  );

  const docs = data ?? [];

  const bind = async (documentId: string) => {
    const parsed = Number(score);
    if (!Number.isFinite(parsed) || parsed < 0 || parsed > 10) {
      setFormError('关联分数需要是 0 到 10 之间的数字，比如 1.0 表示强相关。');
      return;
    }
    setFormError('');
    setBindingId(documentId);
    try {
      await manageApi.saveTopicDocumentRelation({
        topicCode,
        documentId,
        relationScore: parsed,
        relationSource: 'manual',
        reason: reason.trim(),
      });
      toast({ title: '已绑定文档', description: '这个主题下的自动问答现在会检索到它了。', variant: 'success' });
      setReason('');
      onBound();
    } catch (bindError) {
      setFormError(actionFailure(bindError, '绑定文档', '请确认文档存在且没有重复绑定，然后重试。'));
    } finally {
      setBindingId(null);
    }
  };

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-secondary/30 p-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h4 className="text-xs font-medium text-foreground">给这个主题添加文档</h4>
          <p className="mt-0.5 text-2xs text-muted-foreground">按名称搜索当前文档库，最多返回 20 条。</p>
        </div>
        <Button size="sm" variant="ghost" onClick={onClose}>
          收起
        </Button>
      </div>

      <Field label="搜索文档" hint="输入文档名称的一部分即可">
        <Input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="例如：员工手册" />
      </Field>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-[7rem_1fr]">
        <Field label="关联分数" hint="0–10，默认 1.0">
          <Input type="number" min={0} max={10} step={0.1} value={score} onChange={(event) => setScore(event.target.value)} />
        </Field>
        <Field label="关联理由" hint="可选，方便以后回看为什么绑">
          <Input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="例如：该文档包含年假条款" />
        </Field>
      </div>

      {formError ? <p className="text-xs text-destructive" role="alert">{formError}</p> : null}

      {!debounced ? (
        <p className="text-xs text-muted-foreground">输入关键词后会在这里列出候选文档。</p>
      ) : loading ? (
        <Skeleton lines={3} />
      ) : error ? (
        <div className="flex items-center justify-between gap-2 rounded-md border border-destructive/30 p-2.5">
          <p className="text-2xs text-destructive">{loadFailure(error, '候选文档')}</p>
          <Button size="sm" variant="outline" onClick={() => refetch()}>
            重试
          </Button>
        </div>
      ) : docs.length === 0 ? (
        <p className="text-xs text-muted-foreground">没搜到文档。换个关键词，或先去「接入文档」上传。</p>
      ) : (
        <ul className="flex max-h-56 flex-col gap-1.5 overflow-y-auto">
          {docs.map((doc) => {
            const bound = boundIds.includes(doc.documentId);
            return (
              <li key={doc.documentId} className="flex items-center justify-between gap-2 rounded-md border border-border bg-card px-2.5 py-2">
                <span className="min-w-0">
                  <span className="block truncate text-xs font-medium text-foreground">{doc.documentName}</span>
                  <span className="block truncate font-mono text-2xs text-muted-foreground">{doc.documentId}</span>
                </span>
                {bound ? (
                  <span className="shrink-0 text-2xs text-muted-foreground">已关联</span>
                ) : (
                  <Button size="sm" variant="outline" loading={bindingId === doc.documentId} onClick={() => bind(doc.documentId)}>
                    <Link2 size={12} aria-hidden="true" />
                    关联
                  </Button>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
};
