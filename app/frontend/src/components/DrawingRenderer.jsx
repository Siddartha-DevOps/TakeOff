import React, { useState, useEffect, useRef } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";

// Configure PDF.js worker
pdfjs.GlobalWorkerOptions.workerSrc = `//cdnjs.cloudflare.com/ajax/libs/pdf.js/${pdfjs.version}/pdf.worker.min.js`;

export default function DrawingRenderer({ drawing, onLoad }) {
  const [numPages, setNumPages] = useState(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [scale, setScale] = useState(1);
  const [error, setError] = useState(null);
  const canvasRef = useRef(null);

  useEffect(() => {
    if (drawing && drawing.file_type !== 'PDF') {
      loadImage();
    }
  }, [drawing]);

  const loadImage = () => {
    if (!drawing || !canvasRef.current) return;

    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    const img = new Image();

    const apiUrl = process.env.REACT_APP_BACKEND_URL || '';
    img.src = `${apiUrl}/api/uploads/drawings/${drawing.id}/file`;

    img.onload = () => {  // Fix 1: added missing opening brace
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
    const apiUrl = process.env.REACT_APP_BACKEND_URL || 'https://mock-takeoff.preview.emergentagent.com';
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
          <Page pageNumber={pageNumber} scale={scale} />
        </Document>
      </div>
    );
  }

  // Render Image (PNG, JPG, TIFF)
  return (
    <div className="w-full h-full overflow-auto flex items-center justify-center bg-slate-800">
      <canvas
        ref={canvasRef}
        style={{ transform: `scale(${scale})`, transformOrigin: 'center' }}
        className="max-w-full"
      />

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
}  // Fix 2: removed stray colon at end of file