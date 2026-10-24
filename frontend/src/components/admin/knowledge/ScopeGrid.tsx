import React, { useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { manageApi } from '../../../lib/api';
import type { KnowledgeScope, KnowledgeTopic } from '../../../types/api';
import { Button } from '../../../components/ui/Button';
import { ConfirmDialog } from '../../../components/ui/ConfirmDialog';
import { Field, Input } from '../../../components/ui/Field';
import { IconButton } from '../../../components/ui/IconButton';
import { toast } from '../../../lib/toast';
import { actionFailure } from '../adminFormat';

interface Props {
  scopes: KnowledgeScope[];
  topics: KnowledgeTopic[];
  onRefresh: () => void;
}

/** 知识范围：系统划定的领域划分，主题都挂在某个范围下 */
export const ScopeGrid: React.FC<Props> = ({ scopes, topics, onRefresh }) => {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [code, setCode] = useState('');
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState<KnowledgeScope | null>(null);

  const submit = async () => {
    if (!name.trim()) return setFormError('请填写范围名称，比如「人事制度」。');
    if (!code.trim()) return setFormError('请填写范围编码，只能用字母、数字和下划线，比如 hr_policy。');
    setFormError('');
    setSaving(true);
    try {
      await manageApi.saveKnowledgeScope({ scopeCode: code.trim(), scopeName: name.trim() });
      toast({ title: '已创建知识范围', description: `范围「${name.trim()}」可以开始挂主题了。`, variant: 'success' });
      setOpen(false);
      setName('');
      setCode('');
      onRefresh();
    } catch (error) {
      setFormError(actionFailure(error, '创建知识范围', '请确认编码没有被占用，然后重试。'));
    } finally {
      setSaving(false);
    }
  };

  const confirmDelete = async () => {
    if (!deleting) return;
    const target = deleting;
    setDeleting(null);
    try {
      await manageApi.deleteKnowledgeScope({ scopeCode: target.scopeCode });
      toast({ title: '已删除知识范围', description: `范围「${target.scopeName}」已移除。`, variant: 'success' });
      onRefresh();
    } catch (error) {
      toast({ title: '删除失败', description: actionFailure(error, '删除知识范围', '该范围下可能还有主题，先清空主题再删。'), variant: 'error' });
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-medium text-foreground">知识范围</h3>
          <p className="mt-1 text-xs text-muted-foreground">先把大范围定清楚，自动问答才能在正确的文档池里预选。</p>
        </div>
        <Button size="sm" variant="outline" onClick={() => setOpen((prev) => !prev)}>
          <Plus size={13} aria-hidden="true" />
          新建范围
        </Button>
      </div>

      {open ? (
        <form
          className="flex flex-col gap-3 rounded-lg border border-border bg-secondary/30 p-3 sm:flex-row sm:items-end"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <Field label="范围名称" required className="sm:flex-1">
            <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：人事制度" />
          </Field>
          <Field label="范围编码" required hint="字母、数字、下划线" className="sm:flex-1">
            <Input value={code} onChange={(event) => setCode(event.target.value)} placeholder="例如：hr_policy" />
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

      {scopes.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border px-5 py-10 text-center">
          <p className="text-sm font-medium text-foreground">还没有知识范围</p>
          <p className="mt-1 text-xs text-muted-foreground">先建一个范围（比如「人事制度」），再往里加主题和文档。</p>
          <Button size="sm" className="mt-3" onClick={() => setOpen(true)}>
            <Plus size={13} aria-hidden="true" />
            新建范围
          </Button>
        </div>
      ) : (
        <ul className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
          {scopes.map((scope) => (
            <li key={scope.scopeCode} className="rounded-xl border border-border bg-card p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <h4 className="truncate text-sm font-medium text-foreground">{scope.scopeName}</h4>
                  <p className="mt-0.5 font-mono text-2xs text-muted-foreground">{scope.scopeCode}</p>
                </div>
                <IconButton
                  label={`删除范围 ${scope.scopeName}`}
                  hint="该范围下的主题需要先清空"
                  variant="ghost"
                  icon={<Trash2 size={13} aria-hidden="true" />}
                  onClick={() => setDeleting(scope)}
                />
              </div>
              <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-muted-foreground">{scope.description || '暂无描述'}</p>
              <p className="mt-3 border-t border-border pt-2 text-2xs text-muted-foreground">
                主题数：{topics.filter((topic) => topic.scopeCode === scope.scopeCode).length}
              </p>
            </li>
          ))}
        </ul>
      )}

      <ConfirmDialog
        open={deleting !== null}
        title="删除这个知识范围？"
        description={deleting ? `范围「${deleting.scopeName}」会被移除，挂在上面的主题将失去归属。` : ''}
        confirmLabel="删除"
        danger
        onConfirm={confirmDelete}
        onCancel={() => setDeleting(null)}
      />
    </div>
  );
};
