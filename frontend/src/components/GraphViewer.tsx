import { useEffect, useRef, useState } from 'react';
import ForceGraph2D, { GraphData } from 'react-force-graph-2d';
import { X, Maximize2 } from 'lucide-react';
import client from '../api/client';

interface LegalNode {
  id: string | number;
  label: string;
  type: string;
  description: string;
  trang_thai?: string;
  hieu_luc_tu?: string;
  het_hieu_luc?: string;
  source_location?: string;
  evidence?: string;
  extraction_method?: string;
  file_path?: string;
}

interface LegalLink {
  label: string;
  directed: boolean;
  description?: string;
  evidence?: string;
  source_location?: string;
  extraction_method?: string;
}

type LegalGraphData = GraphData<LegalNode, LegalLink> & { is_truncated?: boolean };

const nodeColors: Record<string, string> = {
  VanBanPhapLuat: '#7c3aed', Chuong: '#6366f1', Muc: '#818cf8', Dieu: '#2563eb',
  Khoan: '#0284c7', Diem: '#0891b2', ChuThe: '#059669', KhaiNiem: '#d97706',
  QuyTac: '#dc2626', DieuKien: '#c026d3',
};
const edgeColors: Record<string, string> = {
  CONTAINS: '#64748b', REFERENCES: '#0891b2', EXCEPTION_TO: '#c026d3',
  ENDS_EFFECT_OF: '#ef4444', AMENDS: '#f59e0b', REPLACES: '#ef4444',
  MODIFIES: '#f59e0b', SUPPLEMENTS: '#3b82f6', OVERLAPS: '#a855f7',
};

function tooltip(text: string): string {
  const span = document.createElement('span');
  span.textContent = text;
  return span.outerHTML;
}

