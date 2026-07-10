import React, { useState, useEffect, useRef } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";

// Configure PDF.js worker
pdfjs.GlobalWorkerOptions.workerSrc = `//cdnjs.cloudflare.com/ajax/libs/pdf.js/${pdfjs.version}/pdf.worker.min.js`;

// Converts a click into "plan space" pixel coordinates — native image pixels
// for raster uploads, PDF points-at-scale-1 for PDFs — regardless of the
// current on-screen zoom. See routes/scale_routes.py for why this convention
// (it's the same pixel space ai/preprocessing.py rasterizes drawings into).
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
 */
export default function DrawingRenderer({ drawing, onLoad, calibrating = false, onCalibrationPoints }) {
  const [numPages, setNumPages] = useState(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [scale, setScale] = useState(1);
  const [error, setError] = useState(null);
  const [pageNativeSize, setPageNativeSize] = useState(null); // PDF points at scale=1
  const [calScreenPoints, setCalScreenPoints] = useState([]); // for the on-screen marker overlay only
  const canvasRef = useRef(null);
  const imageWrapRef = useRef(null);
  const pageWrapRef = useRef(null);

  useEffect(() => {
    if (drawing && drawing.file_type !== 'PDF') {
      loadImage();
    }
  }, [drawing]);

  // Calibration is a fresh pick every time it's (re)entered.
  useEffect(() => {
    if (calibrating) setCalScreenPoints([]);
  }, [calibrating]);

  const loadImage = () => {
    if (!drawing || !canvasRef.current) return;

    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    const img = new Image();

    const apiUrl = import.meta.env.VITE_BACKEND_URL || '';
    img.src = `${apiUrl}/api/uploads/drawings/${drawing.id}/file`;

    img.onload = () => {
      canvas.width = img.width;
      canvas.height = img.height;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0);
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
    if (!calibrating || !nativeWidth || !nativeHeight) return;
    const point = toPlanSpacePoint(e, rect, nativeWidth, nativeHeight);
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

  if (!drawing) {
    return (
      <div className="w-full h-full flex items-center justify-center text-slate-400">
        <p>No drawing selected</p>
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
    const fileUrl = `${apiUrl}/api/uploads/drawings/${drawing.id}/file`;

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
          className={`relative inline-block ${calibrating ? 'cursor-crosshair' : ''}`}
          onClick={(e) => {
            if (!pageWrapRef.current || !pageNativeSize) return;
            const rect = pageWrapRef.current.getBoundingClientRect();
            handleCalibrationClick(e, rect, pageNativeSize.width, pageNativeSize.height);
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
        </div>
      </div>
    );
  }

  // Render Image (PNG, JPG, TIFF)
  return (
    <div className="w-full h-full overflow-auto flex items-center justify-center bg-slate-800">
      <div
        ref={imageWrapRef}
        className={`relative inline-block ${calibrating ? 'cursor-crosshair' : ''}`}
        onClick={(e) => {
          if (!canvasRef.current) return;
          const rect = canvasRef.current.getBoundingClientRect();
          handleCalibrationClick(e, rect, canvasRef.current.width, canvasRef.current.height);
        }}
      >
        <canvas
          ref={canvasRef}
          style={{ transform: `scale(${scale})`, transformOrigin: 'center' }}
          className="max-w-full"
        />
        <CalibrationMarkers />
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
