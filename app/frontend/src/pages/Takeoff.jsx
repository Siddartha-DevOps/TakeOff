import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Sparkles, Upload, Send, Download, ZoomIn, ZoomOut, Maximize2, Eye, EyeOff, FileDown, MessageSquare, Layers, RefreshCw, Check, Users, Bell, Loader2, ChevronDown, Ruler, X, MousePointer2, Tag, Plus, Trash2, Search as SearchIcon, GitCompare, ArrowRightLeft, History, Box, Repeat, Folder, FolderPlus, ChevronRight } from 'lucide-react';
import Drawing3DView from '../components/Drawing3DView';
import RepeatingGroupsModal from '../components/RepeatingGroupsModal';
import { runTakeoffAI, askTakeoffChat, getRoomColor } from '../mock/mockAI';
import { SAMPLE_PROJECTS } from '../mock/mockData';
import { projectsAPI, uploadsAPI, takeoffAPI, exportAPI, scaleAPI, conditionsAPI, correctionsAPI, chatAPI, searchAPI, compareAPI, handoffAPI, collabAPI, foldersAPI, templatesAPI } from '../services/api';
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

// Same palette CreateProjectModal.jsx's ORG_COLORS uses — one shared set of
// organization colors for folders too (Togal parity: "color-coded, folders, sets").
const FOLDER_COLORS = ['#6366f1', '#ef4444', '#f59e0b', '#10b981', '#3b82f6', '#a855f7', '#ec4899', '#64748b'];

