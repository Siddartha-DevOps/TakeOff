import React, { useState, useEffect, useRef } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import OpenSeadragon from "openseadragon";
import { uploadsAPI } from "../services/api";

// Configure PDF.js worker
pdfjs.GlobalWorkerOptions.workerSrc = `//cdnjs.cloudflare.com/ajax/libs/pdf.js/${pdfjs.version}/pdf.worker.min.js`;

// Deep Zoom pyramid tiling (tiling.py / routes/upload_routes.py) — closes
// memory/TOGAL_PARITY_REAUDIT.md #11: rendering a full-resolution PDF page
// or raster image into one <canvas> (the fallback path below, kept for
// drawings whose tiles aren't ready yet) allocates the sheet's *entire*
// pixel footprint up front regardless of what's actually on screen — OOM
// risk on a large architectural sheet. OpenSeadragon instead only fetches
// the handful of tiles visible at the current zoom, however large the
// source is. A drawing uses the tiled path once its tile pyramid exists
// (usually within a few seconds of upload — the backend builds it as a
// background task); until then it falls back to the untiled renderer below.
const TILE_POLL_MS = 2500;
const TILE_POLL_MAX_ATTEMPTS = 40; // ~100s — generous for a big sheet's background tiling job

// Converts a click into "plan space" pixel coordinates — native image pixels
// for raster uploads, PDF points-at-scale-1 for PDFs — regardless of the
// current on-screen zoom. See routes/scale_routes.py for why this convention
// (it's the same pixel space ai/preprocessing.py rasterizes drawings into,
// and the same space the tiled path's OpenSeadragon image coordinates use).
function toPlanSpacePoint(e, rect, nativeWidth, nativeHeight) {
  return [
    ((e.clientX - rect.left) / rect.width) * nativeWidth,
    ((e.clientY - rect.top) / rect.height) * nativeHeight,
  ];
}

/**
 * @param {object} props
 * @param {boolean} [props.calibrating] - when true, the next two clicks on the
 *   plan are captured as a scale-calibration pair instead of normal interaction.
 * @param {(points: { point1: number[], point2: number[] }) => void} [props.onCalibrationPoints]
 * @param {boolean} [props.commentMode] - when true, a click drops a comment pin
 *   (via onCommentClick) instead of calibrating or panning.
 * @param {(point: number[]) => void} [props.onCommentClick] - plan-space [x,y]
 * @param {(point: number[]) => void} [props.onPointerMove] - fires on hover with
 *   plan-space [x,y]; used to broadcast live cursor position (realtime.py).
 * @param {Array<{user_id:number,name:string,color:string,x:number,y:number}>} [props.remoteCursors]
 *   - other users' live cursor positions on THIS drawing, in plan-space.
 * @param {Array<{id:number,x:number,y:number,resolved:boolean}>} [props.commentPins]
 *   - persisted comment pins on this drawing, in plan-space.
 * @param {(id:number) => void} [props.onPinClick]
 */