export function GraphViewer({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<LegalGraphData>({ nodes: [], links: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selectedNode, setSelectedNode] = useState<LegalNode | null>(null);
  const [selectedEdgeIndex, setSelectedEdgeIndex] = useState<number | null>(null);
  const container = useRef<HTMLDivElement>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const [size, setSize] = useState({ width: 800, height: 600 });
  const selectedEdge = selectedEdgeIndex === null ? null : data.links[selectedEdgeIndex];
  const details = selectedNode || selectedEdge;

  useEffect(() => {
    const controller = new AbortController();
    client.get<LegalGraphData>('/graph', { signal: controller.signal })
      .then(response => setData(response.data))
      .catch(() => { if (!controller.signal.aborted) setError('Không tải được đồ thị. Hãy đóng và mở lại để thử lại.'); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    dialog.current?.showModal();
    const observer = new ResizeObserver(entries => {
      const rect = entries[0].contentRect;
      setSize({ width: rect.width, height: rect.height });
    });
    if (container.current) observer.observe(container.current);
    return () => observer.disconnect();
  }, []);

  function closeDetails() {
    setSelectedNode(null);
    setSelectedEdgeIndex(null);
  }

  return (
    <dialog ref={dialog} onCancel={onClose} aria-labelledby="legal-graph-title"
      className="m-auto w-[95vw] max-w-6xl h-[90vh] p-0 rounded-xl bg-card text-foreground border shadow-2xl backdrop:bg-black/60">
      <div className="flex flex-col h-full overflow-hidden">
        <div className="flex items-center gap-2 p-4 border-b">
          <Maximize2 className="w-5 h-5 text-primary" />
          <h2 id="legal-graph-title" className="text-lg font-semibold">Đồ thị pháp luật</h2>
          {!loading && <span className="text-xs text-muted-foreground">{data.nodes.length} đỉnh · {data.links.length} cạnh</span>}
          <button autoFocus aria-label="Đóng đồ thị" onClick={onClose} className="ml-auto p-2 rounded hover:bg-muted"><X className="w-5 h-5" /></button>
        </div>
        <div className="flex flex-wrap gap-2 p-2 border-b">
          <select aria-label="Xem chi tiết đỉnh" className="min-w-0 max-w-full border rounded bg-background p-1 text-sm" value={selectedNode?.id || ''}
            onChange={event => { setSelectedNode(data.nodes.find(node => String(node.id) === event.target.value) || null); setSelectedEdgeIndex(null); }}>
            <option value="">Chọn đỉnh để xem nguồn</option>
            {data.nodes.map(node => <option key={node.id} value={node.id}>{node.type}: {node.label}</option>)}
          </select>
          <select aria-label="Xem chi tiết cạnh" className="min-w-0 max-w-full border rounded bg-background p-1 text-sm" value={selectedEdgeIndex ?? ''}
            onChange={event => { setSelectedEdgeIndex(event.target.value === '' ? null : Number(event.target.value)); setSelectedNode(null); }}>
            <option value="">Chọn cạnh để xem bằng chứng</option>
            {data.links.map((link, index) => <option key={index} value={index}>{index + 1}. {link.label}</option>)}
          </select>
          <p className="text-xs text-muted-foreground self-center">Chỉ vẽ mũi tên khi xác định được chiều pháp lý.</p>
          {data.is_truncated && <p role="status" className="text-xs text-amber-700">Đang hiển thị một phần đồ thị do giới hạn số đỉnh.</p>}
        </div>
        <div ref={container} className="flex-1 min-h-0 relative bg-slate-50 dark:bg-slate-900">
          {loading ? <p role="status" className="p-4">Đang tải đồ thị…</p>
            : error ? <p role="alert" className="p-4 text-red-600">{error}</p>
            : data.nodes.length === 0 ? <p className="p-4">Chưa có dữ liệu. Hãy tải tài liệu lên trước.</p>
            : <ForceGraph2D<LegalNode, LegalLink>
              width={size.width} height={size.height} graphData={data}
              nodeLabel={node => tooltip(node.type + ': ' + node.label)}
              nodeColor={node => nodeColors[node.type] || '#64748b'} nodeRelSize={6}
              linkColor={link => edgeColors[link.label] || '#94a3b8'}
              linkWidth={link => ['ENDS_EFFECT_OF', 'AMENDS', 'REPLACES', 'MODIFIES'].includes(link.label) ? 2.5 : 1.5}
              linkDirectionalArrowLength={link => link.directed ? 3.5 : 0} linkDirectionalArrowRelPos={1}
              linkLabel={link => tooltip(link.label + (link.directed ? '' : ' (chưa xác định chiều)'))}
              linkCanvasObjectMode={() => 'after'}
              linkCanvasObject={(link, ctx) => {
                const start = link.source;
                const end = link.target;
                if (typeof start !== 'object' || typeof end !== 'object' || !start || !end) return;
                if (start.x === undefined || start.y === undefined || end.x === undefined || end.y === undefined) return;
                if (!link.label) return;
                let angle = Math.atan2(end.y - start.y, end.x - start.x);
                if (angle > Math.PI / 2) angle -= Math.PI;
                if (angle < -Math.PI / 2) angle += Math.PI;
                ctx.save();
                ctx.translate((start.x + end.x) / 2, (start.y + end.y) / 2);
                ctx.rotate(angle);
                ctx.font = '3px sans-serif';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                const width = ctx.measureText(link.label).width;
                ctx.fillStyle = 'rgba(255,255,255,0.9)';
                ctx.fillRect(-width / 2 - 1, -2, width + 2, 4);
                ctx.fillStyle = edgeColors[link.label] || '#64748b';
                ctx.fillText(link.label, 0, 0);
                ctx.restore();
              }}
              onNodeClick={node => { setSelectedNode(node); setSelectedEdgeIndex(null); }}
              onLinkClick={link => { setSelectedEdgeIndex(data.links.indexOf(link)); setSelectedNode(null); }}
            />}
          {details && (
            <aside aria-label="Chi tiết đồ thị" className="absolute top-4 right-4 w-80 max-w-[90%] max-h-[80%] overflow-y-auto bg-background border rounded-lg shadow-lg p-4">
              <button aria-label="Đóng chi tiết" onClick={closeDetails} className="float-right p-1"><X className="w-4 h-4" /></button>
              <h3 className="font-semibold break-words">{details.label}</h3>
              {selectedNode && <p className="text-sm">{selectedNode.type}</p>}
              {selectedNode?.trang_thai && <p className="text-sm">Trạng thái: {selectedNode.trang_thai}</p>}
              {selectedNode?.hieu_luc_tu && <p className="text-sm">Hiệu lực từ: {selectedNode.hieu_luc_tu}</p>}
              {selectedNode?.het_hieu_luc && <p className="text-sm">Hết hiệu lực: {selectedNode.het_hieu_luc}</p>}
              {selectedNode?.file_path && <p className="text-xs break-words">Nguồn: {selectedNode.file_path}</p>}
              {selectedEdge && <p className="text-xs">{selectedEdge.directed ? 'Đã xác định chiều' : 'Chưa xác định chiều'}</p>}
              <p className="text-xs text-muted-foreground break-words">{details.source_location}</p>
              <p className="text-xs text-muted-foreground">Trích xuất: {details.extraction_method || 'Chưa xác định'}</p>
              <p className="mt-2 text-sm whitespace-pre-wrap break-words">{details.description || 'Chưa có mô tả.'}</p>
              {details.evidence && <blockquote className="mt-2 border-l-2 pl-2 text-sm whitespace-pre-wrap break-words">{details.evidence}</blockquote>}
            </aside>
          )}
        </div>
      </div>
    </dialog>
  );
}
