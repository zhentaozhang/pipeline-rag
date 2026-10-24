import React from 'react';
import { ArrowLeft } from 'lucide-react';
import type { DocumentProfile } from '../../../types/api';
import { Badge } from '../../../components/ui/Badge';
import { Button } from '../../../components/ui/Button';

const QUALITY_LABELS = ['未知', '低', '中', '高'];

/** coreTopics 后端存的是 JSON 字符串，解析失败不应该整页崩掉 */
const parseTopics = (raw?: string | null): string[] => {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.map((item) => String(item)) : [];
  } catch {
    return [];
  }
};

interface Props {
  profile: DocumentProfile;
  onBack: () => void;
}

/** 单份文档的画像详情：摘要、核心主题、能力标签 */
export const ProfileDetail: React.FC<Props> = ({ profile, onBack }) => {
  const topics = parseTopics(profile.coreTopics);
  const capabilities = [
    { label: '结构清晰度', value: QUALITY_LABELS[Number(profile.structureLevel)] || '未知' },
    { label: '图谱友好', value: profile.graphFriendly ? '是' : '否', ok: Boolean(profile.graphFriendly) },
    { label: '支持条目检索', value: profile.supportsItemLookup ? '是' : '否', ok: Boolean(profile.supportsItemLookup) },
  ];

  return (
    <div className="flex flex-col gap-4">
      <Button size="sm" variant="ghost" className="self-start" onClick={onBack}>
        <ArrowLeft size={13} aria-hidden="true" />
        返回列表
      </Button>

      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border pb-3">
        <div className="min-w-0">
          <h4 className="truncate text-sm font-medium text-foreground">{profile.documentName || '未知文档'}</h4>
          <p className="mt-0.5 truncate font-mono text-2xs text-muted-foreground">{profile.documentId}</p>
        </div>
        <Badge variant="secondary">
          内容质量：{QUALITY_LABELS[Number(profile.contentQualityLevel)] || '未知'}
        </Badge>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <section className="flex flex-col gap-3">
          <div>
            <h5 className="mb-1.5 text-xs font-medium text-foreground">文档摘要</h5>
            <p className="rounded-lg border border-border bg-secondary/40 p-3 text-xs leading-relaxed text-muted-foreground">
              {profile.summary || '这份文档还没有生成摘要，先完成解析与画像重建。'}
            </p>
          </div>
          <div>
            <h5 className="mb-1.5 text-xs font-medium text-foreground">核心主题</h5>
            {topics.length === 0 ? (
              <p className="text-xs text-muted-foreground">没有提取到核心主题。</p>
            ) : (
              <ul className="flex flex-wrap gap-1.5">
                {topics.map((topic) => (
                  <li key={topic} className="rounded-full border border-border bg-secondary px-2 py-0.5 text-2xs text-foreground">
                    {topic}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>

        <section>
          <h5 className="mb-1.5 text-xs font-medium text-foreground">能力标签</h5>
          <dl className="flex flex-col gap-1.5">
            {capabilities.map((item) => (
              <div key={item.label} className="flex items-center justify-between rounded-lg border border-border bg-secondary/30 px-3 py-2">
                <dt className="text-xs text-foreground">{item.label}</dt>
                <dd>
                  <Badge variant={item.ok === undefined ? 'secondary' : item.ok ? 'success' : 'outline'}>{item.value}</Badge>
                </dd>
              </div>
            ))}
          </dl>
        </section>
      </div>
    </div>
  );
};
