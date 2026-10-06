import React, { useState, useEffect, useRef } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import client from '../api/client';
import { X, Maximize2 } from 'lucide-react';

interface GraphViewerProps {
  onClose: () => void;
}

const GraphViewer: React.FC<GraphViewerProps> = ({ onClose }) => {
  const [graphData, setGraphData] = useState({ nodes: [], links: [] });
  const [loading, setLoading] = useState(true);
  const [selectedNode, setSelectedNode] = useState<any>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });

  useEffect(() => {
    const fetchGraph = async () => {
      try {
        setLoading(true);
        const res = await client.get('/graph');
        setGraphData(res.data);
      } catch (err) {
        console.error('Failed to load graph:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchGraph();
  }, []);

  useEffect(() => {
    if (containerRef.current) {
      setDimensions({
        width: containerRef.current.clientWidth,
        height: containerRef.current.clientHeight
      });
    }
    
    const handleResize = () => {
      if (containerRef.current) {
        setDimensions({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight
        });
      }
    };
    
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 sm:p-8">
      <div className="bg-card w-full h-full max-w-6xl max-h-[90vh] rounded-xl shadow-2xl border flex flex-col overflow-hidden relative">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b">
          <div className="flex items-center gap-2 flex-wrap">
            <Maximize2 className="w-5 h-5 text-primary" />
            <h2 className="text-lg font-semibold text-foreground">Knowledge Graph Explorer</h2>
            {!loading && <span className="text-xs text-muted-foreground ml-2">({graphData.nodes.length} nodes, {graphData.links.length} edges)</span>}
            {/* Conflict edge legend */}
            <div className="flex items-center gap-2 ml-4 text-[10px] font-medium">
              <span className="flex items-center gap-1"><span className="inline-block w-4 h-0.5 bg-red-500"></span>REPLACES</span>
              <span className="flex items-center gap-1"><span className="inline-block w-4 h-0.5 bg-amber-500"></span>MODIFIES</span>
              <span className="flex items-center gap-1"><span className="inline-block w-4 h-0.5 bg-blue-500"></span>SUPPLEMENTS</span>
              <span className="flex items-center gap-1"><span className="inline-block w-4 h-0.5 bg-purple-500"></span>OVERLAPS</span>
            </div>
          </div>
          <button 
            onClick={onClose}
            className="p-2 hover:bg-muted rounded-full transition-colors"
          >
            <X className="w-5 h-5 text-muted-foreground hover:text-foreground" />
          </button>
        </div>

        {/* Graph Area */}
        <div className="flex-1 w-full bg-slate-50 dark:bg-slate-900 relative" ref={containerRef}>
          {loading ? (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
            </div>
          ) : graphData.nodes.length === 0 ? (
            <div className="absolute inset-0 flex items-center justify-center text-muted-foreground">
              No graph data available. Upload some documents first.
            </div>
          ) : (
            <ForceGraph2D
              width={dimensions.width}
              height={dimensions.height}
              graphData={graphData}
              nodeLabel="label"
              nodeColor={() => '#3b82f6'}
              nodeRelSize={6}
              linkColor={(link: any) => {
                const lbl = (link.label || '').toUpperCase()
                if (lbl.includes('REPLACES')) return '#ef4444'   // red
                if (lbl.includes('MODIFIES')) return '#f59e0b'   // amber
                if (lbl.includes('SUPPLEMENTS')) return '#3b82f6' // blue
                if (lbl.includes('OVERLAPS')) return '#a855f7'   // purple
                return '#94a3b8'                                  // default slate
              }}
              linkWidth={(link: any) => {
                const lbl = (link.label || '').toUpperCase()
                const isConflict = ['REPLACES','MODIFIES','SUPPLEMENTS','OVERLAPS'].some(t => lbl.includes(t))
                return isConflict ? 2.5 : 1.5
              }}
              linkDirectionalArrowLength={3.5}
              linkDirectionalArrowRelPos={1}
              linkLabel="label"
              linkCanvasObjectMode={() => 'after'}
              linkCanvasObject={(link: any, ctx: any) => {
                const start = link.source;
                const end = link.target;
                if (typeof start !== 'object' || typeof end !== 'object') return;
                
                const textPos = {
                  x: start.x + (end.x - start.x) / 2,
                  y: start.y + (end.y - start.y) / 2
                };
                
                const relLink = { x: end.x - start.x, y: end.y - start.y };
                let textAngle = Math.atan2(relLink.y, relLink.x);
                if (textAngle > Math.PI / 2) textAngle = -(Math.PI - textAngle);
                if (textAngle < -Math.PI / 2) textAngle = -(-Math.PI - textAngle);
                
                const label = link.label;
                if (!label) return;

                const lbl = label.toUpperCase()
                let labelColor = '#64748b'
                if (lbl.includes('REPLACES')) labelColor = '#ef4444'
                if (lbl.includes('MODIFIES')) labelColor = '#f59e0b'
                if (lbl.includes('SUPPLEMENTS')) labelColor = '#3b82f6'
                if (lbl.includes('OVERLAPS')) labelColor = '#a855f7'
                
                ctx.save();
                ctx.font = '3px Sans-Serif';
                ctx.translate(textPos.x, textPos.y);
                ctx.rotate(textAngle);
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                
                // Add a small background for better readability
                const textWidth = ctx.measureText(label).width;
                ctx.fillStyle = 'rgba(255, 255, 255, 0.8)';
                ctx.fillRect(-textWidth / 2 - 1, -2, textWidth + 2, 4);
                
                ctx.fillStyle = labelColor;
                ctx.fillText(label, 0, 0);
                ctx.restore();
              }}
              onNodeClick={(node) => setSelectedNode(node)}
            />
          )}

          {/* Node Details Panel */}
          {selectedNode && (
            <div className="absolute top-4 right-4 w-80 bg-background border rounded-lg shadow-lg p-4 z-10 flex flex-col max-h-[80vh] overflow-hidden">
              <div className="flex justify-between items-start mb-2 shrink-0">
                <h3 className="font-bold text-lg text-foreground break-words pr-2">{selectedNode.label}</h3>
                <button onClick={() => setSelectedNode(null)} className="text-muted-foreground hover:text-foreground shrink-0 mt-1">
                  <X className="w-4 h-4" />
                </button>
              </div>
              <div className="mb-2 shrink-0 flex flex-wrap gap-1">
                <span className="inline-block px-2 py-1 bg-primary/10 text-primary rounded text-xs font-semibold">
                  {selectedNode.type}
                </span>
                {selectedNode.trang_thai && (
                  <span className={`inline-block px-2 py-1 rounded text-xs font-semibold ${
                    selectedNode.trang_thai === 'con_hieu_luc'
                      ? 'bg-green-100 text-green-700'
                      : selectedNode.trang_thai === 'het_hieu_luc'
                      ? 'bg-red-100 text-red-700'
                      : 'bg-gray-100 text-gray-600'
                  }`}>
                    {selectedNode.trang_thai}
                  </span>
                )}
              </div>
              {(selectedNode.hieu_luc_tu || selectedNode.het_hieu_luc) && (
                <div className="mb-2 shrink-0 text-xs text-muted-foreground space-y-0.5">
                  {selectedNode.hieu_luc_tu && (
                    <div><span className="font-medium">Hiệu lực từ:</span> {selectedNode.hieu_luc_tu}</div>
                  )}
                  {selectedNode.het_hieu_luc && (
                    <div><span className="font-medium">Hết hiệu lực:</span> {selectedNode.het_hieu_luc}</div>
                  )}
                </div>
              )}
              <div className="overflow-y-auto text-sm text-foreground/80 mt-2 whitespace-pre-wrap flex-1">
                {selectedNode.description || "Chưa có thông tin mô tả cho node này."}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default GraphViewer;
