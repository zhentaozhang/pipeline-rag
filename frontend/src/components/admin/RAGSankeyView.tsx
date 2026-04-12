import React, { useMemo, useState } from 'react';

interface RAGSankeyViewProps {
  channelExecutions: any[];
  retrievalResults: any[];
  activeExchange: any;
}

export const RAGSankeyView: React.FC<RAGSankeyViewProps> = ({ 
  channelExecutions, 
  retrievalResults, 
  activeExchange 
}) => {
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);

  const { nodes, links, metrics } = useMemo(() => {
    // 1. Data mapping (Fixing uppercase bug)
    const vectorRecall = channelExecutions.find(c => String(c.channel).toLowerCase() === 'vector')?.recalled_count || 0;
    const keywordRecall = channelExecutions.find(c => String(c.channel).toLowerCase() === 'keyword')?.recalled_count || 0;
    
    let fusionCount = retrievalResults.filter(r => String(r.phase).toUpperCase() === 'FUSION').length;
    let rerankCount = retrievalResults.filter(r => String(r.phase).toUpperCase() === 'RERANK').length;
    
    // Fallback if phase string is missing or different
    if (fusionCount === 0 && rerankCount === 0) {
      fusionCount = retrievalResults.filter(r => r.gate_passed).length;
      rerankCount = retrievalResults.filter(r => r.score > 0).length;
    }
    
    // Total from vector + keyword might be greater or equal to fusion depending on deduplication
    const sourceTotal = vectorRecall + keywordRecall;
    const finalCount = activeExchange?.references?.length || 0;

    // 2. Adaptive Layout Math
    const maxFlow = Math.max(sourceTotal, fusionCount, rerankCount, finalCount, 1);
    
    const svgH = 340;
    const usableH = 220; // Safe area for node heights to prevent clipping
    
    // Function to calculate node height, guaranteeing minimum height if > 0
    const scale = (val: number) => {
      if (val === 0) return 0;
      return Math.max((val / maxFlow) * usableH, 12);
    };

    const vH = scale(vectorRecall);
    const kH = scale(keywordRecall);
    const fH = scale(fusionCount);
    const rH = scale(rerankCount);
    const finH = scale(finalCount);

    const gap = 20;
    const centerY = svgH / 2;

    // Columns X
    const x0 = 50, x1 = 300, x2 = 550, x3 = 800;
    const nodeW = 14;

    // Stack vector and keyword at x0
    const sourceGroupH = vH + (vH > 0 && kH > 0 ? gap : 0) + kH;
    const sourceStartY = centerY - sourceGroupH / 2;

    const nodes = {
      vector: { id: 'vector', x: x0, y: sourceStartY, h: vH, label: 'PGVector', value: vectorRecall, color: '#10B981', desc: '向量检索召回的段落数' },
      keyword: { id: 'keyword', x: x0, y: sourceStartY + vH + (vH > 0 ? gap : 0), h: kH, label: 'Elasticsearch', value: keywordRecall, color: '#3B82F6', desc: '关键词检索召回的段落数' },
      fusion: { id: 'fusion', x: x1, y: centerY - fH / 2, h: fH, label: 'RRF Fusion', value: fusionCount, color: '#8B5CF6', desc: '经倒数排序融合去重后的段落数' },
      rerank: { id: 'rerank', x: x2, y: centerY - rH / 2, h: rH, label: 'BGE Reranker', value: rerankCount, color: '#F59E0B', desc: '经过重排截断后保留的优质段落数' },
      final: { id: 'final', x: x3, y: centerY - finH / 2, h: finH, label: 'Prompt Context', value: finalCount, color: '#D97706', desc: '受限于 Token 预算最终进入 Prompt 的段落数' }
    };

    // SVG Cubic Bezier generator for Sankey links
    const linkPath = (sx: number, sy: number, sh: number, tx: number, ty: number, th: number) => {
      if (sh === 0 || th === 0) return '';
      const cx1 = sx + (tx - sx) * 0.4;
      const cx2 = tx - (tx - sx) * 0.4;
      return `M ${sx} ${sy} C ${cx1} ${sy}, ${cx2} ${ty}, ${tx} ${ty} L ${tx} ${ty + th} C ${cx2} ${ty + th}, ${cx1} ${sy + sh}, ${sx} ${sy + sh} Z`;
    };

    // Distribute the target height proportionally for the incoming flows
    const vToF_th = (vectorRecall / Math.max(sourceTotal, 1)) * fH;
    const kToF_th = (keywordRecall / Math.max(sourceTotal, 1)) * fH;

    const links = [
      { 
        source: 'vector', target: 'fusion',
        d: linkPath(nodes.vector.x + nodeW, nodes.vector.y, nodes.vector.h, nodes.fusion.x, nodes.fusion.y, vToF_th), 
        color: nodes.vector.color 
      },
      { 
        source: 'keyword', target: 'fusion',
        d: linkPath(nodes.keyword.x + nodeW, nodes.keyword.y, nodes.keyword.h, nodes.fusion.x, nodes.fusion.y + vToF_th, kToF_th), 
        color: nodes.keyword.color 
      },
      { 
        source: 'fusion', target: 'rerank',
        d: linkPath(nodes.fusion.x + nodeW, nodes.fusion.y, nodes.fusion.h, nodes.rerank.x, nodes.rerank.y, nodes.rerank.h), 
        color: nodes.fusion.color 
      },
      { 
        source: 'rerank', target: 'final',
        d: linkPath(nodes.rerank.x + nodeW, nodes.rerank.y, nodes.rerank.h, nodes.final.x, nodes.final.y, nodes.final.h), 
        color: nodes.rerank.color 
      }
    ];

    return { nodes: Object.values(nodes), links, metrics: { vectorRecall, keywordRecall, fusionCount, rerankCount, finalCount } };
  }, [channelExecutions, retrievalResults, activeExchange]);

  if (metrics.vectorRecall === 0 && metrics.keywordRecall === 0 && metrics.finalCount === 0) {
    return (
      <section className="mb-8">
        <h3 className="text-lg font-semibold font-heading text-foreground mb-1">
          <span className="block text-xs font-mono text-muted-foreground uppercase tracking-widest mb-1">召回流水线</span>
          RAG 召回漏斗分析
        </h3>
        <div className="w-full bg-card border border-border/40 rounded-xl p-12 text-center shadow-sm">
           <p className="text-muted-foreground">当前轮次未触发大规模文档检索，或后端未记录检索通道数据。</p>
        </div>
      </section>
    );
  }

  return (
    <section className="mb-8">
      <h3 className="text-lg font-semibold font-heading text-foreground mb-1">
        <span className="block text-xs font-mono text-muted-foreground uppercase tracking-widest mb-1">Retrieval Pipeline</span>
        RAG 召回漏斗分析
      </h3>
      <p className="text-sm text-muted-foreground mb-6">双路检索→融合→重排→最终上下文，追踪每一段切块的流向。</p>

      <div className="w-full bg-background border border-border/50 rounded-xl shadow-sm overflow-hidden p-6 relative">
        <div className="w-full overflow-x-auto overflow-y-hidden">
          <div className="min-w-[900px] h-[360px] relative select-none">
            
            {/* Background Grid Lines optional for enterprise feel */}
            <div className="absolute inset-0 pointer-events-none opacity-5">
               <div className="h-full w-px bg-foreground absolute left-[50px]"></div>
               <div className="h-full w-px bg-foreground absolute left-[300px]"></div>
               <div className="h-full w-px bg-foreground absolute left-[550px]"></div>
               <div className="h-full w-px bg-foreground absolute left-[800px]"></div>
            </div>

            <svg width="100%" height="100%" viewBox="0 0 900 360" className="absolute inset-0">
              {/* Links */}
              {links.map((link, i) => {
                if (!link.d) return null;
                const isFaded = hoveredNode && hoveredNode !== link.source && hoveredNode !== link.target;
                return (
                  <path 
                    key={i} 
                    d={link.d} 
                    fill={link.color} 
                    fillOpacity={isFaded ? "0.05" : "0.25"} 
                    className="transition-all duration-300"
                  />
                );
              })}

              {/* Nodes */}
              {nodes.map((node, i) => {
                if (node.h === 0) return null;
                const isHovered = hoveredNode === node.id;
                const isFaded = hoveredNode && !isHovered;
                
                return (
                  <g 
                    key={i} 
                    className="group"
                    onMouseEnter={() => setHoveredNode(node.id)}
                    onMouseLeave={() => setHoveredNode(null)}
                  >
                    <rect 
                      x={node.x} 
                      y={node.y} 
                      width={14} 
                      height={node.h} 
                      fill={node.color} 
                      rx={3}
                      className={`cursor-pointer transition-all duration-300 ${isFaded ? 'opacity-30' : 'opacity-100'}`}
                    />
                    
                    {/* Hover Glow */}
                    {isHovered && (
                       <rect x={node.x-2} y={node.y-2} width={18} height={node.h+4} fill="none" stroke={node.color} strokeWidth="2" rx="4" opacity="0.5" />
                    )}

                    {/* Node Label Top */}
                    <text 
                      x={node.x + 7} 
                      y={node.y - 14} 
                      textAnchor="middle" 
                      className={`text-xs font-semibold font-mono transition-opacity ${isFaded ? 'opacity-30 fill-muted-foreground' : 'fill-foreground'}`}
                    >
                      {node.label}
                    </text>
                    
                    {/* Node Value Pill */}
                    <rect 
                      x={node.x - 16} 
                      y={node.y + node.h + 12} 
                      width={46} 
                      height={22} 
                      fill={isHovered ? node.color : "var(--color-secondary, #f3f4f6)"} 
                      rx={6} 
                      className="transition-colors duration-300"
                    />
                    <text 
                      x={node.x + 7} 
                      y={node.y + node.h + 27} 
                      textAnchor="middle" 
                      className={`text-[11px] font-bold font-mono transition-colors duration-300 ${isHovered ? 'fill-white dark:fill-black' : 'fill-foreground'}`}
                    >
                      {node.value}
                    </text>
                  </g>
                );
              })}
            </svg>
            
            {/* Headers */}
            <div className="absolute top-0 left-0 w-full flex justify-between px-[38px] pt-1 pointer-events-none">
              <div className="flex flex-col w-[40px] items-center">
                <span className="text-[10px] font-mono text-muted-foreground uppercase tracking-wider mb-0.5">召回</span>
                <span className="text-sm font-semibold text-foreground whitespace-nowrap">双路召回</span>
              </div>
              <div className="flex flex-col w-[40px] items-center ml-[210px]">
                <span className="text-[10px] font-mono text-muted-foreground uppercase tracking-wider mb-0.5">融合</span>
                <span className="text-sm font-semibold text-foreground whitespace-nowrap">RRF 融合</span>
              </div>
              <div className="flex flex-col w-[40px] items-center ml-[210px]">
                <span className="text-[10px] font-mono text-muted-foreground uppercase tracking-wider mb-0.5">精排</span>
                <span className="text-sm font-semibold text-foreground whitespace-nowrap">重排截断</span>
              </div>
              <div className="flex flex-col w-[40px] items-center ml-[210px]">
                <span className="text-[10px] font-mono text-muted-foreground uppercase tracking-wider mb-0.5">结果</span>
                <span className="text-sm font-semibold text-foreground whitespace-nowrap">最终上下文</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
};
