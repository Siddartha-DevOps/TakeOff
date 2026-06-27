import React from 'react';

/**
 * Renders AUTODETECT results (Area polygons / Line walls / labels) as an SVG
 * overlay aligned exactly on top of the rendered PDF page.
 *
 * Coordinates come from the backend in PDF points (top-left origin, y-down —
 * the same convention pdf.js uses), so a point (x, y) maps to a pixel
 * (x * scale, y * scale) on a <Page scale={scale}>. The SVG is sized to the
 * page's point dimensions times the render scale and positioned over the page.
 *
 * Props:
 *   result   — autodetect response: { page:{width_pt,height_pt}, area:[...] }
 *   scale    — the react-pdf render scale (1.0 = 72 DPI = 1pt per CSS px)
 *   layers   — { rooms, walls, ... } visibility toggles
 *   selectedId, onSelect
 */
export default function DetectionOverlay({ result, scale = 1, layers = {}, selectedId, onSelect }) {
  const page = result?.page;
  const spaces = result?.area || [];
  if (!page || !page.width_pt) return null;

  const w = page.width_pt * scale;
  const h = page.height_pt * scale;

  const ringFromGeojson = (geojson) => {
    if (!geojson || geojson.type !== 'Polygon' || !geojson.coordinates?.length) return null;
    return geojson.coordinates[0].map(([x, y]) => `${(x * scale).toFixed(1)},${(y * scale).toFixed(1)}`).join(' ');
  };

  return (
    <svg
      width={w}
      height={h}
      viewBox={`0 0 ${w} ${h}`}
      className="absolute top-0 left-0 pointer-events-none"
      style={{ zIndex: 5 }}
    >
      {layers.rooms !== false &&
        spaces.map((s) => {
          const pts = ringFromGeojson(s.geojson);
          const sel = selectedId === s.id;
          // Fall back to bbox if no polygon ring is available.
          const cx = s.centroid ? s.centroid[0] * scale : (s.bbox ? ((s.bbox[0] + s.bbox[2]) / 2) * scale : 0);
          const cy = s.centroid ? s.centroid[1] * scale : (s.bbox ? ((s.bbox[1] + s.bbox[3]) / 2) * scale : 0);
          return (
            <g key={s.id} style={{ pointerEvents: 'auto', cursor: 'pointer' }} onClick={(e) => { e.stopPropagation(); onSelect?.(s.id); }}>
              {pts ? (
                <polygon
                  points={pts}
                  fill="#6366f1"
                  fillOpacity={sel ? 0.42 : 0.2}
                  stroke={sel ? '#4338ca' : '#6366f1'}
                  strokeWidth={sel ? 2.5 : 1.5}
                />
              ) : s.bbox ? (
                <rect
                  x={s.bbox[0] * scale}
                  y={s.bbox[1] * scale}
                  width={(s.bbox[2] - s.bbox[0]) * scale}
                  height={(s.bbox[3] - s.bbox[1]) * scale}
                  fill="#6366f1"
                  fillOpacity={sel ? 0.42 : 0.2}
                  stroke="#6366f1"
                  strokeWidth={1.5}
                />
              ) : null}
              <g transform={`translate(${cx},${cy})`} style={{ pointerEvents: 'none' }}>
                <text textAnchor="middle" fontSize="11" fontWeight="600" fill="#1e293b">{s.label || 'Space'}</text>
                {s.sqft != null && (
                  <text y="13" textAnchor="middle" fontSize="9" fill="#475569" fontFamily="monospace">{s.sqft} sf</text>
                )}
              </g>
            </g>
          );
        })}
    </svg>
  );
}
