import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Sparkles, Upload, Send, Download, ZoomIn, ZoomOut, Maximize2, Eye, EyeOff, FileDown, MessageSquare, Layers, RefreshCw, Check, Users, Bell, Loader2, ChevronDown, Ruler, X, MousePointer2, Tag, Plus, Trash2, Search as SearchIcon, GitCompare } from 'lucide-react';
import { runTakeoffAI, askTakeoffChat, getRoomColor } from '../mock/mockAI';
import { SAMPLE_PROJECTS } from '../mock/mockData';
import { projectsAPI, uploadsAPI, takeoffAPI, exportAPI, scaleAPI, conditionsAPI, correctionsAPI, chatAPI, searchAPI, compareAPI } from '../services/api';
import FileUploadZone from '../components/FileUploadZone';
import DrawingRenderer from '../components/DrawingRenderer';
import { useAnnotationStore } from '../annotations/useAnnotationStore';
import { boundsOf, rectsIntersect } from '../annotations/geometry';

// AIA Uniform Drawing System discipline colors, matching
// ai/title_block_ocr.py's DISCIPLINE_CODES — just enough to give the
// Drawings sidebar a quick visual scan across a multi-sheet plan set.
const DISCIPLINE_COLORS = {
  A: '#818cf8', AD: '#a5b4fc', AS: '#a5b4fc',
  S: '#94a3b8', C: '#84cc16', L: '#22c55e',
  M: '#f59e0b', E: '#eab308', P: '#38bdf8', FP: '#f87171',
  T: '#a855f7', G: '#64748b', I: '#ec4899', Q: '#14b8a6',
};

const ANNOTATION_TYPES = [
  { value: 'area', label: 'Area (sf)' },
  { value: 'line', label: 'Line (lf)' },
  { value: 'count', label: 'Count (ea)' },
];

const LAYER_CONFIG = [
  { key: 'rooms', label: 'Rooms', color: '#a78bfa' },
  { key: 'doors', label: 'Doors', color: '#10b981' },
  { key: 'windows', label: 'Windows', color: '#3b82f6' },
  { key: 'walls', label: 'Walls', color: '#eab308' },
];

