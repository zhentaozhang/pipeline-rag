import React, { useRef, useState } from 'react';
import { FileUp, Upload } from 'lucide-react';
import { manageApi } from '../../../lib/api';
import { formatFileSize } from '../../../lib/manageFormat';
import { toast } from '../../../lib/toast';
import { Button } from '../../ui/Button';
import { Field, Input } from '../../ui/Field';
import { AdminPanel } from '../AdminPanel';
import { actionFailure } from '../adminFormat';

const OPERATOR_ID = '10001';
const ACCEPT = '.pdf,.doc,.docx,.txt,.md,.html';

interface UploadForm {
  documentName: string;
  knowledgeScopeCode: string;
  knowledgeScopeName: string;
  businessCategory: string;
  documentTags: string;
}

const EMPTY_FORM: UploadForm = {
  documentName: '',
  knowledgeScopeCode: '',
  knowledgeScopeName: '',
  businessCategory: '',
  documentTags: '',
};

const STEPS = [
  '先上传文档，系统会异步解析并生成推荐切块策略。',
  '在下方列表点击任意文档，进入详情页查看解析结果、切块和任务轨迹。',
  '在详情页确认策略并构建索引，列表页专注浏览和筛选。',
];

/** 上传面板：选文件 + 归属元信息，成功后由父组件负责刷新列表并跳转详情 */
export const UploadPanel: React.FC<{ onUploaded: (result: Record<string, unknown>) => void }> = ({
  onUploaded,
}) => {
  const [form, setForm] = useState<UploadForm>(EMPTY_FORM);
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState('');
  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const patch = (key: keyof UploadForm) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((prev) => ({ ...prev, [key]: e.target.value }));

  const pickFile = (picked: File | null | undefined) => {
    setFileError('');
    setFile(picked ?? null);
  };

  const clearSelection = () => {
    setForm(EMPTY_FORM);
    setFile(null);
    setFileError('');
    if (inputRef.current) inputRef.current.value = '';
  };

  const submit = async () => {
    if (!file) {
      setFileError('还没有选择文件。请点击上方虚线框选择 PDF / DOC / DOCX / TXT / MD / HTML 文件后再上传。');
      return;
    }
    setUploading(true);
    try {
      const result = await manageApi.uploadDocument({
        file,
        documentName: form.documentName.trim(),
        operatorId: OPERATOR_ID,
        knowledgeScopeCode: form.knowledgeScopeCode.trim(),
        knowledgeScopeName: form.knowledgeScopeName.trim(),
        businessCategory: form.businessCategory.trim(),
        documentTags: form.documentTags.trim(),
      });
      toast({
        title: '文档已上传',
        description: `任务 ${String(result?.taskId ?? '')} 已进入解析与策略推荐队列。`,
        variant: 'success',
      });
      clearSelection();
      onUploaded(result ?? {});
    } catch (error) {
      toast({
        title: '上传文档失败',
        description: actionFailure(error, '上传文档', '请确认文件未超过后端限制，然后重新上传。'),
        variant: 'error',
      });
    } finally {
      setUploading(false);
    }
  };

  return (
    <div id="upload-panel" className="grid grid-cols-1 gap-4 lg:grid-cols-[1.1fr_0.9fr]">
      <AdminPanel title="上传新文档" description="支持 PDF / DOC / DOCX / TXT / MD / HTML">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="文档名称" hint="不填则使用原始文件名">
            <Input value={form.documentName} onChange={patch('documentName')} placeholder="例如 运营规则手册" />
          </Field>
          <Field label="知识域编码" hint="用于自动问答时预选文档池，例如 operation_rule">
            <Input value={form.knowledgeScopeCode} onChange={patch('knowledgeScopeCode')} placeholder="operation_rule" />
          </Field>
          <Field label="知识域名称">
            <Input value={form.knowledgeScopeName} onChange={patch('knowledgeScopeName')} placeholder="运营规则" />
          </Field>
          <Field label="业务分类">
            <Input value={form.businessCategory} onChange={patch('businessCategory')} placeholder="手册 / 规则 / 介绍" />
          </Field>
          <Field label="文档标签" hint="多个标签用英文逗号分隔" className="sm:col-span-2">
            <Input value={form.documentTags} onChange={patch('documentTags')} placeholder="rag, 运营, v2" />
          </Field>
        </div>

        <div className="mt-4">
          <label
            onDragOver={(e) => {
              e.preventDefault();
              setDragActive(true);
            }}
            onDragLeave={() => setDragActive(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragActive(false);
              pickFile(e.dataTransfer.files?.[0]);
            }}
            className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-4 py-6 text-center transition-colors focus-within:ring-2 focus-within:ring-ring ${
              dragActive ? 'border-primary bg-primary/5' : 'border-border bg-secondary/30 hover:bg-secondary/60'
            }`}
          >
            <FileUp size={20} aria-hidden="true" className="text-muted-foreground" />
            {file ? (
              <>
                <span className="max-w-full truncate text-sm font-medium text-foreground">{file.name}</span>
                <span className="text-xs text-muted-foreground">{formatFileSize(file.size)}</span>
              </>
            ) : (
              <span className="text-sm text-muted-foreground">
                点击选择文件，或把文件拖到这里
              </span>
            )}
            <input
              ref={inputRef}
              type="file"
              accept={ACCEPT}
              className="sr-only"
              onChange={(e) => pickFile(e.target.files?.[0])}
            />
          </label>
          {fileError ? (
            <p role="alert" className="mt-2 text-xs text-destructive">
              {fileError}
            </p>
          ) : null}
        </div>

        <div className="mt-4 flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={clearSelection} disabled={uploading}>
            清空
          </Button>
          <Button size="sm" onClick={submit} loading={uploading} disabled={!file}>
            <Upload size={14} aria-hidden="true" />
            上传并解析
          </Button>
        </div>
      </AdminPanel>

      <AdminPanel title="建议操作顺序" description="按这三步走，能最快看到从文档到问答的完整链路">
        <ol className="flex flex-col gap-4">
          {STEPS.map((step, index) => (
            <li key={step} className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-secondary text-xs font-semibold text-secondary-foreground">
                {index + 1}
              </span>
              <p className="text-sm leading-relaxed text-muted-foreground">{step}</p>
            </li>
          ))}
        </ol>
      </AdminPanel>
    </div>
  );
};