export default function DrawingRenderer({
  drawing, onLoad, calibrating = false, onCalibrationPoints,
  commentMode = false, onCommentClick, onPointerMove,
  remoteCursors = [], commentPins = [], onPinClick,
}) {
  const [numPages, setNumPages] = useState(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [scale, setScale] = useState(1);
  const [error, setError] = useState(null);
  const [pageNativeSize, setPageNativeSize] = useState(null); // PDF points at scale=1
  const [calScreenPoints, setCalScreenPoints] = useState([]); // for the on-screen marker overlay only
  const [tileMeta, setTileMeta] = useState(null); // null until this drawing's tile pyramid is ready
  const [osdTick, setOsdTick] = useState(0); // bumped on OSD pan/zoom so overlay positions recompute
  const canvasRef = useRef(null);
  const imageWrapRef = useRef(null);
  const pageWrapRef = useRef(null);
  const osdContainerRef = useRef(null);
  const osdViewerRef = useRef(null);
  const calibratingRef = useRef(calibrating); // OSD's click handler closes over this once — needs the live value
  const commentModeRef = useRef(commentMode);

  useEffect(() => {
    calibratingRef.current = calibrating;
  }, [calibrating]);

  useEffect(() => {
    commentModeRef.current = commentMode;
  }, [commentMode]);

  // Plan-set ingestion (memory/TOGAL_PARITY_REAUDIT.md #13): a sheet split
  // from a multi-page PDF has its own page_number (0-indexed) even though
  // it shares file_path with its siblings — react-pdf's pageNumber is
  // 1-indexed, so this is what opens the untiled fallback viewer directly
  // on the right page instead of always page 1. The tiled (OpenSeadragon)
  // path doesn't need this: each sheet's tile pyramid is already built
  // from just its own page (tiling.py), not the whole source file.
  useEffect(() => {
    setPageNumber((drawing?.page_number ?? 0) + 1);
  }, [drawing?.id]);

  useEffect(() => {
    if (drawing && drawing.file_type !== 'PDF' && !tileMeta) {
      loadImage();
    }
    // eslint-disable-next-line
  }, [drawing, tileMeta]);

  // Calibration is a fresh pick every time it's (re)entered.
  useEffect(() => {
    if (calibrating) setCalScreenPoints([]);
  }, [calibrating]);

  // Poll tile-pyramid status for the selected drawing; stop once ready (or
  // once we've given up — tiling may be permanently unavailable if Pillow
  // isn't installed server-side, see tiling.py's graceful-degradation gate).
  useEffect(() => {
    setTileMeta(null);
    setError(null);
    if (!drawing) return undefined;

    let cancelled = false;
    let attempts = 0;
    let timeoutId;

    async function poll() {
      try {
        const res = await uploadsAPI.getTileStatus(drawing.id);
        if (cancelled) return;
        if (res.data?.ready) {
          setTileMeta(res.data);
          setError(null); // clear a stale fallback-path error now that tiles have taken over
          return;
        }
      } catch {
        // leave tileMeta null — the untiled fallback renderer below handles it
      }
      attempts += 1;
      if (!cancelled && attempts < TILE_POLL_MAX_ATTEMPTS) {
        timeoutId = setTimeout(poll, TILE_POLL_MS);
      }
    }
    poll();

    return () => {
      cancelled = true;
      clearTimeout(timeoutId);
    };
  }, [drawing?.id]);

  // OpenSeadragon viewer lifecycle — mounts once tileMeta is ready, torn
  // down on drawing change/unmount.
  useEffect(() => {
    if (!tileMeta || !drawing || !osdContainerRef.current) return undefined;

    const apiUrl = import.meta.env.VITE_BACKEND_URL || '';
    const token = localStorage.getItem('auth_token');
    const tileSource = {
      width: tileMeta.width,
      height: tileMeta.height,
      tileSize: tileMeta.tile_size,
      tileOverlap: tileMeta.overlap,
      minLevel: 0,
      maxLevel: tileMeta.max_level,
      getTileUrl: (level, x, y) => `${apiUrl}/api/uploads/drawings/${drawing.id}/tiles/${level}/${x}_${y}.jpg`,
    };

    const viewer = OpenSeadragon({
      element: osdContainerRef.current,
      tileSources: tileSource,
      // Tile requests need the same Bearer auth as every other API call —
      // a plain <img> tag can't carry that header, so route tiles through XHR.
      loadTilesWithAjax: true,
      ajaxHeaders: token ? { Authorization: `Bearer ${token}` } : {},
      showNavigationControl: false,
      visibilityRatio: 1,
      constrainDuringPan: true,
      minZoomLevel: 0.8,
      maxZoomPixelRatio: 4,
      springStiffness: 12,
      // A takeoff sheet isn't a photo browser — clicks place calibration
      // points / (eventually) annotations, they shouldn't also zoom.
      gestureSettingsMouse: { clickToZoom: false },
      gestureSettingsTouch: { clickToZoom: false },
    });
    osdViewerRef.current = viewer;

    viewer.addHandler('open', () => {
      onLoad?.({ width: tileMeta.width, height: tileMeta.height });
    });

    viewer.addHandler('canvas-click', (event) => {
      if (!osdContainerRef.current) return;
      const viewportPoint = viewer.viewport.pointFromPixel(event.position);
      const imagePoint = viewer.viewport.viewportToImageCoordinates(viewportPoint);
      const point = [imagePoint.x, imagePoint.y];

      if (commentModeRef.current) {
        onCommentClick?.(point);
        return;
      }
      if (!calibratingRef.current) return;
      const rect = osdContainerRef.current.getBoundingClientRect();
      const screenPoint = { x: rect.left + event.position.x, y: rect.top + event.position.y };

      setCalScreenPoints((prev) => {
        const next = [...prev, { ...screenPoint, plan: point }];
        if (next.length === 2) {
          onCalibrationPoints?.({ point1: next[0].plan, point2: next[1].plan });
          return [];
        }
        return next;
      });
    });

    // Repositions remote-cursor/comment-pin overlays (rendered as plain
    // absolutely-positioned divs, not part of OSD's own canvas) whenever
    // the viewport pans or zooms.
    viewer.addHandler('animation', () => setOsdTick((t) => t + 1));
    viewer.addHandler('update-viewport', () => setOsdTick((t) => t + 1));

    return () => {
      viewer.destroy();
      osdViewerRef.current = null;
    };
    // eslint-disable-next-line
  }, [tileMeta, drawing?.id]);

  // Plan-space point -> pixel position relative to the OSD viewer element,
  // for overlay rendering. Recomputes on every `osdTick` bump above so
  // markers track pan/zoom instead of freezing at their first position.
  function osdImagePointToViewerPixel(x, y) {
    const viewer = osdViewerRef.current;
    if (!viewer) return null;
    const viewportPoint = viewer.viewport.imageToViewportCoordinates(x, y);
    const pixel = viewer.viewport.pixelFromPoint(viewportPoint, true);
    return { x: pixel.x, y: pixel.y };
  }

  function handleOsdPointerMove(e) {
    const viewer = osdViewerRef.current;
    if (!viewer || !osdContainerRef.current || !onPointerMove) return;
    const rect = osdContainerRef.current.getBoundingClientRect();
    const offset = new OpenSeadragon.Point(e.clientX - rect.left, e.clientY - rect.top);
    const viewportPoint = viewer.viewport.pointFromPixel(offset);
    const imagePoint = viewer.viewport.viewportToImageCoordinates(viewportPoint);
    onPointerMove([imagePoint.x, imagePoint.y]);
  }

  const loadImage = () => {
    if (!drawing || !canvasRef.current) return;

    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    const img = new Image();

    // A plain <img src> can't carry the Bearer token every other API call
    // needs (routes/upload_routes.py's file endpoint is auth-gated like
    // everything else) — fetch it as an authenticated blob instead and
    // point the <img> at an object URL.
    const apiUrl = import.meta.env.VITE_BACKEND_URL || '';
    const token = localStorage.getItem('auth_token');
    let objectUrl;

    fetch(`${apiUrl}/api/uploads/drawings/${drawing.id}/file`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.blob();
      })
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob);
        img.src = objectUrl;
      })
      .catch(() => setError('Failed to load image'));

    img.onload = () => {
      canvas.width = img.width;
      canvas.height = img.height;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0);
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      if (onLoad) {
        onLoad({ width: img.width, height: img.height });
      }
    };

    img.onerror = () => {
      setError('Failed to load image');
    };
  };

  const onDocumentLoadSuccess = ({ numPages }) => {
    setNumPages(numPages);
    if (onLoad) {
      onLoad({ numPages });
    }
  };

  const onDocumentLoadError = (error) => {
    console.error('PDF load error:', error);
    setError('Failed to load PDF');
  };

  const onPageLoadSuccess = (page) => {
    setPageNativeSize({ width: page.width, height: page.height });
  };

  function handleCalibrationClick(e, rect, nativeWidth, nativeHeight) {
    if (!nativeWidth || !nativeHeight) return;
    const point = toPlanSpacePoint(e, rect, nativeWidth, nativeHeight);

    if (commentMode) {
      onCommentClick?.(point);
      return;
    }
    if (!calibrating) return;
    // Viewport-relative (not element-relative): the canvas carries its own CSS
    // `transform: scale()`, which doesn't affect layout, so an element-relative
    // overlay would drift out of sync with the visually scaled canvas. Fixed
    // positioning at raw clientX/clientY sidesteps that entirely.
    const screenPoint = { x: e.clientX, y: e.clientY };

    setCalScreenPoints((prev) => {
      const next = [...prev, { ...screenPoint, plan: point }];
      if (next.length === 2) {
        onCalibrationPoints?.({ point1: next[0].plan, point2: next[1].plan });
        return []; // reset for next calibration attempt; parent owns the result now
      }
      return next;
    });
  }

  function handlePointerMove(e, rect, nativeWidth, nativeHeight) {
    if (!onPointerMove || !nativeWidth || !nativeHeight) return;
    onPointerMove(toPlanSpacePoint(e, rect, nativeWidth, nativeHeight));
  }

  // Plan-space -> viewport-fixed screen point, for the untiled paths (both
  // PDF and raster ultimately render into a rect measurable via
  // getBoundingClientRect(), which already reflects any CSS transform scale
  // — same convention CalibrationMarkers relies on).
  function planToFixedScreenPoint(rect, nativeWidth, nativeHeight, x, y) {
    return {
      x: rect.left + (x / nativeWidth) * rect.width,
      y: rect.top + (y / nativeHeight) * rect.height,
    };
  }

  function CalibrationMarkers() {
    if (calScreenPoints.length === 0) return null;
    return (
      <svg className="fixed inset-0 pointer-events-none z-50" width="100%" height="100%">
        {calScreenPoints.length === 2 && (
          <line
            x1={calScreenPoints[0].x} y1={calScreenPoints[0].y}
            x2={calScreenPoints[1].x} y2={calScreenPoints[1].y}
            stroke="#f59e0b" strokeWidth="2" strokeDasharray="6 4"
          />
        )}
        {calScreenPoints.map((p, i) => (
          <g key={i}>
            <circle cx={p.x} cy={p.y} r="6" fill="#f59e0b" stroke="#fff" strokeWidth="2" />
          </g>
        ))}
      </svg>
    );
  }

  // Live cursor + pinned-comment markers — real-time collaboration
  // (memory/TOGAL_PARITY_REAUDIT.md #16, realtime.py). `screenPointFor`
  // abstracts over the two rendering paths (OSD viewer-relative pixels vs.
  // the untiled fallback's fixed-viewport screen point) so this one
  // component works for both.
  function CollabOverlay({ screenPointFor }) {
    if (remoteCursors.length === 0 && commentPins.length === 0) return null;
    return (
      <>
        {remoteCursors.map((c) => {
          const p = screenPointFor(c.x, c.y);
          if (!p) return null;
          return (
            <div
              key={`cursor-${c.user_id}`}
              className="fixed z-50 pointer-events-none flex items-center gap-1"
              style={{ left: p.x, top: p.y, transform: 'translate(-2px, -2px)' }}
            >
              <svg width="16" height="16" viewBox="0 0 16 16" style={{ filter: 'drop-shadow(0 1px 1px rgba(0,0,0,0.4))' }}>
                <path d="M1 1 L1 14 L5 11 L7.5 15.5 L9.5 14.5 L7 10 L13 10 Z" fill={c.color} stroke="#fff" strokeWidth="1" />
              </svg>
              <span className="px-1.5 py-0.5 rounded text-[10px] font-medium text-white whitespace-nowrap" style={{ background: c.color }}>
                {c.name}
              </span>
            </div>
          );
        })}
        {commentPins.map((pin) => {
          const p = screenPointFor(pin.x, pin.y);
          if (!p) return null;
          return (
            <button
              key={`pin-${pin.id}`}
              onClick={(e) => { e.stopPropagation(); onPinClick?.(pin.id); }}
              className="fixed z-50 w-5 h-5 rounded-full rounded-bl-none border-2 border-white shadow-md flex items-center justify-center text-[9px] font-bold text-white"
              style={{ left: p.x, top: p.y, transform: 'translate(-2px, -20px) rotate(45deg)', background: pin.resolved ? '#94a3b8' : '#f43f5e' }}
              title={pin.resolved ? 'Resolved comment' : 'Open comment'}
            >
              <span style={{ transform: 'rotate(-45deg)' }}>{pin.resolved ? '✓' : '!'}</span>
            </button>
          );
        })}
      </>
    );
  }

  if (!drawing) {
    return (
      <div className="w-full h-full flex items-center justify-center text-slate-400">
        <p>No drawing selected</p>
      </div>
    );
  }

  // Tiled pyramid render — checked before `error` below: it's fetched via a
  // separate, independent poll, so a stale error from the untiled fallback
  // (e.g. a slow/failed direct file fetch that lost the race with tiles
  // becoming ready) shouldn't block switching over once tiles exist.
  if (tileMeta) {
    return (
      <div className="w-full h-full relative bg-slate-800">
        <div
          ref={osdContainerRef}
          className="w-full h-full"
          style={{ cursor: calibrating || commentMode ? 'crosshair' : undefined }}
          onMouseMove={handleOsdPointerMove}
        />
        <CalibrationMarkers />
        <CollabOverlay
          screenPointFor={(x, y) => {
            if (!osdContainerRef.current) return null;
            const pixel = osdImagePointToViewerPixel(x, y);
            if (!pixel) return null;
            const rect = osdContainerRef.current.getBoundingClientRect();
            void osdTick; // recompute this callback's closure whenever the viewport moves
            return { x: rect.left + pixel.x, y: rect.top + pixel.y };
          }}
        />
        <div className="absolute top-4 left-4 flex items-center gap-2 p-2 bg-slate-900/90 backdrop-blur rounded-lg">
          <button
            onClick={() => osdViewerRef.current?.viewport.zoomBy(0.7).applyConstraints()}
            className="px-2 py-1 text-xs bg-slate-700 text-white rounded"
          >
            -
          </button>
          <button
            onClick={() => osdViewerRef.current?.viewport.goHome()}
            className="px-2 py-1 text-xs bg-slate-700 text-white rounded"
          >
            Fit
          </button>
          <button
            onClick={() => osdViewerRef.current?.viewport.zoomBy(1.4).applyConstraints()}
            className="px-2 py-1 text-xs bg-slate-700 text-white rounded"
          >
            +
          </button>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="w-full h-full flex items-center justify-center text-rose-400">
        <p>{error}</p>
      </div>
    );
  }

  // Render PDF
  if (drawing.file_type === 'PDF') {
    const apiUrl = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000';
    const token = localStorage.getItem('auth_token');
    const fileUrl = { url: `${apiUrl}/api/uploads/drawings/${drawing.id}/file`, httpHeaders: token ? { Authorization: `Bearer ${token}` } : {} };

    return (
      <div className="w-full h-full overflow-auto flex flex-col items-center bg-slate-800">
        {/* PDF Controls */}
        <div className="sticky top-0 z-10 flex items-center gap-2 p-2 bg-slate-900/90 backdrop-blur rounded-lg mb-2">
          <button
            onClick={() => setPageNumber(Math.max(1, pageNumber - 1))}
            disabled={pageNumber <= 1}
            className="px-2 py-1 text-xs bg-slate-700 text-white rounded disabled:opacity-50"
          >
            Previous
          </button>
          <span className="text-xs text-white">
            Page {pageNumber} of {numPages || '?'}
          </span>
          <button
            onClick={() => setPageNumber(Math.min(numPages, pageNumber + 1))}
            disabled={pageNumber >= numPages}
            className="px-2 py-1 text-xs bg-slate-700 text-white rounded disabled:opacity-50"
          >
            Next
          </button>
          <div className="w-px h-4 bg-slate-600 mx-1" />
          <button
            onClick={() => setScale(Math.max(0.5, scale - 0.25))}
            className="px-2 py-1 text-xs bg-slate-700 text-white rounded"
          >
            -
          </button>
          <span className="text-xs text-white">{Math.round(scale * 100)}%</span>
          <button
            onClick={() => setScale(Math.min(3, scale + 0.25))}
            className="px-2 py-1 text-xs bg-slate-700 text-white rounded"
          >
            +
          </button>
        </div>

        {/* PDF Document */}
        <div
          ref={pageWrapRef}
          className={`relative inline-block ${calibrating || commentMode ? 'cursor-crosshair' : ''}`}
          onClick={(e) => {
            if (!pageWrapRef.current || !pageNativeSize) return;
            const rect = pageWrapRef.current.getBoundingClientRect();
            handleCalibrationClick(e, rect, pageNativeSize.width, pageNativeSize.height);
          }}
          onMouseMove={(e) => {
            if (!pageWrapRef.current || !pageNativeSize) return;
            const rect = pageWrapRef.current.getBoundingClientRect();
            handlePointerMove(e, rect, pageNativeSize.width, pageNativeSize.height);
          }}
        >
          <Document
            file={fileUrl}
            onLoadSuccess={onDocumentLoadSuccess}
            onLoadError={onDocumentLoadError}
            loading={
              <div className="flex items-center justify-center p-8">
                <div className="text-white text-sm">Loading PDF...</div>
              </div>
            }
          >
            <Page pageNumber={pageNumber} scale={scale} onLoadSuccess={onPageLoadSuccess} />
          </Document>
          <CalibrationMarkers />
          <CollabOverlay
            screenPointFor={(x, y) => {
              if (!pageWrapRef.current || !pageNativeSize) return null;
              const rect = pageWrapRef.current.getBoundingClientRect();
              return planToFixedScreenPoint(rect, pageNativeSize.width, pageNativeSize.height, x, y);
            }}
          />
        </div>
      </div>
    );
  }

  // Render Image (PNG, JPG, TIFF)
  return (
    <div className="w-full h-full overflow-auto flex items-center justify-center bg-slate-800">
      <div
        ref={imageWrapRef}
        className={`relative inline-block ${calibrating || commentMode ? 'cursor-crosshair' : ''}`}
        onClick={(e) => {
          if (!canvasRef.current) return;
          const rect = canvasRef.current.getBoundingClientRect();
          handleCalibrationClick(e, rect, canvasRef.current.width, canvasRef.current.height);
        }}
        onMouseMove={(e) => {
          if (!canvasRef.current) return;
          const rect = canvasRef.current.getBoundingClientRect();
          handlePointerMove(e, rect, canvasRef.current.width, canvasRef.current.height);
        }}
      >
        <canvas
          ref={canvasRef}
          style={{ transform: `scale(${scale})`, transformOrigin: 'center' }}
          className="max-w-full"
        />
        <CalibrationMarkers />
        <CollabOverlay
          screenPointFor={(x, y) => {
            if (!canvasRef.current) return null;
            const rect = canvasRef.current.getBoundingClientRect();
            return planToFixedScreenPoint(rect, canvasRef.current.width, canvasRef.current.height, x, y);
          }}
        />
      </div>

      {/* Image Controls */}
      <div className="absolute top-4 left-4 flex items-center gap-2 p-2 bg-slate-900/90 backdrop-blur rounded-lg">
        <button
          onClick={() => setScale(Math.max(0.5, scale - 0.25))}
          className="px-2 py-1 text-xs bg-slate-700 text-white rounded"
        >
          -
        </button>
        <span className="text-xs text-white">{Math.round(scale * 100)}%</span>
        <button
          onClick={() => setScale(Math.min(3, scale + 0.25))}
          className="px-2 py-1 text-xs bg-slate-700 text-white rounded"
        >
          +
        </button>
      </div>
    </div>
  );
}
