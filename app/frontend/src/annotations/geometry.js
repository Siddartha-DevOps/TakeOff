// Geometry math for the unified annotation model.
// All functions operate on plan-space coordinates ([[x,y], ...]) — no screen/pixel concerns here.

function round2(n) {
  return Math.round(n * 100) / 100;
}

export function polygonArea(points) {
  if (!points || points.length < 3) return 0;
  let sum = 0;
  for (let i = 0; i < points.length; i++) {
    const [x1, y1] = points[i];
    const [x2, y2] = points[(i + 1) % points.length];
    sum += x1 * y2 - x2 * y1;
  }
  return Math.abs(sum) / 2;
}

export function polylineLength(points) {
  if (!points || points.length < 2) return 0;
  let len = 0;
  for (let i = 0; i < points.length - 1; i++) {
    const [x1, y1] = points[i];
    const [x2, y2] = points[i + 1];
    len += Math.hypot(x2 - x1, y2 - y1);
  }
  return len;
}

export function rectFromBbox([x1, y1, x2, y2]) {
  return [
    [x1, y1],
    [x2, y1],
    [x2, y2],
    [x1, y2],
  ];
}

/** Axis-aligned bounding box [x1,y1,x2,y2] of any geometry — used for box-select hit-testing. */
export function boundsOf(points) {
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}

export function rectsIntersect([ax1, ay1, ax2, ay2], [bx1, by1, bx2, by2]) {
  return ax1 <= bx2 && ax2 >= bx1 && ay1 <= by2 && ay2 >= by1;
}

/** Snap a plan-space point to an existing vertex or a fixed angle. */
export function snapPoint(point, {
  anchor = null,
  vertices = [],
  tolerance = 0,
  angleStep = 45,
} = {}) {
  const [x, y] = point;
  let nearest = null;
  let nearestDistance = Number.POSITIVE_INFINITY;
  for (const vertex of vertices) {
    const distance = Math.hypot(vertex[0] - x, vertex[1] - y);
    if (distance <= tolerance && distance < nearestDistance) {
      nearest = vertex;
      nearestDistance = distance;
    }
  }
  // Joining existing geometry takes priority over the angle guide.
  if (nearest) return [...nearest];
  if (!anchor || !Number.isFinite(angleStep) || angleStep <= 0) return [x, y];

  const dx = x - anchor[0];
  const dy = y - anchor[1];
  const distance = Math.hypot(dx, dy);
  if (distance === 0) return [x, y];
  const step = (angleStep * Math.PI) / 180;
  const angle = Math.round(Math.atan2(dy, dx) / step) * step;
  return [anchor[0] + Math.cos(angle) * distance, anchor[1] + Math.sin(angle) * distance];
}

/**
 * The single source of truth for `measuredValue`. Called on every geometry
 * mutation and on ingest (AI output, deserialize) so AI and manual shapes are
 * measured identically and a stale/reported value can never leak through.
 * @param {import('./types').Annotation} annotation
 */
export function planUnitsToFeet(value, scaleRatio, fileType = 'PDF') {
  if (!Number.isFinite(value) || !Number.isFinite(scaleRatio) || scaleRatio <= 0) return 0;
  const planUnitsPerInch = String(fileType).toUpperCase() === 'PDF' ? 72 : 300;
  return (value * scaleRatio) / (planUnitsPerInch * 12);
}

/**
 * Compute a takeoff quantity from plan geometry. With a confirmed drawing
 * scale this returns real square feet / linear feet; without one it falls
 * back to plan-space units for backwards-compatible annotation ingest.
 */
export function computeMeasuredValue(annotation, measurementContext = null) {
  const scaleRatio = Number(measurementContext?.scaleRatio);
  const hasScale = Number.isFinite(scaleRatio) && scaleRatio > 0;
  const feetPerPlanUnit = hasScale
    ? planUnitsToFeet(1, scaleRatio, measurementContext?.fileType)
    : 1;

  switch (annotation.type) {
    case 'area':
      return round2(polygonArea(annotation.geometry) * feetPerPlanUnit ** 2);
    case 'line':
      return round2(polylineLength(annotation.geometry) * feetPerPlanUnit);
    case 'count':
      return 1;
    default:
      return 0;
  }
}
