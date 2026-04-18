import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Sparkles, Upload, Send, Download, ZoomIn, ZoomOut, Maximize2, Eye, EyeOff, FileDown, MessageSquare, Layers, RefreshCw, Check, Users, Bell, Loader2, ChevronDown } from 'lucide-react';
import { runTakeoffAI, askTakeoffChat, getRoomColor } from '../mock/mockAI';
import { SAMPLE_PROJECTS } from '../mock/mockData';
import { projectsAPI, uploadsAPI, takeoffAPI, exportAPI } from '../services/api';
import FileUploadZone from '../components/FileUploadZone';
import DrawingRenderer from '../components/DrawingRenderer';

const LAYER_CONFIG = [
  { key: 'rooms', label: 'Rooms', color: '#a78bfa' },     // Purple
  { key: 'doors', label: 'Doors', color: '#10b981' },     // Green
  { key: 'windows', label: 'Windows', color: '#3b82f6' }, // Blue
  { key: 'walls', label: 'Walls', color: '#eab308' },     // Yellow
];

export default function Takeoff() {
  const { id } = useParams();
  const nav = useNavigate();
  const [project, setProject] = useState(null);
  const [drawings, setDrawings] = useState([]);
  const [loadingProject, setLoadingProject] = useState(true);
  const [showUpload, setShowUpload] = useState(false);
  const [status, setStatus] = useState('idle'); // idle, processing, ready
  const [progress, setProgress] = useState({ msg: '', pct: 0 });
  const [detection, setDetection] = useState(null);
  const [layers, setLayers] = useState({ rooms: true, doors: true, windows: true, walls: true });
  const [selectedId, setSelectedId] = useState(null);
  const [tab, setTab] = useState('quantities');
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const dragRef = useRef(null);
  const [selectedDrawing, setSelectedDrawing] = useState(null);
  const [showExportMenu, setShowExportMenu] = useState(false);
  const [exporting, setExporting] = useState(false);


  useEffect(() => {
    fetchProject();
    // eslint-disable-next-line
  }, [id]);

  useEffect(() => {
    if (project) {
      fetchDrawings();
      runAnalysis();
    }
    // eslint-disable-next-line
  }, [project]);

  async function fetchProject() {
    try {
      setLoadingProject(true);
      const response = await projectsAPI.get(id);
      setProject(response.data);
    } catch (error) {
      console.error('Failed to fetch project:', error);
      // Fallback to mock data
      const mockProject = SAMPLE_PROJECTS.find((p) => p.id === id) || SAMPLE_PROJECTS[0];
      setProject(mockProject);
    } finally {
      setLoadingProject(false);
    }
  }

  async function fetchDrawings() {
    try {
      const response = await uploadsAPI.listDrawings(id);
      setDrawings(response.data || []);
    } catch (error) {
      console.error('Failed to fetch drawings:', error);
      setDrawings([]);
    }
  }

  const handleUploadComplete = (newDrawing) => {
    setDrawings((prev) => [newDrawing, ...prev]);
    setShowUpload(false);
    // Auto-select the new drawing
    setSelectedDrawing(newDrawing);
    // Trigger mock AI for this drawing
    runAnalysisForDrawing(newDrawing);
  };

  const runAnalysisForDrawing = async (drawing) => {
    setStatus('processing');
    const result = await runTakeoffAI({
      onProgress: setProgress,
      seed: drawing.id,
    });
    setDetection(result);
    setStatus('ready');
    
    // Save results to database
    try {
      await takeoffAPI.saveResults(drawing.id, {
        detection_data: JSON.stringify(result),
        quantities_data: JSON.stringify(result.summary || {}),
        confidence_scores: JSON.stringify({ avg: 0.95 }),
        processing_time_ms: result.processingTimeMs || 1500,
      });
      console.log('✅ AI results saved to database');
    } catch (error) {
      console.error('Failed to save AI results:', error);
    }
  };

  const selectDrawing = (drawing) => {
    setSelectedDrawing(drawing);
    // Load specific detection results for this drawing
    runAnalysisForDrawing(drawing);
  };

  async function runAnalysis() {
    setStatus('processing'); setDetection(null); setProgress({ msg: 'Starting...', pct: 0 });
    const res = await runTakeoffAI({ onProgress: (s) => setProgress({ msg: s.msg, pct: s.pct }) });
    setDetection(res);
    setStatus('ready');
  }

async function handleExport(format) {
    if (!selectedDrawing && !id) {
      alert('No drawing or project selected');
      return;
    }

    try {
      setExporting(true);
      setShowExportMenu(false);

      let response;
      let filename;

      if (selectedDrawing) {
        // Export specific drawing
        response = await exportAPI.exportDrawing(selectedDrawing.id, format);
        filename = `takeoff_${selectedDrawing.original_filename.split('.')[0]}_${Date.now()}.${format === 'excel' ? 'xlsx' : 'csv'}`;
      } else {
        // Export entire project
        response = await exportAPI.exportProject(id, format);
        filename = `project_${project?.name || 'export'}_${Date.now()}.${format === 'excel' ? 'xlsx' : 'csv'}`;
      }

      // Create blob and download
      const blob = new Blob([response.data], {
        type: format === 'excel' 
          ? 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' 
          : 'text/csv'
      });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);

    } catch (error) {
      console.error('Export error:', error);
      alert(error.response?.data?.detail || 'Failed to export. Please try again.');
    } finally {
      setExporting(false);
    }
  };


  function zoomBy(delta) { setZoom((z) => Math.max(0.5, Math.min(3, z + delta))); }
  function resetView() { setZoom(1); setPan({ x: 0, y: 0 }); }

  function onMouseDown(e) { dragRef.current = { x: e.clientX, y: e.clientY, sx: pan.x, sy: pan.y }; }
  function onMouseMove(e) {
    if (!dragRef.current) return;
    setPan({ x: dragRef.current.sx + (e.clientX - dragRef.current.x), y: dragRef.current.sy + (e.clientY - dragRef.current.y) });
  }
  function onMouseUp() { dragRef.current = null; }

  const selected = useMemo(() => {
    if (!detection || !selectedId) return null;
    return [...detection.rooms, ...detection.doors, ...detection.windows].find((x) => x.id === selectedId);
  }, [detection, selectedId]);

  return (
    <div className="min-h-screen flex flex-col bg-slate-900">
      {/* Top bar */}
      <header className="h-14 bg-slate-900 text-white border-b border-slate-800 flex items-center px-4 gap-4 flex-shrink-0">
        <button onClick={() => nav('/app')} className="flex items-center gap-2 text-sm text-slate-300 hover:text-white">
          <ArrowLeft className="w-4 h-4" /> <span>Dashboard</span>
        </button>
        <div className="w-px h-5 bg-slate-700" />
        <div className="min-w-0">
          <div className="text-sm font-semibold text-white truncate">{project?.name || 'Loading...'}</div>
          <div className="text-[10px] mono text-slate-400 truncate">
            {drawings.length > 0 ? `${drawings.length} drawing${drawings.length > 1 ? 's' : ''} · ` : ''}
            Scale 1/8" = 1'-0"
          </div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <div className="flex items-center -space-x-1.5">
            {['AR', 'PK', 'JL'].map((x, i) => (
              <div key={x} className={`w-7 h-7 rounded-full border-2 border-slate-900 flex items-center justify-center text-[10px] font-semibold text-white`} style={{ background: ['#6366f1', '#8b5cf6', '#06b6d4'][i] }}>{x}</div>
            ))}
            <button className="w-7 h-7 rounded-full border-2 border-slate-900 bg-slate-700 flex items-center justify-center text-slate-300 ml-1"><Users className="w-3 h-3" /></button>
          </div>
          <div className="w-px h-5 bg-slate-700" />
          <button onClick={() => setShowUpload(!showUpload)} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-xs font-medium text-white"><Upload className="w-3.5 h-3.5" /> Upload Blueprint</button>
          <button className="w-9 h-9 rounded-lg hover:bg-slate-800 flex items-center justify-center text-slate-400"><Bell className="w-4 h-4" /></button>
          <button onClick={runAnalysis} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-medium text-white border border-slate-700"><RefreshCw className="w-3.5 h-3.5" /> Re-run AI</button>
          {/* Export dropdown */}
          <div className="relative">
            <button 
              onClick={() => setShowExportMenu(!showExportMenu)}
              disabled={exporting}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white text-slate-900 text-xs font-medium hover:bg-slate-100 disabled:opacity-50"
            >
              {exporting ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" /> Exporting...
                </>
              ) : (
                <>
                  <FileDown className="w-3.5 h-3.5" /> Export <ChevronDown className="w-3 h-3" />
                </>
              )}
            </button>
            
            {showExportMenu && !exporting && (
              <div className="absolute right-0 top-full mt-1 w-40 bg-white rounded-lg shadow-xl border border-slate-200 py-1 z-50">
                <button
                  onClick={() => handleExport('excel')}
                  className="w-full text-left px-3 py-2 text-xs text-slate-700 hover:bg-slate-50 flex items-center gap-2"
                >
                  <FileDown className="w-3.5 h-3.5" /> Export as Excel
                </button>
                <button
                  onClick={() => handleExport('csv')}
                  className="w-full text-left px-3 py-2 text-xs text-slate-700 hover:bg-slate-50 flex items-center gap-2"
                >
                  <FileDown className="w-3.5 h-3.5" /> Export as CSV
                </button>
        </div>
            )}
            </div>
            </div>
      </header>

      <div className="flex-1 grid grid-cols-[260px_1fr_340px] min-h-0">
        {/* Left rail: layers + sheets */}
        <aside className="bg-slate-900 text-slate-200 border-r border-slate-800 p-4 overflow-auto">
          {/* Upload Zone */}
          {showUpload && (
            <div className="mb-4 p-3 rounded-lg bg-slate-800 border border-slate-700">
              <div className="text-xs font-semibold text-white mb-2">Upload Blueprints</div>
              <FileUploadZone projectId={id} onUploadComplete={handleUploadComplete} />
            </div>
          )}

          {/* Drawings List */}
          {drawings.length > 0 && (
            <>
              <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-2">Drawings</div>
              <div className="space-y-0.5 mb-4">
                {drawings.map((drawing) => (
                  <button
                    key={drawing.id}
                    onClick={() => selectDrawing(drawing)}
                    className={`w-full text-left px-2 py-1.5 rounded text-xs ${
                      selectedDrawing?.id === drawing.id ? 'bg-indigo-500/20 text-indigo-300 font-medium' : 'text-slate-400 hover:bg-slate-800'
                    }`}
                  >
                    <div className="truncate">{drawing.sheet_name || drawing.original_filename}</div>
                    <div className="text-[10px] text-slate-500">{drawing.file_type} · {(drawing.file_size / 1024 / 1024).toFixed(1)}MB</div>
                  </button>
                ))}
              </div>
            </>
          )}

          <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-2">Mock Sheets</div>
          <div className="space-y-0.5">
            {['A-001 Cover', 'A-101 Level 12', 'A-102 Level 13', 'A-201 Elevations', 'M-101 HVAC', 'E-101 Power'].map((s, i) => (
              <button key={s} className={`w-full text-left px-2 py-1.5 rounded text-xs ${i === 1 && drawings.length === 0 ? 'bg-indigo-500/20 text-indigo-300 font-medium' : 'text-slate-400 hover:bg-slate-800'}`}>{s}</button>
            ))}
          </div>

          <div className="mt-6 text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-2 flex items-center gap-1.5"><Layers className="w-3 h-3" /> Detection layers</div>
          <div className="space-y-1">
            {LAYER_CONFIG.map((l) => {
              const on = layers[l.key];
              const count = detection ? (detection[l.key]?.length ?? 0) : 0;
              return (
                <button key={l.key} onClick={() => setLayers({ ...layers, [l.key]: !on })} className={`w-full flex items-center justify-between px-2 py-1.5 rounded text-xs ${on ? 'bg-slate-800 text-slate-200' : 'text-slate-500 hover:bg-slate-800/60'}`}>
                  <span className="flex items-center gap-2"><span className="w-2 h-2 rounded-sm" style={{ background: l.color }} />{l.label}</span>
                  <span className="flex items-center gap-1.5">
                    <span className="mono text-[11px]">{count || '—'}</span>
                    {on ? <Eye className="w-3 h-3" /> : <EyeOff className="w-3 h-3" />}
                  </span>
                </button>
              );
            })}
          </div>

          <div className="mt-6 text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-2">Revisions</div>
          <div className="space-y-1">
            {[['Rev C', 'Current', true], ['Rev B', '3 days ago', false], ['Rev A', 'Mar 14', false]].map(([r, t, cur]) => (
              <button key={r} className={`w-full flex items-center justify-between px-2 py-1.5 rounded text-xs ${cur ? 'bg-slate-800 text-slate-200' : 'text-slate-500 hover:bg-slate-800/60'}`}>
                <span>{r}</span>
                <span className="text-[10px] mono">{t}</span>
              </button>
            ))}
          </div>
        </aside>

        {/* Canvas */}
        <main className="relative bg-slate-100 overflow-hidden" onMouseMove={onMouseMove} onMouseUp={onMouseUp} onMouseLeave={onMouseUp}>
          {status === 'processing' && <ProcessingOverlay progress={progress} />}

          {selectedDrawing ? (
            /* Render real uploaded file */
            <div className="absolute inset-0">
              <DrawingRenderer drawing={selectedDrawing} onLoad={(data) => console.log('Drawing loaded:', data)} />
            </div>
          ) : (
            /* Mock floor plan canvas */
            <div className="absolute inset-0 flex items-center justify-center" onMouseDown={onMouseDown}>
              <div style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`, transition: dragRef.current ? 'none' : 'transform 180ms ease' }}>
                <CanvasFull detection={detection} layers={layers} selectedId={selectedId} onSelect={setSelectedId} />
              </div>
            </div>
          )}

          {/* Canvas toolbar */}
          <div className="absolute bottom-4 left-1/2 -translate-x-1/2 flex items-center gap-1 p-1 rounded-xl bg-white border border-slate-200 shadow-lg">
            <ToolBtn onClick={() => zoomBy(-0.2)}><ZoomOut className="w-4 h-4" /></ToolBtn>
            <div className="mono text-xs px-2 text-slate-700 w-14 text-center">{Math.round(zoom * 100)}%</div>
            <ToolBtn onClick={() => zoomBy(0.2)}><ZoomIn className="w-4 h-4" /></ToolBtn>
            <div className="w-px h-5 bg-slate-200 mx-1" />
            <ToolBtn onClick={resetView}><Maximize2 className="w-4 h-4" /></ToolBtn>
          </div>

          {/* Status chip */}
          {status === 'ready' && (
            <div className="absolute top-4 left-4 flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white border border-slate-200 shadow-sm text-xs font-medium text-slate-800">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
              AI complete · {detection.processingTimeMs}ms · {detection.rooms.length + detection.doors.length + detection.windows.length} detections
            </div>
          )}

          {/* Selection hover card */}
          {selected && <DetectionHoverCard item={selected} onClose={() => setSelectedId(null)} />}
        </main>

        {/* Right panel */}
        <aside className="bg-white border-l border-slate-200 flex flex-col min-h-0">
          <div className="flex border-b border-slate-200">
            {[
              { key: 'quantities', label: 'Quantities' },
              { key: 'chat', label: 'Chat' },
              { key: 'summary', label: 'Summary' },
            ].map((t) => (
              <button key={t.key} onClick={() => setTab(t.key)} className={`flex-1 py-3 text-sm font-medium border-b-2 ${tab === t.key ? 'border-slate-900 text-slate-900' : 'border-transparent text-slate-500 hover:text-slate-800'}`}>{t.label}</button>
            ))}
          </div>
          <div className="flex-1 overflow-auto">
            {tab === 'quantities' && <QuantitiesPanel detection={detection} />}
            {tab === 'chat' && <ChatPanel detection={detection} />}
            {tab === 'summary' && <SummaryPanel detection={detection} />}
          </div>
        </aside>
      </div>
    </div>
  );
}

function ToolBtn({ children, onClick }) {
  return <button onClick={onClick} className="w-8 h-8 rounded-md hover:bg-slate-100 flex items-center justify-center text-slate-700">{children}</button>;
}

function ProcessingOverlay({ progress }) {
  return (
    <div className="absolute inset-0 z-20 flex items-center justify-center bg-slate-100/90 backdrop-blur-sm">
      <div className="text-center max-w-md w-full px-6">
        <div className="relative mx-auto w-16 h-16">
          <div className="absolute inset-0 rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-500 shadow-lg shadow-indigo-500/30 flex items-center justify-center">
            <Sparkles className="w-6 h-6 text-white animate-pulse" />
          </div>
          <div className="absolute inset-0 rounded-2xl bg-indigo-400 animate-pulse-ring" />
        </div>
        <h3 className="mt-5 text-lg font-semibold text-slate-900">Running AI takeoff</h3>
        <p className="mt-1 text-sm text-slate-600 h-5">{progress.msg}</p>
        <div className="mt-5 h-1.5 rounded-full bg-slate-200 overflow-hidden">
          <div className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-violet-500" style={{ width: `${progress.pct}%`, transition: 'width 400ms ease' }} />
        </div>
        <div className="mt-2 text-xs mono text-slate-500">{progress.pct}%</div>
      </div>
    </div>
  );
}

function CanvasFull({ detection, layers, selectedId, onSelect }) {
  return (
    <svg width="800" height="680" viewBox="0 0 800 680" className="bg-white rounded-lg shadow-2xl shadow-slate-900/20 border border-slate-200">
      <defs>
        <pattern id="grid2" width="40" height="40" patternUnits="userSpaceOnUse">
          <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#eef2f7" strokeWidth="0.5" />
        </pattern>
      </defs>
      <rect width="800" height="680" fill="#fafbff" />
      <rect width="800" height="680" fill="url(#grid2)" />
      {/* Walls - Yellow */}
      <g stroke="#eab308" strokeWidth="4" fill="none" opacity={layers.walls ? 1 : 0.15}>
        <rect x="60" y="60" width="660" height="560" />
      </g>
      <g stroke="#ca8a04" strokeWidth="2" fill="none" opacity={layers.walls ? 1 : 0.15}>
        <line x1="300" y1="60" x2="300" y2="200" />
        <line x1="60" y1="200" x2="300" y2="200" />
        <line x1="260" y1="200" x2="260" y2="440" />
        <line x1="340" y1="200" x2="340" y2="440" />
        <line x1="340" y1="340" x2="720" y2="340" />
        <line x1="560" y1="200" x2="560" y2="440" />
        <line x1="60" y1="370" x2="260" y2="370" />
        <line x1="340" y1="440" x2="720" y2="440" />
        <line x1="340" y1="600" x2="560" y2="600" />
        <line x1="260" y1="510" x2="340" y2="510" />
      </g>

      {/* Rooms */}
      {detection && layers.rooms && detection.rooms.map((r) => {
        const [x1, y1, x2, y2] = r.bbox;
        const sel = selectedId === r.id;
        return (
          <g key={r.id}>
            <rect
              className="detection-box"
              x={x1 + 4} y={y1 + 4} width={x2 - x1 - 8} height={y2 - y1 - 8}
              fill={getRoomColor(r.label)} fillOpacity={sel ? 0.5 : 0.22}
              stroke={getRoomColor(r.label)} strokeWidth={sel ? 3 : 1.5}
              style={{ cursor: 'pointer' }}
              onClick={(e) => { e.stopPropagation(); onSelect(r.id); }}
            />
            <g transform={`translate(${(x1 + x2) / 2},${(y1 + y2) / 2})`} style={{ pointerEvents: 'none' }}>
              <text textAnchor="middle" fontSize="12" fontWeight="600" fill="#1e293b">{r.label}</text>
              <text y="14" textAnchor="middle" fontSize="9" fill="#64748b" fontFamily="JetBrains Mono, monospace">{r.area} sf · {Math.round(r.confidence * 100)}%</text>
            </g>
          </g>
        );
      })}

      {/* Doors - Green */}
      {detection && layers.doors && detection.doors.map((d) => (
        <g key={d.id} transform={`translate(${d.x},${d.y}) rotate(${d.rotation || 0})`} style={{ cursor: 'pointer' }} onClick={(e) => { e.stopPropagation(); onSelect(d.id); }}>
          <rect x="-4" y="-14" width="8" height="28" fill="#fff" />
          <path d={`M 0 -14 A ${d.width} ${d.width} 0 0 1 ${d.width} 14`} stroke={selectedId === d.id ? '#059669' : '#10b981'} strokeWidth={selectedId === d.id ? 3 : 1.5} fill="none" />
          <circle cx="0" cy="-14" r="3" fill="#10b981" />
        </g>
      ))}

      {/* Windows - Blue */}
      {detection && layers.windows && detection.windows.map((w) => (
        <g key={w.id} transform={`translate(${w.x},${w.y}) rotate(${w.rotation || 0})`} style={{ cursor: 'pointer' }} onClick={(e) => { e.stopPropagation(); onSelect(w.id); }}>
          <rect x="0" y="-4" width={w.width} height="8" fill={selectedId === w.id ? '#2563eb' : '#3b82f6'} stroke="#1d4ed8" strokeWidth="1" />
          <line x1="0" y1="0" x2={w.width} y2="0" stroke="#fff" strokeWidth="1" />
        </g>
      ))}
    </svg>
  );
}

function DetectionHoverCard({ item, onClose }) {
  const label = item.label || (item.id?.startsWith('d') ? 'Door' : item.id?.startsWith('w') ? 'Window' : 'Element');
  return (
    <div className="absolute top-4 right-4 w-64 rounded-xl bg-white border border-slate-200 shadow-xl p-4 z-10 animate-fade-up">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">Detection</div>
          <div className="mt-0.5 text-base font-semibold text-slate-900">{label}</div>
        </div>
        <button onClick={onClose} className="text-slate-400 hover:text-slate-700 text-xs">Close</button>
      </div>
      <div className="mt-3 space-y-1.5 text-xs">
        <div className="flex justify-between"><span className="text-slate-500">ID</span><span className="mono text-slate-900">{item.id}</span></div>
        {item.area && <div className="flex justify-between"><span className="text-slate-500">Area</span><span className="mono text-slate-900">{item.area} sf</span></div>}
        {item.width && <div className="flex justify-between"><span className="text-slate-500">Width</span><span className="mono text-slate-900">{item.width}"</span></div>}
        <div className="flex justify-between"><span className="text-slate-500">Confidence</span><span className="mono text-emerald-600 font-semibold">{Math.round(item.confidence * 100)}%</span></div>
      </div>
      <div className="mt-4 flex gap-1.5">
        <button className="flex-1 py-1.5 text-xs font-medium text-white bg-slate-900 rounded-md hover:bg-slate-800">Accept</button>
        <button className="flex-1 py-1.5 text-xs font-medium text-slate-700 bg-slate-100 rounded-md hover:bg-slate-200">Edit</button>
      </div>
    </div>
  );
}

function QuantitiesPanel({ detection }) {
  const [filter, setFilter] = useState('All');
  if (!detection) return <div className="p-6 text-sm text-slate-500">Quantities will appear once AI finishes.</div>;
  const trades = ['All', ...Array.from(new Set(detection.quantities.map((q) => q.trade)))];
  const rows = detection.quantities.filter((q) => filter === 'All' || q.trade === filter);
  const total = rows.length;
  return (
    <div className="p-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">Quantities</h3>
          <p className="text-xs text-slate-500 mt-0.5">{total} line items · filter by trade</p>
        </div>
        <button className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium text-white bg-slate-900 rounded-md hover:bg-slate-800"><Download className="w-3.5 h-3.5" /> Excel</button>
      </div>
      <div className="mt-3 flex flex-wrap gap-1">
        {trades.map((t) => (
          <button key={t} onClick={() => setFilter(t)} className={`px-2.5 py-1 text-[11px] font-medium rounded-md ${filter === t ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'}`}>{t}</button>
        ))}
      </div>
      <div className="mt-4 space-y-1">
        {rows.map((q, i) => (
          <div key={i} className="flex items-center justify-between gap-3 px-3 py-2.5 rounded-lg hover:bg-slate-50">
            <div className="min-w-0">
              <div className="text-sm text-slate-900 truncate">{q.item}</div>
              <div className="text-[11px] text-slate-500">{q.trade}</div>
            </div>
            <div className="text-right flex-shrink-0">
              <div className="mono text-sm font-semibold text-slate-900">{q.quantity.toLocaleString()}</div>
              <div className="text-[11px] text-slate-500">{q.unit}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ChatPanel({ detection }) {
  const [messages, setMessages] = useState([
    { role: 'assistant', text: 'Hi! I’ve parsed this sheet. Ask me anything about rooms, doors, windows, quantities or scope.', time: 'now' },
  ]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const endRef = useRef(null);

  async function send(prompt) {
    const q = (prompt ?? input).trim();
    if (!q || sending) return;
    setMessages((m) => [...m, { role: 'user', text: q, time: 'now' }]);
    setInput(''); setSending(true);
    const res = await askTakeoffChat(q);
    setMessages((m) => [...m, { role: 'assistant', text: res.answer, time: 'now', citations: res.citations }]);
    setSending(false);
  }

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages, sending]);

  const suggestions = ['How many rooms?', 'Total paintable area?', 'Generate a scope of work', 'Any door irregularities?'];

  return (
    <div className="h-full flex flex-col">
      <div className="flex-1 overflow-auto p-4 space-y-3">
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm ${m.role === 'user' ? 'bg-slate-900 text-white rounded-br-md' : 'bg-slate-100 text-slate-900 rounded-bl-md'}`}>
              {m.text}
              {m.citations && <div className="mt-2 flex flex-wrap gap-1">{m.citations.map((c) => <span key={c} className="text-[10px] px-1.5 py-0.5 rounded bg-white/60 text-slate-600 mono">{c}</span>)}</div>}
            </div>
          </div>
        ))}
        {sending && (
          <div className="flex justify-start">
            <div className="rounded-2xl px-3.5 py-2.5 bg-slate-100 text-slate-600 text-sm flex items-center gap-2"><Loader2 className="w-3.5 h-3.5 animate-spin" /> Thinking...</div>
          </div>
        )}
        <div ref={endRef} />
      </div>
      <div className="p-3 border-t border-slate-200">
        <div className="flex flex-wrap gap-1.5 mb-2">
          {suggestions.map((s) => (<button key={s} onClick={() => send(s)} className="px-2.5 py-1 text-[11px] rounded-md bg-slate-100 text-slate-700 hover:bg-slate-200">{s}</button>))}
        </div>
        <form onSubmit={(e) => { e.preventDefault(); send(); }} className="flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 focus-within:border-slate-500 focus-within:ring-2 focus-within:ring-slate-200">
          <MessageSquare className="w-4 h-4 text-slate-400" />
          <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask your plan anything..." className="flex-1 text-sm outline-none bg-transparent" />
          <button type="submit" disabled={!input.trim() || sending} className="w-7 h-7 rounded-md bg-slate-900 text-white flex items-center justify-center disabled:opacity-40"><Send className="w-3.5 h-3.5" /></button>
        </form>
      </div>
    </div>
  );
}

function SummaryPanel({ detection }) {
  if (!detection) return <div className="p-6 text-sm text-slate-500">Waiting for AI...</div>;
  const s = detection.summary;
  return (
    <div className="p-4">
      <h3 className="text-sm font-semibold text-slate-900">Summary</h3>
      <p className="text-xs text-slate-500 mt-0.5">Sheet {detection.sheet}</p>
      <div className="mt-4 grid grid-cols-2 gap-2">
        {[
          ['Rooms', s.rooms, 'text-indigo-700'], 
          ['Doors', s.doors, 'text-cyan-700'], 
          ['Windows', s.windows, 'text-amber-700'], 
          ['Walls', s.walls, 'text-rose-700'], 
          ['Total area', `${s.totalArea.toLocaleString()} sf`, 'text-violet-700'], 
          ['Scale', detection.scale, 'text-emerald-700']
        ].map(([k, v, colorClass]) => (
          <div key={k} className="rounded-lg border border-slate-200 p-3">
            <div className="text-[11px] text-slate-500">{k}</div>
            <div className={`mt-1 text-sm font-semibold ${colorClass}`}>{v}</div>
          </div>
        ))}
      </div>

      <h4 className="mt-6 text-xs font-semibold uppercase tracking-wider text-slate-500">Confidence</h4>
      <div className="mt-3 space-y-2">
        {[['Rooms segmentation', 0.96], ['Door classification', 0.94], ['Window classification', 0.93], ['Auto-scale detection', 0.99]].map(([l, v]) => (
          <div key={l}>
            <div className="flex items-center justify-between text-xs"><span className="text-slate-700">{l}</span><span className="mono text-slate-900 font-semibold">{Math.round(v * 100)}%</span></div>
            <div className="mt-1 h-1 rounded-full bg-slate-100 overflow-hidden"><div className="h-full bg-gradient-to-r from-indigo-500 to-emerald-500" style={{ width: `${v * 100}%` }} /></div>
          </div>
        ))}
      </div>

      <h4 className="mt-6 text-xs font-semibold uppercase tracking-wider text-slate-500">Next actions</h4>
      <ul className="mt-3 space-y-2">
        {['Review hallway door swing on Rev C', 'Confirm Master bathroom fixture count', 'Merge drywall + painting exports for GC'].map((a) => (
          <li key={a} className="flex items-start gap-2 text-sm text-slate-700"><Check className="w-4 h-4 text-indigo-600 mt-0.5" /> {a}</li>
        ))}
      </ul>
    </div>
  );
}
<div className="bg-gradient-to-r from-indigo-500 to-emerald-500 h-2 rounded-full" style={{ width: `${v * 100}%` }} />
</div>
          </div>
        ))}
      </div>

      <h4 className="mt-6 text-xs font-semibold uppercase tracking-wider text-slate-500">Next actions</h4>
      <ul className="mt-3 space-y-2">
        {['Review hallway door swing on Rev C', 'Confirm Master bathroom fixture count', 'Merge drywall + painting exports for GC'].map((a) => (
          <li key={a} className="flex items-start gap-2 text-sm text-slate-700"><Check className="w-4 h-4 text-indigo-600 mt-0.5" /> {a}</li>
        ))}
      </ul>
    </div>
  );
}

