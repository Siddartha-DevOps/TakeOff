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

export function pointInPolygon([x, y], points) {
  if (!points || points.length < 3) return false;
  let inside = false;
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    const [xi, yi] = points[i];
    const [xj, yj] = points[j];
    const onEdge = Math.abs((y - yi) * (xj - xi) - (x - xi) * (yj - yi)) < 1e-7
      && x >= Math.min(xi, xj) - 1e-7 && x <= Math.max(xi, xj) + 1e-7
      && y >= Math.min(yi, yj) - 1e-7 && y <= Math.max(yi, yj) + 1e-7;
    if (onEdge) return true;
    if (((yi > y) !== (yj > y)) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

export function ringInsidePolygon(ring, outer) {
  if (!ring || ring.length < 3 || !outer || outer.length < 3) return false;
  return ring.every((point, index) => {
    const next = ring[(index + 1) % ring.length];
    const midpoint = [(point[0] + next[0]) / 2, (point[1] + next[1]) / 2];
    return pointInPolygon(point, outer) && pointInPolygon(midpoint, outer);
  });
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

export function arcLength(points) {
  if (!points || points.length !== 3) return polylineLength(points);
  const [a, b, c] = points;
  const d = 2 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]));
  if (Math.abs(d) < 1e-9) return polylineLength(points);
  const aa = a[0] ** 2 + a[1] ** 2;
  const bb = b[0] ** 2 + b[1] ** 2;
  const cc = c[0] ** 2 + c[1] ** 2;
  const center = [
    (aa * (b[1] - c[1]) + bb * (c[1] - a[1]) + cc * (a[1] - b[1])) / d,
    (aa * (c[0] - b[0]) + bb * (a[0] - c[0]) + cc * (b[0] - a[0])) / d,
  ];
  const angles = [a, b, c].map(([x, y]) => Math.atan2(y - center[1], x - center[0]));
  const normalize = (value) => (value + Math.PI * 2) % (Math.PI * 2);
  const ccwTotal = normalize(angles[2] - angles[0]);
  const ccwMiddle = normalize(angles[1] - angles[0]);
  const sweep = ccwMiddle <= ccwTotal ? ccwTotal : Math.PI * 2 - ccwTotal;
  return Math.hypot(a[0] - center[0], a[1] - center[1]) * sweep;
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
export function planUnitsToFeet(value, scaleRatio, fileType = 'PDF', planDpi = null) {
  if (!Number.isFinite(value) || !Number.isFinite(scaleRatio) || scaleRatio <= 0) return 0;
  const planUnitsPerInch = String(fileType).toUpperCase() === 'PDF'
    ? 72
    : Number(planDpi);
  if (!Number.isFinite(planUnitsPerInch) || planUnitsPerInch <= 0) return 0;
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
    ? planUnitsToFeet(1, scaleRatio, measurementContext?.fileType, measurementContext?.planDpi)
    // A null context is used by geometry-only editor unit operations and
    // intentionally returns plan units. Product callers always pass a
    // drawing context; an unconfirmed/invalid context must yield no trusted
    // measured length/area.
    : (measurementContext == null ? 1 : 0);

  switch (annotation.type) {
    case 'area':
      return round2(Math.max(0, polygonArea(annotation.geometry) - (annotation.holes || []).reduce((sum, ring) => sum + polygonArea(ring), 0)) * feetPerPlanUnit ** 2);
    case 'line':
      return round2((annotation.meta?.curve === 'arc' ? arcLength(annotation.geometry) : polylineLength(annotation.geometry)) * feetPerPlanUnit);
    case 'count':
      return 1;
    default:
      return 0;
  }
}