export default function Takeoff() {
  const { id } = useParams();
  const nav = useNavigate();
  const [project, setProject] = useState(null);
  const [drawings, setDrawings] = useState([]);
  const [loadingProject, setLoadingProject] = useState(true);
  const [showUpload, setShowUpload] = useState(false);
  const [status, setStatus] = useState('idle');
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
  // Unified annotation store (Milestone 0): AI detections are migrated into
  // this same model manual edits will use later. No rendering wired to it yet.
  const annotationStore = useAnnotationStore();

  // Scale calibration — persisted per Sheet (Drawing). See routes/scale_routes.py.
  const [scaleInfo, setScaleInfo] = useState(null);
  const [calibrating, setCalibrating] = useState(false);
  const [pendingCalPoints, setPendingCalPoints] = useState(null); // {point1, point2} awaiting a distance
  const [calibratingBusy, setCalibratingBusy] = useState(false);
  const [suggestionDismissed, setSuggestionDismissed] = useState(false);

  // Conditions + box-select assignment. See routes/condition_routes.py.
  const [conditions, setConditions] = useState([]);
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState([]);
  const [contextMenu, setContextMenu] = useState(null); // {x, y} screen position
  const [editingCondition, setEditingCondition] = useState(null); // Condition object being edited, or null

  const [revisions, setRevisions] = useState([]);
  const [compareTarget, setCompareTarget] = useState(null); // revision entry being compared against selectedDrawing
  const [compareResult, setCompareResult] = useState(null);
  const [compareLoading, setCompareLoading] = useState(false);
  const [compareError, setCompareError] = useState(null);

  useEffect(() => {
    fetchProject();
    // eslint-disable-next-line
  }, [id]);

  useEffect(() => {
    if (project) {
      fetchDrawings();
      fetchConditions();
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

  // Plan-set ingestion (memory/TOGAL_PARITY_REAUDIT.md #13): a multi-page
  // PDF upload returns one Drawing per sheet — all of them join the
  // sidebar list, but only the first is selected/analyzed by default,
  // same as a single-file upload always has been.
  const handleUploadComplete = (newDrawings) => {
    setDrawings((prev) => [...newDrawings, ...prev]);
    setShowUpload(false);
    const primary = newDrawings[0];
    setSelectedDrawing(primary);
    setSuggestionDismissed(false);
    fetchScaleInfo(primary.id);
    fetchRevisions(primary.id);
    runAnalysisForDrawing(primary);
  };

  async function fetchRevisions(drawingId) {
    try {
      const res = await compareAPI.listRevisions(drawingId);
      setRevisions(res.data || []);
    } catch (error) {
      console.error('Failed to fetch revisions:', error);
      setRevisions([]);
    }
  }

  async function runCompare(revision) {
    if (!selectedDrawing || revision.id === selectedDrawing.id) return;
    setCompareTarget(revision);
    setCompareResult(null);
    setCompareError(null);
    setCompareLoading(true);
    try {
      const res = await compareAPI.compare(selectedDrawing.id, revision.id);
      setCompareResult(res.data);
    } catch (error) {
      setCompareError(error.response?.data?.detail || 'Comparison failed');
    } finally {
      setCompareLoading(false);
    }
  }

  function closeCompare() {
    setCompareTarget(null);
    setCompareResult(null);
    setCompareError(null);
  }

  const runAnalysisForDrawing = async (drawing) => {
    setStatus('processing');
    const result = await runTakeoffAI({
      onProgress: setProgress,
      seed: drawing.id,
    });
    setDetection(result);
    annotationStore.loadFromDetection(result);
    setStatus('ready');
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
    setCalibrating(false);
    setPendingCalPoints(null);
    setSuggestionDismissed(false);
    fetchScaleInfo(drawing.id);
    fetchRevisions(drawing.id);
    runAnalysisForDrawing(drawing);
  };

  async function fetchScaleInfo(drawingId) {
    try {
      const res = await scaleAPI.get(drawingId);
      setScaleInfo(res.data);
    } catch (error) {
      console.error('Failed to fetch scale info:', error);
      setScaleInfo(null);
    }
  }

  function handleCalibrationPoints(points) {
    setPendingCalPoints(points);
    setCalibrating(false);
  }

  async function submitCalibration(realWorldDistance, unit) {
    if (!selectedDrawing || !pendingCalPoints) return;
    setCalibratingBusy(true);
    try {
      const res = await scaleAPI.calibrate(selectedDrawing.id, {
        point1: pendingCalPoints.point1,
        point2: pendingCalPoints.point2,
        render_scale: 1, // DrawingRenderer already resolves clicks to native plan-space pixels
        real_world_distance: realWorldDistance,
        unit,
      });
      setScaleInfo(res.data);
      setPendingCalPoints(null);
    } catch (error) {
      console.error('Calibration failed:', error);
      alert(error.response?.data?.detail || 'Failed to calibrate scale. Please try again.');
    } finally {
      setCalibratingBusy(false);
    }
  }

  async function acceptScaleSuggestion() {
    if (!selectedDrawing) return;
    try {
      const res = await scaleAPI.acceptSuggestion(selectedDrawing.id);
      setScaleInfo(res.data);
    } catch (error) {
      console.error('Failed to accept scale suggestion:', error);
    }
  }

  async function fetchConditions() {
    if (!id) return;
    try {
      const res = await conditionsAPI.list(id);
      setConditions(res.data || []);
    } catch (error) {
      console.error('Failed to fetch conditions:', error);
    }
  }

  function handleBoxSelect(ids) {
    setSelectedIds(ids);
    setContextMenu(null);
  }

  function handleContextMenuRequest(x, y) {
    if (selectedIds.length === 0) return;
    setContextMenu({ x, y });
  }

  function assignSelectionToCondition(conditionId) {
    annotationStore.assignCondition(selectedIds, conditionId);
    setContextMenu(null);
    setSelectedIds([]);
  }

  async function createConditionAndAssign(data) {
    const res = await conditionsAPI.create(id, data);
    setConditions((prev) => [...prev, res.data]);
    assignSelectionToCondition(res.data.id);
  }

  async function createCondition(data) {
    const res = await conditionsAPI.create(id, data);
    setConditions((prev) => [...prev, res.data]);
  }

  async function deleteCondition(conditionId) {
    try {
      await conditionsAPI.delete(conditionId);
      setConditions((prev) => prev.filter((c) => c.id !== conditionId));
    } catch (error) {
      console.error('Failed to delete condition:', error);
    }
  }

  async function updateCondition(conditionId, data) {
    try {
      const res = await conditionsAPI.update(conditionId, data);
      setConditions((prev) => prev.map((c) => (c.id === conditionId ? res.data : c)));
    } catch (error) {
      console.error('Failed to update condition:', error);
    }
  }

  // Accept/reject/relabel from DetectionHoverCard -> CorrectionEvent, the
  // training-data flywheel (CLAUDE.md §2/§5). drawing_id is only sent when a
  // real Sheet is selected — demo-canvas corrections still log (annotation_id
  // + project scope is enough signal), just without a Drawing FK.
  // geometry included so eval_harness.py's mIoU can compare an AI shape's
  // geometry against its corrected geometry — source/type included so the
  // harness can tell an area edit worth an IoU check apart from a count/line
  // one. Previously only {label, confidence, measuredValue} — no accept/
  // reject/relabel action changes geometry today (that's the still-gated
  // Milestone 1 editable-overlay work), so this doesn't yet produce a live
  // mIoU signal, but every future 'edit' correction will carry what it needs to.
  function snapshotAnnotation(annotation) {
    return {
      label: annotation?.meta?.label,
      confidence: annotation?.meta?.confidence,
      measuredValue: annotation?.measuredValue,
      geometry: annotation?.geometry,
      source: annotation?.source,
    };
  }

  async function recordCorrection(annotation, action, before, after) {
    try {
      await correctionsAPI.create(id, {
        drawing_id: selectedDrawing?.id ?? null,
        annotation_id: annotation.id,
        annotation_type: annotation.type,
        action,
        before,
        after,
        // eval_harness.py scopes a promotion-gate run to one candidate
        // model's corrections via this — undefined for manual annotations,
        // which never had an AI model version to begin with.
        model_version: annotation?.meta?.aiModelVersion,
      });
    } catch (error) {
      console.error('Failed to record correction:', error);
    }
  }

  function handleAcceptDetection(item) {
    const annotation = annotationsById.get(item.id);
    if (!annotation) return;
    annotationStore.updateAnnotationMeta(item.id, { reviewed: true });
    const snapshot = snapshotAnnotation(annotation);
    recordCorrection(annotation, 'accept', snapshot, snapshot);
    setSelectedId(null);
  }

  function handleRejectDetection(item) {
    const annotation = annotationsById.get(item.id);
    if (!annotation) return;
    annotationStore.updateAnnotationMeta(item.id, { rejected: true });
    recordCorrection(annotation, 'reject', snapshotAnnotation(annotation), null);
    setSelectedId(null);
  }

  function handleRelabelDetection(item, newLabel) {
    const annotation = annotationsById.get(item.id);
    if (!annotation || !newLabel.trim() || newLabel === annotation.meta?.label) return;
    const before = { label: annotation.meta?.label };
    annotationStore.updateAnnotationMeta(item.id, { label: newLabel, reviewed: true });
    recordCorrection(annotation, 'relabel', before, { label: newLabel });
  }

  // AI Search result -> annotation. GeoJSON polygon rings repeat the first
  // point to close (spec-guaranteed); rectFromBbox()'s convention doesn't,
  // so drop it. Only called for results on the currently selected drawing —
  // SearchPanel gates "Add" on that since the annotation store is scoped to
  // whichever sheet's detection is currently loaded.
  function addSearchResultAsAnnotation(result, type) {
    const geometry = result.geometry.slice(0, -1);
    annotationStore.addAnnotation({
      id: `search_${result.detection_id}_${Date.now()}`,
      type,
      geometry,
      layerId: 'search',
      source: 'manual',
      meta: { label: result.label_hint, similarity: result.similarity, fromSearch: true },
    });
  }

  async function runAnalysis() {
    setStatus('processing'); setDetection(null); setProgress({ msg: 'Starting...', pct: 0 });
    const res = await runTakeoffAI({ onProgress: (s) => setProgress({ msg: s.msg, pct: s.pct }) });
    setDetection(res);
    annotationStore.loadFromDetection(res);
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
        response = await exportAPI.exportDrawing(selectedDrawing.id, format);
        filename = `takeoff_${selectedDrawing.original_filename.split('.')[0]}_${Date.now()}.${format === 'excel' ? 'xlsx' : 'csv'}`;
      } else {
        response = await exportAPI.exportProject(id, format);
        filename = `project_${project?.name || 'export'}_${Date.now()}.${format === 'excel' ? 'xlsx' : 'csv'}`;
      }
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
  }

  function zoomBy(delta) { setZoom((z) => Math.max(0.5, Math.min(3, z + delta))); }
  function resetView() { setZoom(1); setPan({ x: 0, y: 0 }); }

  function onMouseDown(e) { dragRef.current = { x: e.clientX, y: e.clientY, sx: pan.x, sy: pan.y }; }
  function onMouseMove(e) {
    if (!dragRef.current) return;
    setPan({ x: dragRef.current.sx + (e.clientX - dragRef.current.x), y: dragRef.current.sy + (e.clientY - dragRef.current.y) });
  }
  function onMouseUp() { dragRef.current = null; }

  const annotationsById = useMemo(() => {
    const map = new Map();
    annotationStore.annotations.forEach((a) => map.set(a.id, a));
    return map;
  }, [annotationStore.annotations]);

  const selected = useMemo(() => {
    if (!detection || !selectedId) return null;
    if (annotationsById.get(selectedId)?.meta?.rejected) return null;
    return [...detection.rooms, ...detection.doors, ...detection.windows, ...(detection.wall_segments ?? [])].find((x) => x.id === selectedId);
  }, [detection, selectedId, annotationsById]);

  const conditionsById = useMemo(() => {
    const map = new Map();
    conditions.forEach((c) => map.set(c.id, c));
    return map;
  }, [conditions]);

  const conditionTotals = useMemo(() => {
    const totals = new Map(conditions.map((c) => [c.id, 0]));
    annotationStore.annotations.forEach((a) => {
      const conditionId = a.meta?.conditionId;
      if (conditionId != null && totals.has(conditionId)) {
        totals.set(conditionId, totals.get(conditionId) + a.measuredValue);
      }
    });
    return totals;
  }, [annotationStore.annotations, conditions]);

  // Custom formula (TOGAL_PARITY_REAUDIT.md #5): cost = quantity * unit_cost
  // * (1 + waste% / 100). "Area x Unit Cost" is the common case
  // (annotation_type='area', unit='sf') but this generalizes to any unit.
  // Recomputes live off conditionTotals, which is itself live off the
  // annotation store — editing unit_cost/waste_percent or re-assigning a
  // shape both flow straight through to this number.
  const conditionCostTotals = useMemo(() => {
    const costs = new Map();
    conditions.forEach((c) => {
      const qty = conditionTotals.get(c.id) ?? 0;
      const wasteMultiplier = 1 + (c.waste_percent || 0) / 100;
      costs.set(c.id, qty * (c.unit_cost || 0) * wasteMultiplier);
    });
    return costs;
  }, [conditionTotals, conditions]);

  const grandTotalCost = useMemo(
    () => Array.from(conditionCostTotals.values()).reduce((sum, v) => sum + v, 0),
    [conditionCostTotals]
  );

  return (
    <div className="min-h-screen flex flex-col bg-slate-900">
      <header className="h-14 bg-slate-900 text-white border-b border-slate-800 flex items-center px-4 gap-4 flex-shrink-0">
        <button onClick={() => nav('/app')} className="flex items-center gap-2 text-sm text-slate-300 hover:text-white">
          <ArrowLeft className="w-4 h-4" /> <span>Dashboard</span>
        </button>
        <div className="w-px h-5 bg-slate-700" />
        <div className="min-w-0">
          <div className="text-sm font-semibold text-white truncate">{project?.name || 'Loading...'}</div>
          <div className="text-[10px] mono text-slate-400 truncate">
            {drawings.length > 0 ? `${drawings.length} drawing${drawings.length > 1 ? 's' : ''} · ` : ''}
            {selectedDrawing
              ? (scaleInfo?.scale_label ? `Scale ${scaleInfo.scale_label}` : 'Scale not calibrated')
              : 'Scale 1/8" = 1\'-0"'}
          </div>
        </div>
        {selectedDrawing && (
          <button
            onClick={() => { setCalibrating(true); setPendingCalPoints(null); }}
            className={`inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium border ${
              scaleInfo?.scale_source
                ? 'bg-slate-800 hover:bg-slate-700 text-white border-slate-700'
                : 'bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 border-amber-500/30'
            }`}
          >
            <Ruler className="w-3.5 h-3.5" /> {scaleInfo?.scale_source ? 'Recalibrate' : 'Calibrate Scale'}
          </button>
        )}
        <div className="ml-auto flex items-center gap-2">
          <div className="flex items-center -space-x-1.5">
            {['AR', 'PK', 'JL'].map((x, i) => (
              <div key={x} className="w-7 h-7 rounded-full border-2 border-slate-900 flex items-center justify-center text-[10px] font-semibold text-white" style={{ background: ['#6366f1', '#8b5cf6', '#06b6d4'][i] }}>{x}</div>
            ))}
            <button className="w-7 h-7 rounded-full border-2 border-slate-900 bg-slate-700 flex items-center justify-center text-slate-300 ml-1"><Users className="w-3 h-3" /></button>
          </div>
          <div className="w-px h-5 bg-slate-700" />
          <button onClick={() => setShowUpload(!showUpload)} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-xs font-medium text-white"><Upload className="w-3.5 h-3.5" /> Upload Blueprint</button>
          <button className="w-9 h-9 rounded-lg hover:bg-slate-800 flex items-center justify-center text-slate-400"><Bell className="w-4 h-4" /></button>
          <button onClick={runAnalysis} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-medium text-white border border-slate-700"><RefreshCw className="w-3.5 h-3.5" /> Re-run AI</button>
          <div className="relative">
            <button
              onClick={() => setShowExportMenu(!showExportMenu)}
              disabled={exporting}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white text-slate-900 text-xs font-medium hover:bg-slate-100 disabled:opacity-50"
            >
              {exporting ? (
                <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Exporting...</>
              ) : (
                <><FileDown className="w-3.5 h-3.5" /> Export <ChevronDown className="w-3 h-3" /></>
              )}
            </button>
            {showExportMenu && !exporting && (
              <div className="absolute right-0 top-full mt-1 w-40 bg-white rounded-lg shadow-xl border border-slate-200 py-1 z-50">
                <button onClick={() => handleExport('excel')} className="w-full text-left px-3 py-2 text-xs text-slate-700 hover:bg-slate-50 flex items-center gap-2">
                  <FileDown className="w-3.5 h-3.5" /> Export as Excel
                </button>
                <button onClick={() => handleExport('csv')} className="w-full text-left px-3 py-2 text-xs text-slate-700 hover:bg-slate-50 flex items-center gap-2">
                  <FileDown className="w-3.5 h-3.5" /> Export as CSV
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      <div className="flex-1 grid grid-cols-[260px_1fr_340px] min-h-0">
        <aside className="bg-slate-900 text-slate-200 border-r border-slate-800 p-4 overflow-auto">
          {showUpload && (
            <div className="mb-4 p-3 rounded-lg bg-slate-800 border border-slate-700">
              <div className="text-xs font-semibold text-white mb-2">Upload Blueprints</div>
              <FileUploadZone projectId={id} onUploadComplete={handleUploadComplete} />
            </div>
          )}
          {drawings.length > 0 && (
            <>
              <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-2">Drawings</div>
              <div className="space-y-0.5 mb-4">
                {drawings.map((drawing) => (
                  <button
                    key={drawing.id}
                    onClick={() => selectDrawing(drawing)}
                    className={`w-full text-left px-2 py-1.5 rounded text-xs ${selectedDrawing?.id === drawing.id ? 'bg-indigo-500/20 text-indigo-300 font-medium' : 'text-slate-400 hover:bg-slate-800'}`}
                  >
                    <div className="flex items-center gap-1.5 min-w-0">
                      {drawing.discipline && (
                        <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: DISCIPLINE_COLORS[drawing.discipline] || '#64748b' }} />
                      )}
                      {drawing.sheet_number && <span className="mono flex-shrink-0">{drawing.sheet_number}</span>}
                      <span className="truncate">{drawing.sheet_name || drawing.original_filename}</span>
                    </div>
                    <div className="text-[10px] text-slate-500">
                      {drawing.file_type} · {(drawing.file_size / 1024 / 1024).toFixed(1)}MB
                      {drawing.total_pages > 1 && ` · Sheet ${drawing.page_number + 1}/${drawing.total_pages}`}
                    </div>
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
          <div className="mt-6 mb-2 flex items-center justify-between">
            <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold flex items-center gap-1.5"><Tag className="w-3 h-3" /> Conditions</div>
            <ConditionCreateButton onCreate={createCondition} />
          </div>
          <div className="space-y-1">
            {conditions.length === 0 && (
              <div className="text-[11px] text-slate-500 px-2 py-1">Box-select shapes, right-click, assign.</div>
            )}
            {conditions.map((c) => (
              <button
                key={c.id}
                onClick={() => setEditingCondition(c)}
                className="group w-full flex flex-col gap-0.5 px-2 py-1.5 rounded text-xs text-slate-300 hover:bg-slate-800 text-left"
              >
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-2 min-w-0">
                    <span className="w-2 h-2 rounded-sm flex-shrink-0" style={{ background: c.color }} />
                    <span className="truncate">{c.name}</span>
                  </span>
                  <span className="flex items-center gap-1.5 flex-shrink-0">
                    <span className="mono text-[11px] text-slate-400">{(conditionTotals.get(c.id) ?? 0).toLocaleString()} {c.unit}</span>
                    <span
                      onClick={(e) => { e.stopPropagation(); deleteCondition(c.id); }}
                      className="opacity-0 group-hover:opacity-100 text-slate-500 hover:text-rose-400"
                    >
                      <Trash2 className="w-3 h-3" />
                    </span>
                  </span>
                </div>
                {c.unit_cost > 0 && (
                  <div className="pl-4 text-[10px] text-slate-500 mono">
                    ${c.unit_cost.toLocaleString()}/{c.unit}{c.waste_percent ? ` · ${c.waste_percent}% waste` : ''} = ${(conditionCostTotals.get(c.id) ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}
                  </div>
                )}
              </button>
            ))}
            {grandTotalCost > 0 && (
              <div className="flex items-center justify-between px-2 py-1.5 mt-1 border-t border-slate-800 text-xs font-semibold text-white">
                <span>Total cost</span>
                <span className="mono">${grandTotalCost.toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>
              </div>
            )}
          </div>
          {revisions.length > 1 && (
            <>
              <div className="mt-6 text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-2">Revisions</div>
              <div className="space-y-1">
                {[...revisions].reverse().map((r) => (
                  <button
                    key={r.id}
                    onClick={() => !r.is_current && runCompare(r)}
                    title={r.is_current ? undefined : `Compare against ${r.revision_label}`}
                    className={`group w-full flex items-center justify-between px-2 py-1.5 rounded text-xs ${r.is_current ? 'bg-slate-800 text-slate-200' : 'text-slate-500 hover:bg-slate-800/60'}`}
                  >
                    <span className="flex items-center gap-1.5">
                      {r.revision_label}
                      {!r.is_current && <GitCompare className="w-3 h-3 opacity-0 group-hover:opacity-100" />}
                    </span>
                    <span className="text-[10px] mono">{r.is_current ? 'Current' : new Date(r.uploaded_at).toLocaleDateString()}</span>
                  </button>
                ))}
              </div>
            </>
          )}
        </aside>

        <main className="relative bg-slate-100 overflow-hidden" onMouseMove={onMouseMove} onMouseUp={onMouseUp} onMouseLeave={onMouseUp}>
          {status === 'processing' && <ProcessingOverlay progress={progress} />}
          {selectedDrawing ? (
            <div className="absolute inset-0">
              <DrawingRenderer
                drawing={selectedDrawing}
                onLoad={(data) => console.log('Drawing loaded:', data)}
                calibrating={calibrating}
                onCalibrationPoints={handleCalibrationPoints}
              />
            </div>
          ) : (
            <div className="absolute inset-0 flex items-center justify-center" onMouseDown={selectMode ? undefined : onMouseDown}>
              <div style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`, transition: dragRef.current ? 'none' : 'transform 180ms ease' }}>
                <CanvasFull
                  detection={detection}
                  layers={layers}
                  selectedId={selectedId}
                  onSelect={setSelectedId}
                  selectMode={selectMode}
                  selectedIds={selectedIds}
                  annotationsById={annotationsById}
                  conditionsById={conditionsById}
                  onBoxSelect={handleBoxSelect}
                  onContextMenuRequest={handleContextMenuRequest}
                />
              </div>
            </div>
          )}
          <div className="absolute bottom-4 left-1/2 -translate-x-1/2 flex items-center gap-1 p-1 rounded-xl bg-white border border-slate-200 shadow-lg">
            {!selectedDrawing && (
              <>
                <ToolBtn active={selectMode} onClick={() => { setSelectMode((v) => !v); setSelectedIds([]); }}><MousePointer2 className="w-4 h-4" /></ToolBtn>
                <div className="w-px h-5 bg-slate-200 mx-1" />
              </>
            )}
            <ToolBtn onClick={() => zoomBy(-0.2)}><ZoomOut className="w-4 h-4" /></ToolBtn>
            <div className="mono text-xs px-2 text-slate-700 w-14 text-center">{Math.round(zoom * 100)}%</div>
            <ToolBtn onClick={() => zoomBy(0.2)}><ZoomIn className="w-4 h-4" /></ToolBtn>
            <div className="w-px h-5 bg-slate-200 mx-1" />
            <ToolBtn onClick={resetView}><Maximize2 className="w-4 h-4" /></ToolBtn>
          </div>
          {status === 'ready' && (
            <div className="absolute top-4 left-4 flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white border border-slate-200 shadow-sm text-xs font-medium text-slate-800">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
              AI complete · {detection.processingTimeMs}ms · {detection.rooms.length + detection.doors.length + detection.windows.length} detections
            </div>
          )}
          {selected && (
            <DetectionHoverCard
              item={selected}
              annotation={annotationsById.get(selected.id)}
              onClose={() => setSelectedId(null)}
              onAccept={() => handleAcceptDetection(selected)}
              onReject={() => handleRejectDetection(selected)}
              onRelabel={(newLabel) => handleRelabelDetection(selected, newLabel)}
            />
          )}
          {calibrating && (
            <div className="absolute top-4 left-1/2 -translate-x-1/2 flex items-center gap-2 px-4 py-2 rounded-lg bg-slate-900 text-white shadow-lg text-xs font-medium">
              <Ruler className="w-3.5 h-3.5 text-amber-400" />
              Click two points a known distance apart (e.g. a door width)
              <button onClick={() => setCalibrating(false)} className="ml-2 text-slate-400 hover:text-white"><X className="w-3.5 h-3.5" /></button>
            </div>
          )}
          {selectedDrawing && scaleInfo?.suggestion && !suggestionDismissed && !calibrating && !pendingCalPoints && (
            <ScaleSuggestionBanner
              suggestion={scaleInfo.suggestion}
              onAccept={acceptScaleSuggestion}
              onDismiss={() => setSuggestionDismissed(true)}
            />
          )}
          {pendingCalPoints && (
            <ScaleCalibrationModal
              busy={calibratingBusy}
              onCancel={() => setPendingCalPoints(null)}
              onConfirm={submitCalibration}
            />
          )}
          {selectMode && selectedIds.length > 0 && !contextMenu && (
            <div className="absolute top-4 left-1/2 -translate-x-1/2 flex items-center gap-2 px-4 py-2 rounded-lg bg-slate-900 text-white shadow-lg text-xs font-medium">
              <MousePointer2 className="w-3.5 h-3.5 text-indigo-400" />
              {selectedIds.length} selected · right-click to assign a condition
            </div>
          )}
          {contextMenu && (
            <ConditionAssignMenu
              position={contextMenu}
              conditions={conditions}
              selectedCount={selectedIds.length}
              onAssign={assignSelectionToCondition}
              onCreateAndAssign={createConditionAndAssign}
              onClose={() => setContextMenu(null)}
            />
          )}
        </main>

        <aside className="bg-white border-l border-slate-200 flex flex-col min-h-0">
          <div className="flex border-b border-slate-200">
            {[
              { key: 'quantities', label: 'Quantities' },
              { key: 'search', label: 'Search' },
              { key: 'chat', label: 'Chat' },
              { key: 'summary', label: 'Summary' },
            ].map((t) => (
              <button key={t.key} onClick={() => setTab(t.key)} className={`flex-1 py-3 text-sm font-medium border-b-2 ${tab === t.key ? 'border-slate-900 text-slate-900' : 'border-transparent text-slate-500 hover:text-slate-800'}`}>{t.label}</button>
            ))}
          </div>
          <div className="flex-1 overflow-auto">
            {tab === 'quantities' && <QuantitiesPanel detection={detection} />}
            {tab === 'search' && (
              <SearchPanel
                projectId={id}
                drawings={drawings}
                selectedDrawing={selectedDrawing}
                onAddAnnotation={addSearchResultAsAnnotation}
              />
            )}
            {tab === 'chat' && <ChatPanel detection={detection} drawing={selectedDrawing} />}
            {tab === 'summary' && <SummaryPanel detection={detection} />}
          </div>
        </aside>
      </div>
      {editingCondition && (
        <ConditionEditModal
          condition={editingCondition}
          onSave={(data) => { updateCondition(editingCondition.id, data); setEditingCondition(null); }}
          onCancel={() => setEditingCondition(null)}
        />
      )}
      {compareTarget && (
        <CompareModal
          current={selectedDrawing}
          target={compareTarget}
          loading={compareLoading}
          error={compareError}
          result={compareResult}
          onClose={closeCompare}
        />
      )}
    </div>
  );
}

function ToolBtn({ children, onClick, active = false }) {
  return (
    <button
      onClick={onClick}
      className={`w-8 h-8 rounded-md flex items-center justify-center ${active ? 'bg-indigo-600 text-white hover:bg-indigo-700' : 'hover:bg-slate-100 text-slate-700'}`}
    >
      {children}
    </button>
  );
}

function ProcessingOverlay({ progress }) {
  return (
    <div className="absolute inset-0 z-20 flex items-center justify-center bg-slate-100/90 backdrop-blur-sm">
      <div className="text-center max-w-md w-full px-6">
        <div className="relative mx-auto w-16 h-16">
          <div className="absolute inset-0 rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-500 shadow-lg shadow-indigo-500/30 flex items-center justify-center">
            <Sparkles className="w-6 h-6 text-white animate-pulse" />
          </div>
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

function conditionDotFor(id, annotationsById, conditionsById) {
  const conditionId = annotationsById.get(id)?.meta?.conditionId;
  if (conditionId == null) return null;
  return conditionsById.get(conditionId) || null;
}

function CanvasFull({
  detection, layers, selectedId, onSelect,
  selectMode = false, selectedIds = [], annotationsById = new Map(), conditionsById = new Map(),
  onBoxSelect, onContextMenuRequest,
}) {
  const svgRef = useRef(null);
  const dragStartRef = useRef(null);
  const [marquee, setMarquee] = useState(null); // [x1,y1,x2,y2] in SVG user space
  const selectedIdSet = useMemo(() => new Set(selectedIds), [selectedIds]);

  function toSvgPoint(clientX, clientY) {
    const svg = svgRef.current;
    const ctm = svg?.getScreenCTM();
    if (!svg || !ctm) return [0, 0];
    const pt = svg.createSVGPoint();
    pt.x = clientX; pt.y = clientY;
    const local = pt.matrixTransform(ctm.inverse());
    return [local.x, local.y];
  }

  function handleMouseDown(e) {
    if (!selectMode) return;
    e.stopPropagation(); // don't also trigger the parent's pan-drag
    dragStartRef.current = toSvgPoint(e.clientX, e.clientY);
    setMarquee([...dragStartRef.current, ...dragStartRef.current]);
  }

  function handleMouseMove(e) {
    if (!selectMode || !dragStartRef.current) return;
    const [x2, y2] = toSvgPoint(e.clientX, e.clientY);
    setMarquee([...dragStartRef.current, x2, y2]);
  }

  function handleMouseUp() {
    if (!selectMode || !dragStartRef.current || !marquee) {
      dragStartRef.current = null;
      return;
    }
    const [x1, y1, x2, y2] = marquee;
    const box = [Math.min(x1, x2), Math.min(y1, y2), Math.max(x1, x2), Math.max(y1, y2)];
    const layerVisible = { rooms: layers.rooms, doors: layers.doors, windows: layers.windows, walls: layers.walls, mep: true };
    const hits = [];
    annotationsById.forEach((a, id) => {
      if (layerVisible[a.layerId] === false || a.meta?.rejected) return;
      if (rectsIntersect(box, boundsOf(a.geometry))) hits.push(id);
    });
    dragStartRef.current = null;
    setMarquee(null);
    onBoxSelect?.(hits);
  }

  function handleContextMenu(e) {
    e.preventDefault();
    if (selectedIds.length > 0) onContextMenuRequest?.(e.clientX, e.clientY);
  }

  return (
    <svg
      ref={svgRef}
      width="800" height="680" viewBox="0 0 800 680"
      className={`bg-white rounded-lg shadow-2xl shadow-slate-900/20 border border-slate-200 ${selectMode ? 'cursor-crosshair' : ''}`}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onContextMenu={handleContextMenu}
    >
      <defs>
        <pattern id="grid2" width="40" height="40" patternUnits="userSpaceOnUse">
          <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#eef2f7" strokeWidth="0.5" />
        </pattern>
      </defs>
      <rect width="800" height="680" fill="#fafbff" />
      <rect width="800" height="680" fill="url(#grid2)" />
      {detection && (detection.wall_segments ?? []).map((seg) => {
        if (annotationsById.get(seg.id)?.meta?.rejected) return null;
        const [[x1, y1], [x2, y2]] = seg.geometry;
        const sel = selectedId === seg.id || selectedIdSet.has(seg.id);
        const dot = conditionDotFor(seg.id, annotationsById, conditionsById);
        const exterior = seg.wallType === 'exterior';
        return (
          <g key={seg.id} opacity={layers.walls ? 1 : 0.15}>
            <line
              x1={x1} y1={y1} x2={x2} y2={y2}
              stroke={sel ? '#4f46e5' : (exterior ? '#eab308' : '#ca8a04')}
              strokeWidth={sel ? (exterior ? 6 : 4) : (exterior ? 4 : 2)}
              strokeLinecap="square"
              style={{ cursor: selectMode ? 'crosshair' : 'pointer' }}
              onClick={(e) => { if (selectMode) return; e.stopPropagation(); onSelect(seg.id); }}
            />
            {dot && <circle cx={(x1 + x2) / 2} cy={(y1 + y2) / 2} r="4" fill={dot.color} stroke="#fff" strokeWidth="1.5" style={{ pointerEvents: 'none' }} />}
          </g>
        );
      })}
      {detection && layers.rooms && detection.rooms.map((r) => {
        if (annotationsById.get(r.id)?.meta?.rejected) return null;
        const [x1, y1, x2, y2] = r.bbox;
        const sel = selectedId === r.id || selectedIdSet.has(r.id);
        const dot = conditionDotFor(r.id, annotationsById, conditionsById);
        const label = annotationsById.get(r.id)?.meta?.label ?? r.label;
        return (
          <g key={r.id}>
            <rect
              className="detection-box"
              x={x1 + 4} y={y1 + 4} width={x2 - x1 - 8} height={y2 - y1 - 8}
              fill={getRoomColor(r.label)} fillOpacity={sel ? 0.5 : 0.22}
              stroke={sel ? '#4f46e5' : getRoomColor(r.label)} strokeWidth={sel ? 3 : 1.5}
              strokeDasharray={selectedIdSet.has(r.id) ? '6 3' : undefined}
              style={{ cursor: selectMode ? 'crosshair' : 'pointer' }}
              onClick={(e) => { if (selectMode) return; e.stopPropagation(); onSelect(r.id); }}
            />
            <g transform={`translate(${(x1 + x2) / 2},${(y1 + y2) / 2})`} style={{ pointerEvents: 'none' }}>
              <text textAnchor="middle" fontSize="12" fontWeight="600" fill="#1e293b">{label}</text>
              <text y="14" textAnchor="middle" fontSize="9" fill="#64748b" fontFamily="JetBrains Mono, monospace">{r.area} sf · {Math.round(r.confidence * 100)}%</text>
            </g>
            {dot && <circle cx={x1 + 12} cy={y1 + 12} r="5" fill={dot.color} stroke="#fff" strokeWidth="1.5" style={{ pointerEvents: 'none' }} />}
          </g>
        );
      })}
      {detection && layers.doors && detection.doors.map((d) => {
        if (annotationsById.get(d.id)?.meta?.rejected) return null;
        const dot = conditionDotFor(d.id, annotationsById, conditionsById);
        const sel = selectedIdSet.has(d.id);
        return (
          <g key={d.id} transform={`translate(${d.x},${d.y}) rotate(${d.rotation || 0})`} style={{ cursor: selectMode ? 'crosshair' : 'pointer' }} onClick={(e) => { if (selectMode) return; e.stopPropagation(); onSelect(d.id); }}>
            <rect x="-4" y="-14" width="8" height="28" fill="#fff" />
            <path d={`M 0 -14 A ${d.width} ${d.width} 0 0 1 ${d.width} 14`} stroke={sel ? '#4f46e5' : (selectedId === d.id ? '#059669' : '#10b981')} strokeWidth={sel || selectedId === d.id ? 3 : 1.5} fill="none" />
            <circle cx="0" cy="-14" r="3" fill="#10b981" />
            {dot && <circle cx="10" cy="-14" r="4" fill={dot.color} stroke="#fff" strokeWidth="1.5" style={{ pointerEvents: 'none' }} />}
          </g>
        );
      })}
      {detection && layers.windows && detection.windows.map((w) => {
        if (annotationsById.get(w.id)?.meta?.rejected) return null;
        const dot = conditionDotFor(w.id, annotationsById, conditionsById);
        const sel = selectedIdSet.has(w.id);
        return (
          <g key={w.id} transform={`translate(${w.x},${w.y}) rotate(${w.rotation || 0})`} style={{ cursor: selectMode ? 'crosshair' : 'pointer' }} onClick={(e) => { if (selectMode) return; e.stopPropagation(); onSelect(w.id); }}>
            <rect x="0" y="-4" width={w.width} height="8" fill={sel ? '#4f46e5' : (selectedId === w.id ? '#2563eb' : '#3b82f6')} stroke="#1d4ed8" strokeWidth="1" />
            <line x1="0" y1="0" x2={w.width} y2="0" stroke="#fff" strokeWidth="1" />
            {dot && <circle cx={w.width + 6} cy="0" r="4" fill={dot.color} stroke="#fff" strokeWidth="1.5" style={{ pointerEvents: 'none' }} />}
          </g>
        );
      })}
      {marquee && (
        <rect
          x={Math.min(marquee[0], marquee[2])} y={Math.min(marquee[1], marquee[3])}
          width={Math.abs(marquee[2] - marquee[0])} height={Math.abs(marquee[3] - marquee[1])}
          fill="rgba(79,70,229,0.12)" stroke="#4f46e5" strokeDasharray="4 3"
        />
      )}
    </svg>
  );
}

function DetectionHoverCard({ item, annotation, onClose, onAccept, onReject, onRelabel }) {
  const [editing, setEditing] = useState(false);
  const label = annotation?.meta?.label || item.label || (item.id?.startsWith('d') ? 'Door' : item.id?.startsWith('w') ? 'Window' : 'Element');
  const [draftLabel, setDraftLabel] = useState(label);
  const reviewed = annotation?.meta?.reviewed;

  function saveRelabel(e) {
    e.preventDefault();
    onRelabel(draftLabel);
    setEditing(false);
  }

  return (
    <div className="absolute top-4 right-4 w-64 rounded-xl bg-white border border-slate-200 shadow-xl p-4 z-10 animate-fade-up">
      <div className="flex items-start justify-between">
        <div className="min-w-0">
          <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold flex items-center gap-1.5">
            Detection {reviewed && <Check className="w-3 h-3 text-emerald-600" />}
          </div>
          {editing ? (
            <form onSubmit={saveRelabel} className="mt-1 flex items-center gap-1">
              <input
                value={draftLabel} onChange={(e) => setDraftLabel(e.target.value)} autoFocus
                className="min-w-0 flex-1 rounded border border-slate-300 px-1.5 py-1 text-sm outline-none focus:border-slate-500"
              />
              <button type="submit" className="text-emerald-600 hover:text-emerald-700"><Check className="w-4 h-4" /></button>
              <button type="button" onClick={() => { setEditing(false); setDraftLabel(label); }} className="text-slate-400 hover:text-slate-700"><X className="w-4 h-4" /></button>
            </form>
          ) : (
            <div className="mt-0.5 text-base font-semibold text-slate-900 truncate">{label}</div>
          )}
        </div>
        <button onClick={onClose} className="text-slate-400 hover:text-slate-700 text-xs flex-shrink-0">Close</button>
      </div>
      <div className="mt-3 space-y-1.5 text-xs">
        <div className="flex justify-between"><span className="text-slate-500">ID</span><span className="mono text-slate-900">{item.id}</span></div>
        {item.area && <div className="flex justify-between"><span className="text-slate-500">Area</span><span className="mono text-slate-900">{item.area} sf</span></div>}
        {item.width && <div className="flex justify-between"><span className="text-slate-500">Width</span><span className="mono text-slate-900">{item.width}"</span></div>}
        {item.lengthPx != null && <div className="flex justify-between"><span className="text-slate-500">Length</span><span className="mono text-slate-900">{item.lengthPx}px</span></div>}
        {item.confidence != null ? (
          <div className="flex justify-between"><span className="text-slate-500">Confidence</span><span className="mono text-emerald-600 font-semibold">{Math.round(item.confidence * 100)}%</span></div>
        ) : (
          <div className="flex justify-between"><span className="text-slate-500">Source</span><span className="mono text-slate-500">Derived from room layout</span></div>
        )}
      </div>
      <div className="mt-4 flex gap-1.5">
        <button onClick={onAccept} className="flex-1 py-1.5 text-xs font-medium text-white bg-slate-900 rounded-md hover:bg-slate-800">Accept</button>
        <button onClick={() => setEditing(true)} className="flex-1 py-1.5 text-xs font-medium text-slate-700 bg-slate-100 rounded-md hover:bg-slate-200">Edit</button>
        <button onClick={onReject} className="py-1.5 px-2.5 text-xs font-medium text-rose-600 bg-rose-50 rounded-md hover:bg-rose-100">Reject</button>
      </div>
    </div>
  );
}

function ScaleSuggestionBanner({ suggestion, onAccept, onDismiss }) {
  return (
    <div className="absolute top-4 right-4 w-72 rounded-xl bg-white border border-slate-200 shadow-xl p-4 z-10">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-slate-500 font-semibold">
          <Ruler className="w-3 h-3" /> Scale detected (OCR)
        </div>
        <button onClick={onDismiss} className="text-slate-400 hover:text-slate-700"><X className="w-3.5 h-3.5" /></button>
      </div>
      <div className="mt-1.5 text-base font-semibold text-slate-900">{suggestion.label}</div>
      <div className="mt-0.5 text-xs text-slate-500">{Math.round(suggestion.confidence * 100)}% confidence · matched "{suggestion.raw_text || suggestion.label}"</div>
      <div className="mt-3 flex gap-1.5">
        <button onClick={onAccept} className="flex-1 py-1.5 text-xs font-medium text-white bg-slate-900 rounded-md hover:bg-slate-800">Use this scale</button>
        <button onClick={onDismiss} className="flex-1 py-1.5 text-xs font-medium text-slate-700 bg-slate-100 rounded-md hover:bg-slate-200">Dismiss</button>
      </div>
    </div>
  );
}

function ScaleCalibrationModal({ busy, onCancel, onConfirm }) {
  const [distance, setDistance] = useState('');
  const [unit, setUnit] = useState('ft');

  function submit(e) {
    e.preventDefault();
    const value = parseFloat(distance);
    if (!value || value <= 0) return;
    onConfirm(value, unit);
  }

  return (
    <div className="absolute inset-0 z-30 flex items-center justify-center bg-slate-900/40">
      <form onSubmit={submit} className="w-80 rounded-xl bg-white border border-slate-200 shadow-2xl p-5">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-slate-900">Set real-world distance</h3>
          <button type="button" onClick={onCancel} className="text-slate-400 hover:text-slate-700"><X className="w-4 h-4" /></button>
        </div>
        <p className="mt-1 text-xs text-slate-500">How far apart are the two points you clicked?</p>
        <div className="mt-4 flex items-center gap-2">
          <input
            type="number" step="any" min="0" autoFocus
            value={distance} onChange={(e) => setDistance(e.target.value)}
            placeholder="e.g. 3"
            className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500 focus:ring-2 focus:ring-slate-200"
          />
          <select
            value={unit} onChange={(e) => setUnit(e.target.value)}
            className="rounded-lg border border-slate-300 px-2 py-2 text-sm outline-none focus:border-slate-500"
          >
            <option value="ft">ft</option>
            <option value="in">in</option>
          </select>
        </div>
        <div className="mt-4 flex gap-1.5">
          <button type="button" onClick={onCancel} className="flex-1 py-1.5 text-xs font-medium text-slate-700 bg-slate-100 rounded-md hover:bg-slate-200">Cancel</button>
          <button type="submit" disabled={busy} className="flex-1 py-1.5 text-xs font-medium text-white bg-slate-900 rounded-md hover:bg-slate-800 disabled:opacity-50 flex items-center justify-center gap-1.5">
            {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />} Save scale
          </button>
        </div>
      </form>
    </div>
  );
}

const CONDITION_COLORS = ['#6366f1', '#10b981', '#f59e0b', '#ec4899', '#06b6d4', '#8b5cf6', '#ef4444', '#84cc16'];

function ConditionForm({ initial, initialType = 'area', onSubmit, onCancel, submitLabel = 'Create' }) {
  const [name, setName] = useState(initial?.name ?? '');
  const [trade, setTrade] = useState(initial?.trade ?? '');
  const [annotationType, setAnnotationType] = useState(initial?.annotation_type ?? initialType);
  const [unit, setUnit] = useState(initial?.unit ?? (initialType === 'area' ? 'sf' : initialType === 'line' ? 'lf' : 'ea'));
  const [color, setColor] = useState(initial?.color ?? CONDITION_COLORS[Math.floor(Math.random() * CONDITION_COLORS.length)]);
  const [unitCost, setUnitCost] = useState(initial?.unit_cost ?? 0);
  const [wastePercent, setWastePercent] = useState(initial?.waste_percent ?? 0);

  function handleTypeChange(t) {
    setAnnotationType(t);
    setUnit(t === 'area' ? 'sf' : t === 'line' ? 'lf' : 'ea');
  }

  function submit(e) {
    e.preventDefault();
    if (!name.trim() || !trade.trim()) return;
    onSubmit({
      name: name.trim(), trade: trade.trim(), annotation_type: annotationType, unit, color,
      unit_cost: parseFloat(unitCost) || 0, waste_percent: parseFloat(wastePercent) || 0,
    });
  }

  return (
    <form onSubmit={submit} className="space-y-2">
      <input
        value={name} onChange={(e) => setName(e.target.value)} placeholder="Condition name (e.g. Interior Drywall)" autoFocus
        className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-xs outline-none focus:border-slate-500 focus:ring-2 focus:ring-slate-200"
      />
      <input
        value={trade} onChange={(e) => setTrade(e.target.value)} placeholder="Trade (e.g. Drywall)"
        className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-xs outline-none focus:border-slate-500 focus:ring-2 focus:ring-slate-200"
      />
      <div className="flex items-center gap-1.5">
        <select value={annotationType} onChange={(e) => handleTypeChange(e.target.value)} className="flex-1 rounded-md border border-slate-300 px-2 py-1.5 text-xs outline-none">
          {ANNOTATION_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
        </select>
        <input type="color" value={color} onChange={(e) => setColor(e.target.value)} className="w-8 h-8 rounded border border-slate-300" />
      </div>
      <div className="flex items-center gap-1.5">
        <label className="flex-1 flex items-center gap-1.5 text-xs text-slate-600">
          <span className="text-slate-400">$</span>
          <input
            type="number" step="any" min="0" value={unitCost} onChange={(e) => setUnitCost(e.target.value)}
            placeholder="Unit cost" title={`Cost per ${unit}`}
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-xs outline-none focus:border-slate-500"
          />
          <span className="text-slate-400 flex-shrink-0">/{unit}</span>
        </label>
        <label className="flex items-center gap-1.5 text-xs text-slate-600">
          <input
            type="number" step="any" min="0" value={wastePercent} onChange={(e) => setWastePercent(e.target.value)}
            placeholder="Waste"
            className="w-16 rounded-md border border-slate-300 px-2 py-1.5 text-xs outline-none focus:border-slate-500"
          />
          <span className="text-slate-400 flex-shrink-0">% waste</span>
        </label>
      </div>
      <div className="flex gap-1.5 pt-1">
        <button type="button" onClick={onCancel} className="flex-1 py-1.5 text-xs font-medium text-slate-700 bg-slate-100 rounded-md hover:bg-slate-200">Cancel</button>
        <button type="submit" className="flex-1 py-1.5 text-xs font-medium text-white bg-slate-900 rounded-md hover:bg-slate-800">{submitLabel}</button>
      </div>
    </form>
  );
}

function ConditionCreateButton({ onCreate }) {
  const [open, setOpen] = useState(false);
  if (!open) {
    return (
      <button onClick={() => setOpen(true)} className="text-slate-500 hover:text-slate-200"><Plus className="w-3.5 h-3.5" /></button>
    );
  }
  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-slate-900/40" onClick={() => setOpen(false)}>
      <div className="w-72 rounded-xl bg-white border border-slate-200 shadow-2xl p-4" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-sm font-semibold text-slate-900 mb-3">New condition</h3>
        <ConditionForm onSubmit={(data) => { onCreate(data); setOpen(false); }} onCancel={() => setOpen(false)} />
      </div>
    </div>
  );
}

function ConditionEditModal({ condition, onSave, onCancel }) {
  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-slate-900/40" onClick={onCancel}>
      <div className="w-72 rounded-xl bg-white border border-slate-200 shadow-2xl p-4" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-sm font-semibold text-slate-900 mb-3">Edit condition</h3>
        <ConditionForm initial={condition} onSubmit={onSave} onCancel={onCancel} submitLabel="Save" />
      </div>
    </div>
  );
}

function CompareModal({ current, target, loading, error, result, onClose }) {
  const stats = result?.quantification;
  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-slate-900/40" onClick={onClose}>
      <div className="w-[640px] max-w-[90vw] max-h-[85vh] overflow-auto rounded-xl bg-white border border-slate-200 shadow-2xl p-5" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-slate-900 flex items-center gap-1.5">
            <GitCompare className="w-4 h-4 text-indigo-600" />
            {current?.sheet_name ? `${current.sheet_name} — ` : ''}{target?.revision_label} vs Current
          </h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700"><X className="w-4 h-4" /></button>
        </div>

        {loading && (
          <div className="mt-8 flex flex-col items-center justify-center gap-2 text-slate-500 text-xs py-10">
            <Loader2 className="w-5 h-5 animate-spin" />
            Aligning sheets and computing diff…
          </div>
        )}

        {!loading && error && (
          <div className="mt-4 rounded-lg bg-rose-50 border border-rose-200 p-3 text-xs text-rose-700">
            {error}
            <div className="mt-1.5 text-rose-500">
              Manual point-pair alignment is supported by the API but not yet wired into this UI —
              ask an engineer to run it via <span className="mono">POST /api/takeoff/drawings/{'{id}'}/compare</span> with
              manual_points_a/manual_points_b if auto-align keeps failing.
            </div>
          </div>
        )}

        {!loading && !error && result && (
          <div className="mt-4 space-y-4">
            <img src={result.diff_image} alt="Drawing diff" className="w-full rounded-lg border border-slate-200" />
            <div className="flex items-center gap-4 text-[10px] text-slate-500">
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-[#dc3c3c]" /> Removed</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-[#3c6edc]" /> Added</span>
              <span className="ml-auto mono">
                {result.alignment_method === 'auto' ? `Auto-aligned · ${result.alignment_confidence} matched features` : `Manually aligned · ${result.alignment_confidence} point pairs`}
              </span>
            </div>
            {stats && (
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-lg border border-rose-200 bg-rose-50 p-3">
                  <div className="text-[10px] uppercase tracking-wider text-rose-500 font-semibold">Removed</div>
                  <div className="mt-1 text-sm font-semibold text-rose-700">{stats.removed_regions} region{stats.removed_regions === 1 ? '' : 's'}</div>
                  <div className="text-[11px] text-rose-500 mono">
                    {stats.removed_px.toLocaleString()} px{stats.removed_sqft != null ? ` · ${stats.removed_sqft.toLocaleString()} sf` : ''}
                  </div>
                </div>
                <div className="rounded-lg border border-indigo-200 bg-indigo-50 p-3">
                  <div className="text-[10px] uppercase tracking-wider text-indigo-500 font-semibold">Added</div>
                  <div className="mt-1 text-sm font-semibold text-indigo-700">{stats.added_regions} region{stats.added_regions === 1 ? '' : 's'}</div>
                  <div className="text-[11px] text-indigo-500 mono">
                    {stats.added_px.toLocaleString()} px{stats.added_sqft != null ? ` · ${stats.added_sqft.toLocaleString()} sf` : ''}
                  </div>
                </div>
              </div>
            )}
            {stats && stats.removed_sqft == null && (
              <div className="text-[10px] text-slate-400">Set a scale on this drawing to see changed area in sf, not just pixels.</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function ConditionAssignMenu({ position, conditions, selectedCount, onAssign, onCreateAndAssign, onClose }) {
  const [creating, setCreating] = useState(false);
  const menuStyle = { left: Math.min(position.x, window.innerWidth - 260), top: Math.min(position.y, window.innerHeight - 320) };

  return (
    <div className="fixed inset-0 z-40" onClick={onClose} onContextMenu={(e) => { e.preventDefault(); onClose(); }}>
      <div className="fixed w-64 rounded-xl bg-white border border-slate-200 shadow-2xl py-2" style={menuStyle} onClick={(e) => e.stopPropagation()}>
        {!creating ? (
          <>
            <div className="px-3 py-1.5 text-[10px] uppercase tracking-wider text-slate-500 font-semibold flex items-center gap-1.5">
              <Tag className="w-3 h-3" /> Assign {selectedCount} shape{selectedCount > 1 ? 's' : ''} to
            </div>
            <div className="max-h-48 overflow-auto">
              {conditions.length === 0 && <div className="px-3 py-2 text-xs text-slate-500">No conditions yet</div>}
              {conditions.map((c) => (
                <button key={c.id} onClick={() => onAssign(c.id)} className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50">
                  <span className="w-2.5 h-2.5 rounded-sm flex-shrink-0" style={{ background: c.color }} />
                  <span className="truncate">{c.name}</span>
                  <span className="ml-auto text-[10px] text-slate-400">{c.unit}</span>
                </button>
              ))}
            </div>
            <div className="border-t border-slate-100 mt-1 pt-1">
              <button onClick={() => setCreating(true)} className="w-full flex items-center gap-2 px-3 py-1.5 text-xs font-medium text-indigo-600 hover:bg-slate-50">
                <Plus className="w-3.5 h-3.5" /> New condition
              </button>
            </div>
          </>
        ) : (
          <div className="px-3 py-2">
            <ConditionForm submitLabel="Create & assign" onSubmit={onCreateAndAssign} onCancel={() => setCreating(false)} />
          </div>
        )}
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

function SearchPanel({ projectId, drawings, selectedDrawing, onAddAnnotation }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const drawingNameById = useMemo(() => {
    const map = new Map();
    drawings.forEach((d) => map.set(d.id, d.sheet_name || d.original_filename));
    return map;
  }, [drawings]);

  async function runSearch(e) {
    e?.preventDefault();
    const q = query.trim();
    if (!q || loading) return;
    setLoading(true); setError(null); setResults(null);
    try {
      const res = await searchAPI.text(projectId, q);
      setResults(res.data.results);
    } catch (err) {
      setError(err.response?.status === 503
        ? "AI Search isn't available yet — the server is missing its CLIP model dependencies."
        : (err.response?.data?.detail || 'Search failed. Please try again.'));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="h-full flex flex-col">
      <div className="p-4 border-b border-slate-200">
        <form onSubmit={runSearch} className="flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 focus-within:border-slate-500 focus-within:ring-2 focus-within:ring-slate-200">
          <SearchIcon className="w-4 h-4 text-slate-400" />
          <input
            value={query} onChange={(e) => setQuery(e.target.value)}
            placeholder='Find "outlets", "bedrooms"...'
            className="flex-1 text-sm outline-none bg-transparent"
          />
          <button type="submit" disabled={!query.trim() || loading} className="w-7 h-7 rounded-md bg-slate-900 text-white flex items-center justify-center disabled:opacity-40">
            {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <SearchIcon className="w-3.5 h-3.5" />}
          </button>
        </form>
        <p className="mt-2 text-[11px] text-slate-500">Search across every sheet in this project by description. CLIP embeds every AI detection on ingest; results rank by similarity.</p>
      </div>
      <div className="flex-1 overflow-auto p-4 space-y-2">
        {error && <div className="text-xs text-rose-600 bg-rose-50 rounded-lg p-3">{error}</div>}
        {results && results.length === 0 && <div className="text-sm text-slate-500">No matches found.</div>}
        {results && results.map((r) => {
          const onCurrentDrawing = r.drawing_id === selectedDrawing?.id;
          return (
            <div key={`${r.drawing_id}-${r.detection_id}`} className="rounded-lg border border-slate-200 p-3">
              <div className="flex items-center justify-between">
                <div className="text-sm font-medium text-slate-900">{r.label_hint || 'Match'}</div>
                <div className="text-[11px] mono text-emerald-600 font-semibold">{Math.round(r.similarity * 100)}%</div>
              </div>
              <div className="mt-0.5 text-[11px] text-slate-500">{drawingNameById.get(r.drawing_id) || `Sheet #${r.drawing_id}`}</div>
              <div className="mt-2 flex gap-1.5">
                <button
                  disabled={!onCurrentDrawing}
                  onClick={() => onAddAnnotation(r, 'count')}
                  title={onCurrentDrawing ? undefined : "Select this result's sheet to add it"}
                  className="flex-1 py-1 text-[11px] font-medium text-white bg-slate-900 rounded-md hover:bg-slate-800 disabled:opacity-30 disabled:cursor-not-allowed"
                >
                  Add as Count
                </button>
                <button
                  disabled={!onCurrentDrawing}
                  onClick={() => onAddAnnotation(r, 'area')}
                  title={onCurrentDrawing ? undefined : "Select this result's sheet to add it"}
                  className="flex-1 py-1 text-[11px] font-medium text-slate-700 bg-slate-100 rounded-md hover:bg-slate-200 disabled:opacity-30 disabled:cursor-not-allowed"
                >
                  Add as Area
                </button>
              </div>
            </div>
          );
        })}
        {!results && !error && (
          <p className="text-xs text-slate-500">
            Type a description above — "outlets", "fire extinguishers", "bedrooms" — to find every matching detection across this project's sheets.
          </p>
        )}
      </div>
    </div>
  );
}

function ChatPanel({ detection, drawing }) {
  const [messages, setMessages] = useState([
    { role: 'assistant', text: "Hi! I've parsed this sheet. Ask me anything about rooms, doors, windows, quantities or scope — or ask me to draft a Scope of Work, RFP, or RFI.", time: 'now', synthetic: true },
  ]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const endRef = useRef(null);

  async function send(prompt) {
    const q = (prompt ?? input).trim();
    if (!q || sending) return;
    // Claude's API requires the conversation to start with a user-role
    // message — the synthetic UI greeting above isn't a real turn, exclude it.
    const history = messages.filter((m) => !m.synthetic).map((m) => ({ role: m.role, content: m.text }));
    setMessages((m) => [...m, { role: 'user', text: q, time: 'now' }]);
    setInput(''); setSending(true);
    try {
      if (drawing) {
        // Real TakeOff.CHAT — RAG over this sheet's detections, conditions,
        // human corrections, and OCR (routes/ai_routes.py).
        const res = await chatAPI.send(drawing.id, q, history);
        setMessages((m) => [...m, { role: 'assistant', text: res.data.answer, time: 'now', citations: res.data.citations }]);
      } else {
        // No real Sheet selected (demo canvas) — nothing to ground a real
        // chat in yet, same scoping as scale calibration/corrections.
        const res = await askTakeoffChat(q);
        setMessages((m) => [...m, { role: 'assistant', text: res.answer, time: 'now', citations: res.citations }]);
      }
    } catch (error) {
      const detail = error.response?.data?.detail;
      const text = error.response?.status === 503
        ? "TakeOff.CHAT isn't configured yet — the server is missing its Claude API key."
        : (detail || "Something went wrong answering that. Please try again.");
      setMessages((m) => [...m, { role: 'assistant', text, time: 'now' }]);
    } finally {
      setSending(false);
    }
  }

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages, sending]);

  const suggestions = drawing
    ? ['How many rooms?', 'Total paintable area?', 'Draft a Scope of Work', 'Draft an RFP', 'Draft an RFI']
    : ['How many rooms?', 'Total paintable area?', 'Generate a scope of work', 'Any door irregularities?'];

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