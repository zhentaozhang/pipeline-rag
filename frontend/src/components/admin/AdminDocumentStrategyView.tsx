import React, { useState, useEffect } from 'react';
import { manageApi, APIError } from '../../lib/api';
import type { ManageDocument, StrategyPlanResponse } from '../../types/api';
import { 
  STRATEGY_LIBRARY, 
  STRATEGY_PIPELINE_LIBRARY,
  extractPipelineStrategyTypes,
  buildStrategyPreview,
  buildPipelineStepPayload
} from '../../lib/documentStrategyPipeline';

interface AdminDocumentStrategyViewProps {
  documentId: string;
  documentDetail: ManageDocument | null;
  showNotice: (msg: string, type?: 'info' | 'success' | 'danger') => void;
  onStrategyConfirmed: () => void;
}

export const AdminDocumentStrategyView: React.FC<AdminDocumentStrategyViewProps> = ({ 
  documentId, 
  showNotice,
  onStrategyConfirmed
}) => {
  const [loading, setLoading] = useState(false);
  const [strategyPlan, setStrategyPlan] = useState<StrategyPlanResponse | null>(null);
  const [selectedParentTypes, setSelectedParentTypes] = useState<string[]>([]);
  const [selectedChildTypes, setSelectedChildTypes] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  const loadStrategyPlan = async () => {
    setLoading(true);
    try {
      const data = await manageApi.queryStrategyPlan(documentId);
      setStrategyPlan(data);
      if (data?.plan) {
        setSelectedParentTypes(extractPipelineStrategyTypes(data.plan, 'parent', STRATEGY_LIBRARY));
        setSelectedChildTypes(extractPipelineStrategyTypes(data.plan, 'child', STRATEGY_LIBRARY));
      }
    } catch (error) {
      console.error('Failed to load strategy plan', error);
      showNotice(error instanceof APIError ? error.message : '加载策略配置失败', 'danger');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (documentId) {
      void (async () => {
        await loadStrategyPlan();
      })();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentId]);

  const toggleStrategy = (type: string, pipelineKey: string) => {
    const isParent = pipelineKey === 'parent';
    const currentTypes = isParent ? [...selectedParentTypes] : [...selectedChildTypes];
    
    const index = currentTypes.indexOf(type);
    if (index >= 0) {
      currentTypes.splice(index, 1);
    } else {
      currentTypes.push(type);
    }

    if (isParent) setSelectedParentTypes(currentTypes);
    else setSelectedChildTypes(currentTypes);
  };

  const moveStrategy = (type: string, dir: number, pipelineKey: string) => {
    const isParent = pipelineKey === 'parent';
    const currentTypes = isParent ? [...selectedParentTypes] : [...selectedChildTypes];
    
    const index = currentTypes.indexOf(type);
    if (index < 0) return;
    
    const newIndex = index + dir;
    if (newIndex < 0 || newIndex >= currentTypes.length) return;
    
    currentTypes.splice(index, 1);
    currentTypes.splice(newIndex, 0, type);

    if (isParent) setSelectedParentTypes(currentTypes);
    else setSelectedChildTypes(currentTypes);
  };

  const confirmStrategy = async () => {
    setSaving(true);
    try {
      await manageApi.confirmStrategy({
        documentId,
        basePlanId: strategyPlan?.plan?.planId || '0',
        parentSteps: buildPipelineStepPayload(selectedParentTypes),
        childSteps: buildPipelineStepPayload(selectedChildTypes)
      });
      showNotice('策略配置已确认保存', 'success');
      onStrategyConfirmed();
    } catch (error) {
      showNotice(error instanceof APIError ? error.message : '保存策略失败', 'danger');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-muted-foreground">
        <svg className="animate-spin h-8 w-8 text-primary mb-4" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        <p>正在读取策略详情...</p>
      </div>
    );
  }

  if (!strategyPlan?.planReady) {
    return (
      <div className="p-8 text-center text-muted-foreground bg-secondary/30 rounded-xl border border-border/50 m-6">
        当前文档尚未生成策略方案，请等待解析完成后刷新查看。
      </div>
    );
  }

    const renderPipeline = (pipelineKey: string, pipelineTitle: string, selectedTypes: string[]) => {
      const preview = buildStrategyPreview(selectedTypes, STRATEGY_LIBRARY);
      
      return (
        <div className="bg-secondary/30 rounded-xl border border-border/50 p-6 flex flex-col gap-4">
          <div>
            <h4 className="text-sm font-bold text-foreground uppercase tracking-wider">{pipelineTitle}</h4>
            <p className="text-xs text-muted-foreground mt-1">{STRATEGY_PIPELINE_LIBRARY.find(p => p.key === pipelineKey)?.description}</p>
          </div>
  
          <div className="flex flex-wrap gap-2">
            {STRATEGY_LIBRARY.map(item => {
              const isSelected = selectedTypes.includes(item.type);
              return (
                <button
                  key={item.type}
                  onClick={() => toggleStrategy(item.type, pipelineKey)}
                  className={`flex flex-col items-start p-3 border rounded-lg transition-all text-left min-w-[200px] ${
                    isSelected 
                      ? 'bg-primary/5 border-primary/30 shadow-sm' 
                      : 'bg-background border-border hover:border-primary/50'
                  }`}
                >
                  <div className="flex items-center gap-2 mb-1 w-full justify-between">
                    <span className={`text-xs font-bold px-1.5 py-0.5 rounded ${
                      isSelected ? 'bg-primary/10 text-primary' : 'bg-secondary text-muted-foreground'
                    }`}>
                      {isSelected ? '已选中' : '点击添加'}
                    </span>
                    {isSelected && (
                      <svg className="w-4 h-4 text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                      </svg>
                    )}
                  </div>
                  <strong className={`text-sm ${isSelected ? 'text-primary' : 'text-foreground'}`}>
                    {item.label}
                  </strong>
                  <span className="text-xs text-muted-foreground mt-1">{item.description}</span>
                </button>
              );
            })}
          </div>
  
          <div className="mt-4 p-4 bg-background border border-border/50 rounded-lg">
            <span className="text-xs font-bold text-muted-foreground uppercase tracking-wider mb-3 block">当前执行顺序</span>
            {preview.length === 0 ? (
              <span className="text-sm text-muted-foreground opacity-80">尚未选择任何策略</span>
            ) : (
              <div className="flex flex-col gap-2">
                {preview.map((item, idx) => (
                  <div key={item.type} className="flex items-center gap-3 p-2 bg-secondary/20 rounded border border-border/50">
                    <span className="text-xs font-mono font-bold text-muted-foreground bg-background px-1.5 py-0.5 rounded border border-border/50">{item.order}</span>
                    <span className="text-sm font-medium text-foreground flex-1">{item.label}</span>
                    <div className="flex items-center gap-1">
                      <button 
                        onClick={() => moveStrategy(item.type, -1, pipelineKey)}
                        disabled={idx === 0}
                        className="p-1 text-muted-foreground hover:text-primary disabled:opacity-30 transition-colors"
                      >
                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" /></svg>
                      </button>
                      <button 
                        onClick={() => moveStrategy(item.type, 1, pipelineKey)}
                        disabled={idx === preview.length - 1}
                        className="p-1 text-muted-foreground hover:text-primary disabled:opacity-30 transition-colors"
                      >
                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" /></svg>
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      );
    };

  return (
    <div className="p-6 md:p-8">
      <div className="mb-6 flex justify-between items-start">
        <div>
          <h3 className="text-lg font-bold text-foreground tracking-tight">配置策略</h3>
          <p className="text-sm text-muted-foreground mt-1">分别配置父块回答流水线和子块召回流水线，并通过上移 / 下移调整顺序。</p>
        </div>
        <button
          onClick={confirmStrategy}
          disabled={saving || (selectedParentTypes.length === 0 && selectedChildTypes.length === 0)}
          className="px-4 py-2 bg-primary text-primary-foreground rounded-md text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 shadow-sm shadow-primary/20"
        >
          {saving ? (
            <>
              <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-primary-foreground" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              保存中...
            </>
          ) : (
            '保存策略配置'
          )}
        </button>
      </div>

      <div className="bg-primary/5 border border-primary/20 rounded-lg p-4 mb-6">
        <h4 className="text-sm font-bold text-primary mb-1">系统推荐摘要</h4>
        <p className="text-sm text-primary/80">
          {strategyPlan?.plan?.recommendReason || '系统已生成推荐策略，可以根据业务需要再做补充。'}
        </p>
      </div>

      <div className="flex flex-col gap-6">
        {renderPipeline('parent', '父块回答流水线', selectedParentTypes)}
        {renderPipeline('child', '子块召回流水线', selectedChildTypes)}
      </div>
    </div>
  );
};
