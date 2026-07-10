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

/**
 * The single source of truth for `measuredValue`. Called on every geometry
 * mutation and on ingest (AI output, deserialize) so AI and manual shapes are
 * measured identically and a stale/reported value can never leak through.
 * @param {import('./types').Annotation} annotation
 */
export function computeMeasuredValue(annotation) {
  switch (annotation.type) {
    case 'area':
      return round2(polygonArea(annotation.geometry));
    case 'line':
      return round2(polylineLength(annotation.geometry));
    case 'count':
      return 1;
    default:
      return 0;
  }
}
