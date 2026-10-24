import React, { useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { manageApi } from '../../../lib/api';
import type { KnowledgeScope, KnowledgeTopic } from '../../../types/api';
import { Button } from '../../../components/ui/Button';
import { ConfirmDialog } from '../../../components/ui/ConfirmDialog';
import { DataTable, type DataTableColumn } from '../../../components/ui/DataTable';
import { Field, Input, Select } from '../../../components/ui/Field';
import { IconButton } from '../../../components/ui/IconButton';
import { toast } from '../../../lib/toast';
import { actionFailure } from '../adminFormat';

interface Props {
  scopes: KnowledgeScope[];
  topics: KnowledgeTopic[];
  onRefresh: () => void;
}

/** 知识主题：范围下更细的可回答单元，文档最终挂到主题上 */
export const AdminKnowledgeTopicView: React.FC<Props> = ({ scopes, topics, onRefresh }) => {
  const [open, setOpen] = useState(false);
  const [topicName, setTopicName] = useState('');
  const [topicCode, setTopicCode] = useState('');
  const [scopeCode, setScopeCode] = useState(scopes[0]?.scopeCode ?? '');
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState<KnowledgeTopic | null>(null);

  const submit = async () => {
    if (!topicName.trim()) return setFormError('请填写主题名称，用户提问会命中它。');
    if (!topicCode.trim()) return setFormError('请填写主题编码，比如 leave_policy。');
    if (!scopeCode) return setFormError('请选择所属范围；没有范围时先去「知识范围」新建一个。');
    setFormError('');
    setSaving(true);
    try {
      await manageApi.saveKnowledgeTopic({ topicCode: topicCode.trim(), topicName: topicName.trim(), scopeCode });
      toast({ title: '已创建知识主题', description: `主题「${topicName.trim()}」已归入所选范围。`, variant: 'success' });
      setOpen(false);
      setTopicName('');
      setTopicCode('');
      onRefresh();
    } catch (error) {
      setFormError(actionFailure(error, '创建知识主题', '请确认主题编码没有被占用，然后重试。'));
    } finally {
      setSaving(false);
    }
  };

  const confirmDelete = async () => {
    if (!deleting) return;
    const target = deleting;
    setDeleting(null);
    try {
      await manageApi.deleteKnowledgeTopic({ topicCode: target.topicCode });
      toast({ title: '已删除知识主题', description: `主题「${target.topicName}」已移除。`, variant: 'success' });
      onRefresh();
    } catch (error) {
      toast({ title: '删除失败', description: actionFailure(error, '删除知识主题', '先解绑该主题下的文档，再删除。'), variant: 'error' });
    }
  };

  const columns: DataTableColumn<KnowledgeTopic>[] = [
    {
      key: 'code',
      header: '主题编码',
      render: (topic) => <span className="font-mono text-2xs text-muted-foreground">{topic.topicCode}</span>,
    },
    { key: 'name', header: '主题名称', render: (topic) => <span className="text-xs font-medium text-foreground">{topic.topicName}</span> },
    {
      key: 'scope',
      header: '所属范围',
      render: (topic) => {
        const scope = scopes.find((item) => item.scopeCode === topic.scopeCode);
        return <span className="text-xs text-muted-foreground">{scope?.scopeName ?? topic.scopeCode ?? '未归属'}</span>;
      },
    },
    {
      key: 'description',
      header: '描述',
      render: (topic) => (
        <span className="line-clamp-2 max-w-[22rem] text-2xs text-muted-foreground">{topic.description || '未填写'}</span>
      ),
    },
    {
      key: 'action',
      header: '操作',
      align: 'right',
      render: (topic) => (
        <IconButton
          label={`删除主题 ${topic.topicName}`}
          hint="解绑文档后可删除"
          variant="ghost"
          icon={<Trash2 size={13} aria-hidden="true" />}
          onClick={() => setDeleting(topic)}
        />
      ),
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-medium text-foreground">知识主题</h3>
          <p className="mt-1 text-xs text-muted-foreground">在知识范围下定义更细的可回答单元，后续把文档挂到主题上。</p>
        </div>
        <Button size="sm" variant="outline" onClick={() => setOpen((prev) => !prev)}>
          <Plus size={13} aria-hidden="true" />
          新建主题
        </Button>
      </div>

      {open ? (
        <form
          className="flex flex-col gap-3 rounded-lg border border-border bg-secondary/30 p-3 md:flex-row md:items-end"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <Field label="主题名称" required className="md:flex-1">
            <Input value={topicName} onChange={(event) => setTopicName(event.target.value)} placeholder="例如：年假申请流程" />
          </Field>
          <Field label="主题编码" required hint="字母、数字、下划线" className="md:flex-1">
            <Input value={topicCode} onChange={(event) => setTopicCode(event.target.value)} placeholder="例如：annual_leave" />
          </Field>
          <Field label="所属范围" required className="md:w-48">
            <Select value={scopeCode} onChange={(event) => setScopeCode(event.target.value)}>
              <option value="">请选择</option>
              {scopes.map((scope) => (
                <option key={scope.scopeCode} value={scope.scopeCode}>
                  {scope.scopeName}
                </option>
              ))}
            </Select>
          </Field>
          <Button type="submit" size="sm" loading={saving}>
            创建
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={() => setOpen(false)}>
            取消
          </Button>
        </form>
      ) : null}

      {formError ? <p className="text-xs text-destructive" role="alert">{formError}</p> : null}

      <DataTable
        caption="知识主题清单，含所属范围与描述"
        columns={columns}
        rows={topics}
        rowKey={(topic) => topic.topicCode}
        dense
        emptyTitle="还没有知识主题"
        emptyDescription="先建一个主题（比如「年假申请流程」），再把相关文档绑到它上面，自动问答才能命中。"
        emptyAction={
          <Button size="sm" onClick={() => setOpen(true)}>
            <Plus size={13} aria-hidden="true" />
            新建主题
          </Button>
        }
      />

      <ConfirmDialog
        open={deleting !== null}
        title="删除这个知识主题？"
        description={deleting ? `主题「${deleting.topicName}」会被移除，绑定在它下面的文档关系也会失效。` : ''}
        confirmLabel="删除"
        danger
        onConfirm={confirmDelete}
        onCancel={() => setDeleting(null)}
      />
    </div>
  );
};