export default function Takeoff() {
  const { id } = useParams();
  const nav = useNavigate();
  const [project, setProject] = useState(null);
  const [drawings, setDrawings] = useState([]);
  const [folders, setFolders] = useState([]);
  const [collapsedFolders, setCollapsedFolders] = useState(() => new Set());
  const [showNewFolder, setShowNewFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState('');
  const [newFolderColor, setNewFolderColor] = useState(FOLDER_COLORS[0]);
  const [movingDrawingId, setMovingDrawingId] = useState(null);
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
  const [showAdvancedExport, setShowAdvancedExport] = useState(false);
  const [showHandoff, setShowHandoff] = useState(false);
  const [showRepeatingGroups, setShowRepeatingGroups] = useState(false);
  const [show3DView, setShow3DView] = useState(false);
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

  // Real-time collaboration — presence, live cursors, pinned comments
  // (memory/TOGAL_PARITY_REAUDIT.md #16; realtime.py, routes/realtime_routes.py).
  const [presenceUsers, setPresenceUsers] = useState({}); // user_id -> {name,color,drawing_id,x,y}
  const [comments, setComments] = useState([]);
  const [commentMode, setCommentMode] = useState(false);
  const [pendingCommentPoint, setPendingCommentPoint] = useState(null); // plan [x,y] awaiting body text
  const [activeCommentId, setActiveCommentId] = useState(null); // pin popover currently open
  const wsRef = useRef(null);
  const lastCursorSentRef = useRef(0);
  const selfUserId = (() => { try { return JSON.parse(localStorage.getItem('user') || '{}').id; } catch { return null; } })();

  useEffect(() => {
    fetchProject();
    // eslint-disable-next-line
  }, [id]);

  useEffect(() => {
    if (project) {
      fetchDrawings();
      fetchFolders();
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

  // Drawing folders — Togal parity "Project folders & organization"
  // (color-coded, folders, sets). Folders are a manual, project-scoped
  // grouping (routes/folder_routes.py); "sets" are the automatic grouping
  // sheets that arrived together in one multi-page PDF upload already carry
  // (Drawing.upload_batch_id) — surfaced below, not a separate fetch.
  async function fetchFolders() {
    try {
      const response = await foldersAPI.list(id);
      setFolders(response.data || []);
    } catch (error) {
      console.error('Failed to fetch folders:', error);
      setFolders([]);
    }
  }

  async function createFolder() {
    const name = newFolderName.trim();
    if (!name) return;
    try {
      const response = await foldersAPI.create(id, { name, color: newFolderColor });
      setFolders((prev) => [...prev, response.data]);
      setNewFolderName('');
      setNewFolderColor(FOLDER_COLORS[0]);
      setShowNewFolder(false);
    } catch (error) {
      console.error('Failed to create folder:', error);
    }
  }

  async function deleteFolder(folderId) {
    try {
      await foldersAPI.delete(folderId);
      setFolders((prev) => prev.filter((f) => f.id !== folderId));
      // Un-file client-side too — the backend already SET NULLs it (ON
      // DELETE SET NULL), this just keeps the sidebar in sync without a refetch.
      setDrawings((prev) => prev.map((d) => (d.folder_id === folderId ? { ...d, folder_id: null } : d)));
    } catch (error) {
      console.error('Failed to delete folder:', error);
    }
  }

  async function assignDrawingFolder(drawingId, folderId) {
    try {
      const response = await foldersAPI.assignDrawing(drawingId, folderId);
      setDrawings((prev) => prev.map((d) => (d.id === drawingId ? response.data : d)));
    } catch (error) {
      console.error('Failed to move drawing:', error);
    } finally {
      setMovingDrawingId(null);
    }
  }

  function toggleFolderCollapsed(folderId) {
    setCollapsedFolders((prev) => {
      const next = new Set(prev);
      if (next.has(folderId)) next.delete(folderId);
      else next.add(folderId);
      return next;
    });
  }

  // Folders (manual) + sets (automatic, from upload_batch_id) grouping for
  // the Drawings sidebar. Unfiled drawings that share a batch_id with at
  // least one sibling render under a "Set" sub-heading; everything else
  // (single-page uploads, or already-foldered sheets) is flat.
  const drawingGroups = useMemo(() => {
    const byFolder = new Map(folders.map((f) => [f.id, []]));
    const unfiled = [];
    for (const d of drawings) {
      if (d.folder_id != null && byFolder.has(d.folder_id)) byFolder.get(d.folder_id).push(d);
      else unfiled.push(d);
    }
    const batchCounts = new Map();
    for (const d of unfiled) {
      if (d.upload_batch_id) batchCounts.set(d.upload_batch_id, (batchCounts.get(d.upload_batch_id) || 0) + 1);
    }
    const sets = new Map(); // batch_id -> drawings[]
    const unfiledFlat = [];
    for (const d of unfiled) {
      if (d.upload_batch_id && batchCounts.get(d.upload_batch_id) > 1) {
        if (!sets.has(d.upload_batch_id)) sets.set(d.upload_batch_id, []);
        sets.get(d.upload_batch_id).push(d);
      } else {
        unfiledFlat.push(d);
      }
    }
    return { byFolder, sets, unfiledFlat };
  }, [drawings, folders]);

  function renderDrawingRow(drawing) {
    return (
      <div key={drawing.id} className="group relative flex items-center gap-1">
        <button
          onClick={() => selectDrawing(drawing)}
          className={`flex-1 min-w-0 text-left px-2 py-1.5 rounded text-xs ${selectedDrawing?.id === drawing.id ? 'bg-indigo-500/20 text-indigo-300 font-medium' : 'text-slate-400 hover:bg-slate-800'}`}
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
        <div className="relative flex-shrink-0">
          <button
            onClick={() => setMovingDrawingId(movingDrawingId === drawing.id ? null : drawing.id)}
            title="Move to folder"
            className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-slate-800 text-slate-500 hover:text-slate-300"
          >
            <Folder className="w-3 h-3" />
          </button>
          {movingDrawingId === drawing.id && (
            <div className="absolute right-0 top-6 z-10 w-40 bg-slate-800 border border-slate-700 rounded-lg shadow-xl py-1">
              <button
                onClick={() => assignDrawingFolder(drawing.id, null)}
                className="w-full text-left px-3 py-1.5 text-[11px] text-slate-300 hover:bg-slate-700"
              >
                Unfiled
              </button>
              {folders.map((f) => (
                <button
                  key={f.id}
                  onClick={() => assignDrawingFolder(drawing.id, f.id)}
                  className="w-full text-left px-3 py-1.5 text-[11px] text-slate-300 hover:bg-slate-700 flex items-center gap-1.5"
                >
                  <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: f.color }} />
                  <span className="truncate">{f.name}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  // Real-time collaboration socket — one connection per project ("room"),
  // independent of which drawing is currently open (presence/cursors carry
  // their own drawing_id so remote cursors are filtered client-side).
  useEffect(() => {
    if (!id) return undefined;
    const ws = new WebSocket(collabAPI.wsUrl(id));
    wsRef.current = ws;

    ws.onmessage = (event) => {
      let msg;
      try { msg = JSON.parse(event.data); } catch { return; }
      switch (msg.type) {
        case 'presence_sync': {
          const next = {};
          for (const u of msg.users) if (u.user_id !== selfUserId) next[u.user_id] = u;
          setPresenceUsers(next);
          break;
        }
        case 'user_joined':
          if (msg.user.user_id !== selfUserId) {
            setPresenceUsers((prev) => ({ ...prev, [msg.user.user_id]: msg.user }));
          }
          break;
        case 'user_left':
          setPresenceUsers((prev) => { const next = { ...prev }; delete next[msg.user_id]; return next; });
          break;
        case 'cursor':
          setPresenceUsers((prev) => ({ ...prev, [msg.user_id]: { ...prev[msg.user_id], ...msg } }));
          break;
        case 'comment_created':
          setComments((prev) => (prev.some((c) => c.id === msg.comment.id) ? prev : [...prev, msg.comment]));
          break;
        case 'comment_resolved':
          setComments((prev) => prev.map((c) => (c.id === msg.comment.id ? msg.comment : c)));
          break;
        case 'comment_deleted':
          setComments((prev) => prev.filter((c) => c.id !== msg.comment_id));
          break;
        default:
          break;
      }
    };

    return () => {
      ws.close();
      wsRef.current = null;
    };
    // eslint-disable-next-line
  }, [id]);

  // Comments are per-drawing (pin coordinates only make sense on one sheet)
  // — reload the list whenever the open drawing changes.
  useEffect(() => {
    if (!selectedDrawing) { setComments([]); return; }
    collabAPI.listComments(id, { drawing_id: selectedDrawing.id })
      .then((res) => setComments(res.data.comments))
      .catch(() => setComments([]));
  }, [id, selectedDrawing?.id]);

  function handleCollabPointerMove(point) {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN || !selectedDrawing) return;
    const now = Date.now();
    if (now - lastCursorSentRef.current < 80) return; // ~12/s — plenty smooth, avoids flooding the socket
    lastCursorSentRef.current = now;
    wsRef.current.send(JSON.stringify({ type: 'cursor', drawing_id: selectedDrawing.id, x: point[0], y: point[1] }));
  }

  async function submitComment(body) {
    if (!pendingCommentPoint || !selectedDrawing || !body.trim()) return;
    try {
      const res = await collabAPI.createComment(id, {
        drawing_id: selectedDrawing.id, x: pendingCommentPoint[0], y: pendingCommentPoint[1], body: body.trim(),
      });
      setComments((prev) => [...prev, res.data]);
      setPendingCommentPoint(null);
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to post comment');
    }
  }

  async function toggleResolveComment(comment) {
    try {
      const res = await collabAPI.resolveComment(comment.id, !comment.resolved);
      setComments((prev) => prev.map((c) => (c.id === comment.id ? res.data : c)));
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to update comment');
    }
  }

  async function removeComment(comment) {
    try {
      await collabAPI.deleteComment(comment.id);
      setComments((prev) => prev.filter((c) => c.id !== comment.id));
      setActiveCommentId(null);
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to delete comment');
    }
  }

  const drawingCursors = Object.entries(presenceUsers)
    .filter(([, u]) => u.drawing_id === selectedDrawing?.id && u.x != null && u.y != null)
    .map(([uid, u]) => ({ user_id: Number(uid), name: u.name, color: u.color, x: u.x, y: u.y }));
  const drawingPins = comments.map((c) => ({ id: c.id, x: c.x, y: c.y, resolved: c.resolved }));

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

  // Map the backend AUTODETECT response into the detection shape the panels +
  // annotation store expect. Area/Line/Count come from exact vector geometry.
  const mapAutodetect = (data, drawing) => {
    const prim = data.primitives || {};
    const rooms = (data.area || []).map((s) => ({
      id: s.id,
      label: s.label || 'Space',
      bbox: s.bbox || [0, 0, 0, 0],
      area: s.sqft,
      confidence: s.confidence ?? 1,
      geojson: s.geojson,
      centroid: s.centroid,
    }));
    return {
      rooms, doors: [], windows: [],
      quantities: data.quantities || [],
      summary: {
        rooms: prim.count ?? rooms.length, doors: 0, windows: 0,
        walls: prim.line ?? 0, totalArea: prim.area ?? 0,
      },
      symbol_counts: data.symbol_counts || {},
      symbolGroups: data.symbol_groups || [],
      primitives: prim, page: data.page, method: 'vector',
      scale: data.scale_ratio ? `1:${Math.round(data.scale_ratio)}` : '—',
      sheet: drawing?.sheet_name || drawing?.original_filename || '',
      processingTimeMs: 0,
    };
  };

  const runAnalysisForDrawing = async (drawing) => {
    setStatus('processing');
    setProgress({ msg: 'Reading vector geometry from the plan…', pct: 30 });

    // Real vector AUTODETECT first (exact, no weights). Falls back to the mock
    // only when the sheet isn't a vector PDF or the call fails — same
    // real-first/fallback pattern this app uses for chat.
    let result = null;
    let fromVector = false;
    if ((drawing.file_type || '').toUpperCase() === 'PDF') {
      try {
        const { data } = await takeoffAPI.autodetect(drawing.id);
        if (data && data.method === 'vector' && data.is_vector !== false) {
          result = mapAutodetect(data, drawing);
          fromVector = true;
        }
      } catch (error) {
        console.warn('AUTODETECT unavailable, falling back:', error);
      }
    }
    if (!result) {
      result = await runTakeoffAI({ onProgress: setProgress, seed: drawing.id });
    }

    setDetection(result);
    annotationStore.loadFromDetection(result);
    setStatus('ready');

    // The vector AUTODETECT endpoint already persisted a TakeoffResult; only the
    // mock/fallback path needs to save here (avoids a duplicate row + usage count).
    if (!fromVector) {
      try {
        await takeoffAPI.saveResults(drawing.id, {
          detection_data: JSON.stringify(result),
          quantities_data: JSON.stringify(result.summary || {}),
          confidence_scores: JSON.stringify({ avg: 0.95 }),
          processing_time_ms: result.processingTimeMs || 1500,
        });
      } catch (error) {
        console.error('Failed to save AI results:', error);
      }
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
        {selectedDrawing && (
          <button
            onClick={() => { setCommentMode((v) => !v); setPendingCommentPoint(null); }}
            title="Comment mode — click the drawing to pin a note"
            className={`inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium border ${
              commentMode
                ? 'bg-indigo-600 hover:bg-indigo-700 text-white border-indigo-500'
                : 'bg-slate-800 hover:bg-slate-700 text-white border-slate-700'
            }`}
          >
            <MessageSquare className="w-3.5 h-3.5" /> Comment
          </button>
        )}
        {selectedDrawing && (
          <button
            onClick={() => setShow3DView(true)}
            title="Interactive 3D view of this drawing's detected geometry"
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium border bg-slate-800 hover:bg-slate-700 text-white border-slate-700"
          >
            <Box className="w-3.5 h-3.5" /> 3D View
          </button>
        )}
        <div className="ml-auto flex items-center gap-2">
          <div className="flex items-center -space-x-1.5">
            {/* Live presence — memory/TOGAL_PARITY_REAUDIT.md #16 (was hardcoded 'AR'/'PK'/'JL'). */}
            {Object.values(presenceUsers).map((u) => (
              <div
                key={u.user_id}
                title={u.name}
                className="w-7 h-7 rounded-full border-2 border-slate-900 flex items-center justify-center text-[10px] font-semibold text-white"
                style={{ background: u.color }}
              >
                {(u.name || '?').slice(0, 2).toUpperCase()}
              </div>
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
                <div className="my-1 border-t border-slate-100" />
                <button onClick={() => { setShowExportMenu(false); setShowAdvancedExport(true); }} className="w-full text-left px-3 py-2 text-xs text-slate-700 hover:bg-slate-50 flex items-center gap-2">
                  <FileDown className="w-3.5 h-3.5" /> Advanced export (PDF, grouping…)
                </button>
                <div className="my-1 border-t border-slate-100" />
                <button onClick={() => { setShowExportMenu(false); setShowHandoff(true); }} className="w-full text-left px-3 py-2 text-xs text-slate-700 hover:bg-slate-50 flex items-center gap-2">
                  <ArrowRightLeft className="w-3.5 h-3.5" /> Estimating handoff (UPC/WBS)
                </button>
                <div className="my-1 border-t border-slate-100" />
                <button onClick={() => { setShowExportMenu(false); setShowRepeatingGroups(true); }} className="w-full text-left px-3 py-2 text-xs text-slate-700 hover:bg-slate-50 flex items-center gap-2">
                  <Repeat className="w-3.5 h-3.5" /> Repeating groups
                </button>
              </div>
            )}
          </div>
        </div>
      </header>
      {showAdvancedExport && (
        <ExportModal
          projectId={id}
          drawings={drawings}
          projectName={project?.name}
          onClose={() => setShowAdvancedExport(false)}
        />
      )}
      {showHandoff && (
        <HandoffModal
          projectId={id}
          projectName={project?.name}
          onClose={() => setShowHandoff(false)}
        />
      )}
      {showRepeatingGroups && (
        <RepeatingGroupsModal
          projectId={id}
          drawings={drawings}
          onClose={() => setShowRepeatingGroups(false)}
        />
      )}
      {show3DView && selectedDrawing && (
        <Drawing3DView
          drawingId={selectedDrawing.id}
          drawingName={selectedDrawing.sheet_name || selectedDrawing.original_filename}
          scaleRatio={scaleInfo?.scale_ratio}
          onClose={() => setShow3DView(false)}
        />
      )}

      <div className="flex-1 grid grid-cols-[260px_1fr_340px] min-h-0">
        <aside className="bg-slate-900 text-slate-200 border-r border-slate-800 p-4 overflow-auto">
          {showUpload && (
            <div className="mb-4 p-3 rounded-lg bg-slate-800 border border-slate-700">
              <div className="text-xs font-semibold text-white mb-2">Upload Blueprints</div>
              <FileUploadZone projectId={id} onUploadComplete={handleUploadComplete} />
            </div>
          )}
          {(drawings.length > 0 || folders.length > 0) && (
            <>
              <div className="flex items-center justify-between mb-2">
                <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">Drawings</div>
                <button
                  onClick={() => setShowNewFolder((v) => !v)}
                  title="New folder"
                  className="p-1 rounded hover:bg-slate-800 text-slate-500 hover:text-slate-300"
                >
                  <FolderPlus className="w-3.5 h-3.5" />
                </button>
              </div>

              {showNewFolder && (
                <div className="mb-3 p-2 rounded-lg bg-slate-800 border border-slate-700 space-y-2">
                  <input
                    autoFocus
                    value={newFolderName}
                    onChange={(e) => setNewFolderName(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') createFolder(); if (e.key === 'Escape') setShowNewFolder(false); }}
                    placeholder="Folder name"
                    className="w-full px-2 py-1 text-xs rounded bg-slate-900 border border-slate-700 text-slate-200 outline-none focus:border-indigo-500"
                  />
                  <div className="flex items-center gap-1.5">
                    {FOLDER_COLORS.map((c) => (
                      <button
                        key={c}
                        onClick={() => setNewFolderColor(c)}
                        className="w-4 h-4 rounded-full flex-shrink-0"
                        style={{ background: c, boxShadow: newFolderColor === c ? `0 0 0 2px #0f172a, 0 0 0 3.5px ${c}` : 'none' }}
                        aria-label={`Color ${c}`}
                      />
                    ))}
                    <div className="flex-1" />
                    <button onClick={createFolder} className="px-2 py-0.5 text-[11px] rounded bg-indigo-500 text-white hover:bg-indigo-400">Create</button>
                  </div>
                </div>
              )}

              <div className="space-y-3 mb-4">
                {folders.map((folder) => {
                  const folderDrawings = drawingGroups.byFolder.get(folder.id) || [];
                  const collapsed = collapsedFolders.has(folder.id);
                  return (
                    <div key={folder.id}>
                      <div className="group flex items-center gap-1 px-1">
                        <button onClick={() => toggleFolderCollapsed(folder.id)} className="flex items-center gap-1.5 flex-1 min-w-0 text-left">
                          <ChevronRight className={`w-3 h-3 flex-shrink-0 text-slate-500 transition-transform ${collapsed ? '' : 'rotate-90'}`} />
                          <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: folder.color }} />
                          <span className="text-[11px] font-semibold text-slate-300 truncate">{folder.name}</span>
                          <span className="text-[10px] text-slate-500">({folderDrawings.length})</span>
                        </button>
                        <button
                          onClick={() => deleteFolder(folder.id)}
                          title="Delete folder"
                          className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-slate-800 text-slate-500 hover:text-rose-400"
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </div>
                      {!collapsed && (
                        <div className="mt-0.5 ml-4 space-y-0.5">
                          {folderDrawings.length === 0
                            ? <div className="text-[10px] text-slate-600 px-2 py-1">Empty</div>
                            : folderDrawings.map(renderDrawingRow)}
                        </div>
                      )}
                    </div>
                  );
                })}

                {[...drawingGroups.sets.entries()].map(([batchId, setDrawings]) => (
                  <div key={batchId}>
                    <div className="flex items-center gap-1.5 px-1 mb-0.5">
                      <span className="text-[10px] uppercase tracking-wider text-slate-500">Set</span>
                      <span className="text-[10px] text-slate-600">· {setDrawings.length} sheets</span>
                    </div>
                    <div className="space-y-0.5">{setDrawings.map(renderDrawingRow)}</div>
                  </div>
                ))}

                {drawingGroups.unfiledFlat.length > 0 && (
                  <div className="space-y-0.5">{drawingGroups.unfiledFlat.map(renderDrawingRow)}</div>
                )}
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
            <div className="flex items-center gap-1">
              <ConditionLibraryMenu projectId={id} projectName={project?.name} conditions={conditions} onChanged={fetchConditions} />
              <ConditionCreateButton onCreate={createCondition} />
            </div>
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
                detection={detection}
                onLoad={(data) => console.log('Drawing loaded:', data)}
                calibrating={calibrating}
                onCalibrationPoints={handleCalibrationPoints}
                commentMode={commentMode}
                onCommentClick={(point) => { setPendingCommentPoint(point); setActiveCommentId(null); }}
                onPointerMove={handleCollabPointerMove}
                remoteCursors={drawingCursors}
                commentPins={drawingPins}
                onPinClick={(commentId) => { setActiveCommentId(commentId); setPendingCommentPoint(null); }}
              />
              {(pendingCommentPoint || activeCommentId) && (
                <CommentPopover
                  point={pendingCommentPoint}
                  comment={activeCommentId ? comments.find((c) => c.id === activeCommentId) : null}
                  replies={activeCommentId ? comments.filter((c) => c.parent_id === activeCommentId) : []}
                  currentUserId={selfUserId}
                  onSubmitNew={submitComment}
                  onToggleResolve={toggleResolveComment}
                  onDelete={removeComment}
                  onClose={() => { setPendingCommentPoint(null); setActiveCommentId(null); }}
                />
              )}
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

// Classification libraries (Togal parity: "Reusable templates, import/export").
// Org-scoped templates (routes/template_routes.py) plus raw JSON
// download/upload for exchanging condition sets outside the app entirely.
function ConditionLibraryMenu({ projectId, projectName, conditions, onChanged }) {
  const [open, setOpen] = useState(false);
  const [templates, setTemplates] = useState(null); // null = not loaded yet
  const [saving, setSaving] = useState(false);
  const [newTemplateName, setNewTemplateName] = useState('');
  const fileInputRef = useRef(null);

  async function loadTemplates() {
    try {
      const res = await templatesAPI.list();
      setTemplates(res.data || []);
    } catch (error) {
      console.error('Failed to load templates:', error);
      setTemplates([]);
    }
  }

  function toggle() {
    const next = !open;
    setOpen(next);
    if (next && templates === null) loadTemplates();
  }

  async function saveAsTemplate() {
    const name = newTemplateName.trim();
    if (!name || conditions.length === 0) return;
    setSaving(true);
    try {
      const res = await templatesAPI.saveFromProject(projectId, { name });
      setTemplates((prev) => [...(prev || []), res.data]);
      setNewTemplateName('');
    } catch (error) {
      console.error('Failed to save template:', error);
    } finally {
      setSaving(false);
    }
  }

  async function applyTemplate(templateId) {
    try {
      await templatesAPI.apply(projectId, templateId);
      onChanged();
      setOpen(false);
    } catch (error) {
      console.error('Failed to apply template:', error);
    }
  }

  async function deleteTemplate(templateId) {
    try {
      await templatesAPI.delete(templateId);
      setTemplates((prev) => prev.filter((t) => t.id !== templateId));
    } catch (error) {
      console.error('Failed to delete template:', error);
    }
  }

  async function exportJson() {
    try {
      const res = await templatesAPI.exportProject(projectId);
      const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${(projectName || 'conditions').replace(/[^a-z0-9]+/gi, '-')}-conditions.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      console.error('Failed to export conditions:', error);
    }
  }

  async function importJsonFile(e) {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    try {
      const text = await file.text();
      const payload = JSON.parse(text);
      await templatesAPI.importJson(projectId, payload);
      onChanged();
      setOpen(false);
    } catch (error) {
      console.error('Failed to import conditions JSON:', error);
    }
  }

  return (
    <div className="relative">
      <button onClick={toggle} title="Classification library" className="text-slate-500 hover:text-slate-200">
        <Folder className="w-3.5 h-3.5" />
      </button>
      {open && (
        <div className="fixed inset-0 z-30" onClick={() => setOpen(false)}>
          <div
            className="absolute right-4 top-32 w-72 rounded-xl bg-slate-800 border border-slate-700 shadow-2xl p-3 text-xs"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-2">Classification library</div>

            <div className="space-y-1 mb-3 max-h-40 overflow-auto">
              {templates === null && <div className="text-slate-500 px-1 py-1">Loading…</div>}
              {templates?.length === 0 && <div className="text-slate-500 px-1 py-1">No saved templates yet.</div>}
              {templates?.map((t) => (
                <div key={t.id} className="flex items-center gap-1.5 group">
                  <button
                    onClick={() => applyTemplate(t.id)}
                    className="flex-1 min-w-0 text-left px-2 py-1 rounded hover:bg-slate-700 text-slate-300"
                  >
                    <span className="truncate block">{t.name}</span>
                    <span className="text-[10px] text-slate-500">{t.items.length} condition{t.items.length === 1 ? '' : 's'}</span>
                  </button>
                  <button
                    onClick={() => deleteTemplate(t.id)}
                    className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-slate-700 text-slate-500 hover:text-rose-400"
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                </div>
              ))}
            </div>

            <div className="flex items-center gap-1.5 mb-2">
              <input
                value={newTemplateName}
                onChange={(e) => setNewTemplateName(e.target.value)}
                placeholder="Save current conditions as…"
                disabled={conditions.length === 0}
                className="flex-1 min-w-0 px-2 py-1 rounded bg-slate-900 border border-slate-700 text-slate-200 outline-none focus:border-indigo-500 disabled:opacity-50"
              />
              <button
                onClick={saveAsTemplate}
                disabled={saving || !newTemplateName.trim() || conditions.length === 0}
                className="px-2 py-1 rounded bg-indigo-500 text-white hover:bg-indigo-400 disabled:opacity-50 flex-shrink-0"
              >
                Save
              </button>
            </div>

            <div className="flex items-center gap-2 pt-2 border-t border-slate-700">
              <button onClick={exportJson} disabled={conditions.length === 0} className="text-slate-400 hover:text-slate-200 disabled:opacity-50">Export JSON</button>
              <span className="text-slate-600">·</span>
              <button onClick={() => fileInputRef.current?.click()} className="text-slate-400 hover:text-slate-200">Import JSON</button>
              <input ref={fileInputRef} type="file" accept="application/json" className="hidden" onChange={importJsonFile} />
            </div>
          </div>
        </div>
      )}
    </div>
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

// Rich export — memory/TOGAL_PARITY_REAUDIT.md #14: PDF export + 3-level
// grouping, filtering, drawing selection, export multiplier, inline
// editable grid. Rows come from routes/export_routes.py's preview
// endpoint (TakeoffResult.quantities_data per drawing, not the
// client-only Condition/cost concept — see export_engine.py's docstring
// for why); doExport() posts back exactly what's shown here, edits and
// exclusions included, so the grid is genuinely what gets exported.
function ExportModal({ projectId, drawings, projectName, onClose }) {
  const [selectedDrawingIds, setSelectedDrawingIds] = useState(() => new Set(drawings.map((d) => d.id)));
  const [selectedTrades, setSelectedTrades] = useState(new Set()); // empty = all trades
  const [multiplier, setMultiplier] = useState(1);
  const [groupBy, setGroupBy] = useState(['trade', 'drawing', '']);
  const [rows, setRows] = useState(null); // null = not yet loaded
  const [availableTrades, setAvailableTrades] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [exportingFormat, setExportingFormat] = useState(null);
  const [excludedRowIds, setExcludedRowIds] = useState(new Set());

  async function loadPreview() {
    setLoading(true);
    setError(null);
    try {
      const res = await exportAPI.previewProjectExport(projectId, {
        drawingIds: Array.from(selectedDrawingIds),
        trades: selectedTrades.size ? Array.from(selectedTrades) : undefined,
        multiplier,
      });
      setRows(res.data.rows);
      setAvailableTrades(res.data.available_trades);
      setExcludedRowIds(new Set());
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load preview');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { loadPreview(); /* eslint-disable-next-line */ }, []);

  function updateRowQuantity(rowId, value) {
    setRows((prev) => prev.map((r) => (r.row_id === rowId ? { ...r, quantity: value } : r)));
  }

  function toggleExcluded(rowId) {
    setExcludedRowIds((prev) => {
      const next = new Set(prev);
      if (next.has(rowId)) next.delete(rowId); else next.add(rowId);
      return next;
    });
  }

  function toggleDrawing(drawingId) {
    setSelectedDrawingIds((prev) => {
      const next = new Set(prev);
      if (next.has(drawingId)) next.delete(drawingId); else next.add(drawingId);
      return next;
    });
  }

  function toggleTrade(trade) {
    setSelectedTrades((prev) => {
      const next = new Set(prev);
      if (next.has(trade)) next.delete(trade); else next.add(trade);
      return next;
    });
  }

  const includedRows = (rows || []).filter((r) => !excludedRowIds.has(r.row_id));

  async function doExport(format) {
    if (!includedRows.length) return;
    setExportingFormat(format);
    try {
      const res = await exportAPI.generateProjectExport(projectId, {
        format,
        rows: includedRows.map((r) => ({ ...r, quantity: parseFloat(r.quantity) || 0 })),
        group_by: groupBy.filter(Boolean),
        title: `${projectName || 'Project'} — Takeoff Export`,
      });
      const mediaType = format === 'excel'
        ? 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        : format === 'pdf' ? 'application/pdf' : 'text/csv';
      const blob = new Blob([res.data], { type: mediaType });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `takeoff_export.${format === 'excel' ? 'xlsx' : format}`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (err) {
      alert(err.response?.data?.detail || 'Export failed');
    } finally {
      setExportingFormat(null);
    }
  }

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/50" onClick={onClose}>
      <div className="w-[880px] max-w-[95vw] max-h-[88vh] overflow-hidden flex flex-col rounded-xl bg-white border border-slate-200 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200">
          <h3 className="text-sm font-semibold text-slate-900 flex items-center gap-1.5"><FileDown className="w-4 h-4" /> Export project quantities</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700"><X className="w-4 h-4" /></button>
        </div>

        <div className="flex-1 overflow-auto px-5 py-4 space-y-4">
          <div>
            <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1.5">
              Drawings ({selectedDrawingIds.size}/{drawings.length})
            </div>
            <div className="flex flex-wrap gap-1.5">
              {drawings.map((d) => (
                <button
                  key={d.id}
                  onClick={() => toggleDrawing(d.id)}
                  className={`px-2.5 py-1 text-[11px] font-medium rounded-md border ${selectedDrawingIds.has(d.id) ? 'bg-indigo-50 border-indigo-300 text-indigo-700' : 'bg-white border-slate-200 text-slate-500'}`}
                >
                  {d.sheet_number || d.sheet_name || d.original_filename}
                </button>
              ))}
              {drawings.length === 0 && <span className="text-xs text-slate-400">No drawings in this project yet.</span>}
            </div>
          </div>

          {availableTrades.length > 0 && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1.5">Trades (none selected = all)</div>
              <div className="flex flex-wrap gap-1.5">
                {availableTrades.map((t) => (
                  <button
                    key={t}
                    onClick={() => toggleTrade(t)}
                    className={`px-2.5 py-1 text-[11px] font-medium rounded-md ${selectedTrades.has(t) ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'}`}
                  >
                    {t}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="flex items-end gap-3 flex-wrap">
            {[0, 1, 2].map((level) => (
              <div key={level}>
                <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">Group {level + 1}</div>
                <select
                  value={groupBy[level]}
                  onChange={(e) => setGroupBy((prev) => prev.map((v, i) => (i === level ? e.target.value : v)))}
                  className="rounded-lg border border-slate-300 px-2 py-1.5 text-xs"
                >
                  <option value="">None</option>
                  <option value="trade">Trade</option>
                  <option value="drawing">Sheet</option>
                  <option value="item">Item</option>
                </select>
              </div>
            ))}
            <div>
              <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">Multiplier</div>
              <input
                type="number" min="0.01" step="0.1" value={multiplier}
                onChange={(e) => setMultiplier(parseFloat(e.target.value) || 1)}
                className="w-20 rounded-lg border border-slate-300 px-2 py-1.5 text-xs"
              />
            </div>
            <button onClick={loadPreview} disabled={loading} className="px-3 py-1.5 text-xs font-medium text-white bg-slate-900 rounded-md hover:bg-slate-800 disabled:opacity-50 flex items-center gap-1.5">
              {loading && <Loader2 className="w-3.5 h-3.5 animate-spin" />} Apply
            </button>
          </div>

          {error && <div className="text-xs text-rose-600">{error}</div>}

          {rows && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1.5">
                Preview — {includedRows.length}/{rows.length} rows included · edit quantities or exclude rows below
              </div>
              <div className="border border-slate-200 rounded-lg overflow-hidden max-h-72 overflow-y-auto">
                <table className="w-full text-xs">
                  <thead className="bg-slate-50 sticky top-0">
                    <tr>
                      <th className="w-8"></th>
                      <th className="text-left px-2 py-1.5 font-medium text-slate-500">Item</th>
                      <th className="text-left px-2 py-1.5 font-medium text-slate-500">Trade</th>
                      <th className="text-left px-2 py-1.5 font-medium text-slate-500">Sheet</th>
                      <th className="text-right px-2 py-1.5 font-medium text-slate-500">Quantity</th>
                      <th className="text-left px-2 py-1.5 font-medium text-slate-500">Unit</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => {
                      const excluded = excludedRowIds.has(r.row_id);
                      return (
                        <tr key={r.row_id} className={excluded ? 'opacity-40' : ''}>
                          <td className="px-2 py-1"><input type="checkbox" checked={!excluded} onChange={() => toggleExcluded(r.row_id)} /></td>
                          <td className="px-2 py-1 truncate max-w-[180px]" title={r.item}>{r.item}</td>
                          <td className="px-2 py-1 text-slate-500">{r.trade}</td>
                          <td className="px-2 py-1 text-slate-500">{r.drawing_name}</td>
                          <td className="px-2 py-1 text-right">
                            <input
                              type="number" value={r.quantity}
                              onChange={(e) => updateRowQuantity(r.row_id, e.target.value)}
                              disabled={excluded}
                              className="w-20 text-right rounded border border-slate-200 px-1.5 py-0.5 mono disabled:bg-slate-50"
                            />
                          </td>
                          <td className="px-2 py-1 text-slate-500">{r.unit}</td>
                        </tr>
                      );
                    })}
                    {rows.length === 0 && (
                      <tr><td colSpan={6} className="px-2 py-6 text-center text-slate-400">No quantities match these filters.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 px-5 py-4 border-t border-slate-200">
          {['excel', 'pdf', 'csv'].map((format) => (
            <button
              key={format}
              onClick={() => doExport(format)}
              disabled={!includedRows.length || exportingFormat !== null}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-900 text-white text-xs font-medium hover:bg-slate-800 disabled:opacity-50"
            >
              {exportingFormat === format ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FileDown className="w-3.5 h-3.5" />}
              {format.toUpperCase()}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

const HANDOFF_TARGET_SYSTEMS = [
  { value: 'generic', label: 'Generic (UPC + WBS)' },
  { value: 'ediphi', label: 'Ediphi' },
  { value: 'destini', label: 'DESTINI Estimator' },
  { value: 'procore', label: 'Procore (Cost Code)' },
];

// Estimating-handoff integration — quantities -> UPC/WBS map + audit trail
// (routes/handoff_routes.py, handoff_engine.py). Not an estimating engine:
// this maps the AI's trade/item quantities to the cost codes a partner tool
// imports, and logs every mapping edit + every export for accountability.
function HandoffModal({ projectId, projectName, onClose }) {
  const [tab, setTab] = useState('mapping'); // 'mapping' | 'audit'
  const [rows, setRows] = useState(null);
  const [edits, setEdits] = useState({}); // rowKey -> { wbs_code, upc_code, description }
  const [targetSystem, setTargetSystem] = useState('generic');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [savingKey, setSavingKey] = useState(null);
  const [exporting, setExporting] = useState(false);
  const [auditEvents, setAuditEvents] = useState(null);
  const [auditLoading, setAuditLoading] = useState(false);

  const rowKey = (r) => `${r.trade} ${r.item}`;

  async function loadMappings() {
    setLoading(true);
    setError(null);
    try {
      const res = await handoffAPI.getMappings(projectId);
      setRows(res.data.rows);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load quantities/mappings');
    } finally {
      setLoading(false);
    }
  }

  async function loadAuditTrail() {
    setAuditLoading(true);
    try {
      const res = await handoffAPI.getAuditTrail(projectId);
      setAuditEvents(res.data.events);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load audit trail');
    } finally {
      setAuditLoading(false);
    }
  }

  useEffect(() => { loadMappings(); /* eslint-disable-next-line */ }, []);
  useEffect(() => { if (tab === 'audit' && auditEvents === null) loadAuditTrail(); /* eslint-disable-next-line */ }, [tab]);

  function fieldFor(r) {
    const key = rowKey(r);
    if (edits[key]) return edits[key];
    return {
      wbs_code: r.wbs_code || r.suggested?.wbs_code || '',
      upc_code: r.upc_code || r.suggested?.upc_code || '',
      description: r.description || r.suggested?.description || '',
    };
  }

  function updateField(r, field, value) {
    const key = rowKey(r);
    setEdits((prev) => ({ ...prev, [key]: { ...fieldFor(r), [field]: value } }));
  }

  async function saveMapping(r) {
    const key = rowKey(r);
    const f = fieldFor(r);
    setSavingKey(key);
    try {
      await handoffAPI.upsertMapping(projectId, {
        trade: r.trade, item: r.item,
        wbs_code: f.wbs_code || null, upc_code: f.upc_code || null, description: f.description || null,
        target_system: targetSystem,
      });
      setEdits((prev) => { const next = { ...prev }; delete next[key]; return next; });
      await loadMappings();
      if (auditEvents !== null) loadAuditTrail();
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to save mapping');
    } finally {
      setSavingKey(null);
    }
  }

  async function clearMapping(r) {
    if (!r.mapping_id) return;
    setSavingKey(rowKey(r));
    try {
      await handoffAPI.deleteMapping(r.mapping_id);
      await loadMappings();
      if (auditEvents !== null) loadAuditTrail();
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to clear mapping');
    } finally {
      setSavingKey(null);
    }
  }

  const mappedCount = (rows || []).filter((r) => r.mapped).length;

  async function doExport() {
    setExporting(true);
    try {
      const res = await handoffAPI.exportHandoff(projectId, targetSystem);
      const blob = new Blob([res.data], { type: 'text/csv' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `handoff_${targetSystem}.csv`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
      if (auditEvents !== null) loadAuditTrail();
    } catch (err) {
      alert(err.response?.data?.detail || 'Export failed');
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/50" onClick={onClose}>
      <div className="w-[920px] max-w-[95vw] max-h-[88vh] overflow-hidden flex flex-col rounded-xl bg-white border border-slate-200 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200">
          <h3 className="text-sm font-semibold text-slate-900 flex items-center gap-1.5"><ArrowRightLeft className="w-4 h-4" /> Estimating handoff — {projectName || 'Project'}</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700"><X className="w-4 h-4" /></button>
        </div>

        <div className="flex items-center gap-1 px-5 pt-3 border-b border-slate-200">
          {[['mapping', 'UPC/WBS mapping'], ['audit', 'Audit trail']].map(([key, label]) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={`px-3 py-1.5 text-xs font-medium rounded-t-md flex items-center gap-1.5 ${tab === key ? 'bg-slate-100 text-slate-900' : 'text-slate-500 hover:text-slate-700'}`}
            >
              {key === 'audit' && <History className="w-3.5 h-3.5" />} {label}
            </button>
          ))}
        </div>

        {error && <div className="px-5 pt-3 text-xs text-rose-600">{error}</div>}

        {tab === 'mapping' && (
          <>
            <div className="flex-1 overflow-auto px-5 py-4">
              <div className="flex items-center justify-between mb-2">
                <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">
                  {rows ? `${mappedCount}/${rows.length} items mapped` : 'Loading…'}
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">Target</span>
                  <select value={targetSystem} onChange={(e) => setTargetSystem(e.target.value)} className="rounded-lg border border-slate-300 px-2 py-1 text-xs">
                    {HANDOFF_TARGET_SYSTEMS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                  </select>
                </div>
              </div>

              <div className="border border-slate-200 rounded-lg overflow-hidden">
                <table className="w-full text-xs">
                  <thead className="bg-slate-50 sticky top-0">
                    <tr>
                      <th className="text-left px-2 py-1.5 font-medium text-slate-500">Item</th>
                      <th className="text-left px-2 py-1.5 font-medium text-slate-500">Trade</th>
                      <th className="text-right px-2 py-1.5 font-medium text-slate-500">Qty</th>
                      <th className="text-left px-2 py-1.5 font-medium text-slate-500">WBS code</th>
                      <th className="text-left px-2 py-1.5 font-medium text-slate-500">UPC code</th>
                      <th className="text-left px-2 py-1.5 font-medium text-slate-500">Description</th>
                      <th className="w-20"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {(rows || []).map((r) => {
                      const key = rowKey(r);
                      const f = fieldFor(r);
                      const dirty = !!edits[key];
                      return (
                        <tr key={key} className="border-t border-slate-100">
                          <td className="px-2 py-1 truncate max-w-[140px]" title={r.item}>{r.item}</td>
                          <td className="px-2 py-1 text-slate-500">{r.trade}</td>
                          <td className="px-2 py-1 text-right mono">{r.quantity} {r.unit}</td>
                          <td className="px-2 py-1">
                            <input value={f.wbs_code} onChange={(e) => updateField(r, 'wbs_code', e.target.value)}
                              placeholder="e.g. 09-210" className="w-24 rounded border border-slate-200 px-1.5 py-0.5" />
                          </td>
                          <td className="px-2 py-1">
                            <input value={f.upc_code} onChange={(e) => updateField(r, 'upc_code', e.target.value)}
                              placeholder="e.g. 09.21.16" className="w-28 rounded border border-slate-200 px-1.5 py-0.5" />
                          </td>
                          <td className="px-2 py-1">
                            <input value={f.description} onChange={(e) => updateField(r, 'description', e.target.value)}
                              placeholder={r.suggested?.description || ''} className="w-full min-w-[140px] rounded border border-slate-200 px-1.5 py-0.5" />
                          </td>
                          <td className="px-2 py-1">
                            <div className="flex items-center gap-1">
                              {r.mapped ? <Check className="w-3.5 h-3.5 text-emerald-600 shrink-0" /> : null}
                              <button
                                onClick={() => saveMapping(r)}
                                disabled={savingKey === key || (!dirty && r.mapped)}
                                title="Save mapping"
                                className="px-1.5 py-0.5 rounded bg-slate-900 text-white disabled:opacity-30"
                              >
                                {savingKey === key ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Save'}
                              </button>
                              {r.mapping_id && (
                                <button onClick={() => clearMapping(r)} disabled={savingKey === key} title="Clear mapping" className="p-1 text-slate-400 hover:text-rose-600">
                                  <Trash2 className="w-3 h-3" />
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                    {rows && rows.length === 0 && (
                      <tr><td colSpan={7} className="px-2 py-6 text-center text-slate-400">No quantities yet — run AI takeoff on a drawing first.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="flex items-center justify-between px-5 py-4 border-t border-slate-200">
              <div className="text-[11px] text-slate-500">
                {rows && mappedCount < rows.length ? `${rows.length - mappedCount} unmapped item(s) export as "UNMAPPED", not dropped.` : 'All items mapped.'}
              </div>
              <button
                onClick={doExport}
                disabled={!rows || !rows.length || exporting}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-900 text-white text-xs font-medium hover:bg-slate-800 disabled:opacity-50"
              >
                {exporting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FileDown className="w-3.5 h-3.5" />}
                Export {HANDOFF_TARGET_SYSTEMS.find((s) => s.value === targetSystem)?.label}
              </button>
            </div>
          </>
        )}

        {tab === 'audit' && (
          <div className="flex-1 overflow-auto px-5 py-4">
            {auditLoading && <div className="text-xs text-slate-400 flex items-center gap-1.5"><Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading audit trail…</div>}
            {!auditLoading && auditEvents && auditEvents.length === 0 && (
              <div className="text-xs text-slate-400">No mapping changes or exports yet.</div>
            )}
            <div className="space-y-2">
              {(auditEvents || []).map((e) => (
                <div key={e.id} className="border border-slate-200 rounded-lg px-3 py-2">
                  <div className="flex items-center justify-between text-[11px]">
                    <span className="font-medium text-slate-800">{e.action.replace(/_/g, ' ')}</span>
                    <span className="text-slate-400">{e.user_email} · {new Date(e.created_at).toLocaleString()}{e.target_system ? ` · ${e.target_system}` : ''}</span>
                  </div>
                  {e.action === 'handoff_exported' && e.after && (
                    <div className="mt-1 text-[11px] text-slate-500 mono">{e.after}</div>
                  )}
                  {e.action !== 'handoff_exported' && (
                    <div className="mt-1 grid grid-cols-2 gap-2 text-[11px]">
                      <div>
                        <div className="text-slate-400 mb-0.5">Before</div>
                        <div className="text-slate-600 mono break-all">{e.before || '—'}</div>
                      </div>
                      <div>
                        <div className="text-slate-400 mb-0.5">After</div>
                        <div className="text-slate-600 mono break-all">{e.after || '—'}</div>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// Pinned-comment create/view panel — memory/TOGAL_PARITY_REAUDIT.md #16.
// Fixed-corner placement rather than anchored exactly at the pin: the pin's
// on-screen position is computed inside DrawingRenderer (it alone knows
// which of the three render paths — OSD/PDF/raster — is active and their
// current zoom/pan), so exactly reproducing that here would mean
// duplicating that conversion logic for a purely cosmetic anchoring win.
// The pin itself (rendered by DrawingRenderer) already marks the spot on
// the drawing; this panel just needs to be visible and out of the way.
function CommentPopover({ point, comment, replies, currentUserId, onSubmitNew, onToggleResolve, onDelete, onClose }) {
  const [text, setText] = useState('');
  const isNew = !!point;

  return (
    <div className="absolute bottom-20 right-4 z-40 w-72 rounded-xl bg-white border border-slate-200 shadow-2xl overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-200 bg-slate-50">
        <span className="text-xs font-semibold text-slate-700 flex items-center gap-1.5">
          <MessageSquare className="w-3.5 h-3.5" /> {isNew ? 'New comment' : 'Comment'}
        </span>
        <button onClick={onClose} className="text-slate-400 hover:text-slate-700"><X className="w-3.5 h-3.5" /></button>
      </div>

      {isNew ? (
        <div className="p-3 space-y-2">
          <textarea
            autoFocus
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Leave a note pinned to this spot…"
            rows={3}
            className="w-full text-xs rounded-lg border border-slate-300 px-2 py-1.5 resize-none"
          />
          <button
            onClick={() => onSubmitNew(text)}
            disabled={!text.trim()}
            className="w-full px-3 py-1.5 rounded-lg bg-slate-900 text-white text-xs font-medium hover:bg-slate-800 disabled:opacity-40"
          >
            Post
          </button>
        </div>
      ) : comment ? (
        <div className="p-3 space-y-2">
          <div className={`text-xs rounded-lg p-2 ${comment.resolved ? 'bg-slate-50 text-slate-400' : 'bg-indigo-50 text-slate-700'}`}>
            <div className="flex items-center justify-between mb-1">
              <span className="font-medium">{comment.author_email}</span>
              <span className="text-[10px] text-slate-400">{new Date(comment.created_at).toLocaleString()}</span>
            </div>
            <p className={comment.resolved ? 'line-through' : ''}>{comment.body}</p>
          </div>
          {replies.map((r) => (
            <div key={r.id} className="text-xs bg-slate-50 rounded-lg p-2 ml-3">
              <div className="font-medium text-slate-600">{r.author_email}</div>
              <p className="text-slate-600">{r.body}</p>
            </div>
          ))}
          <div className="flex items-center gap-2 pt-1">
            <button
              onClick={() => onToggleResolve(comment)}
              className="flex-1 px-2 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 text-[11px] font-medium flex items-center justify-center gap-1"
            >
              <Check className="w-3 h-3" /> {comment.resolved ? 'Reopen' : 'Resolve'}
            </button>
            {comment.author_id === currentUserId && (
              <button onClick={() => onDelete(comment)} className="px-2 py-1.5 rounded-lg bg-rose-50 hover:bg-rose-100 text-rose-600" title="Delete comment">
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        </div>
      ) : null}
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