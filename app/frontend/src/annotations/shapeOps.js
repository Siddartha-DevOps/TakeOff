// Advanced takeoff tools — Togal parity: "Advanced tools (split/merge/cut/backout)".
// Real polygon boolean ops (union/difference/intersection) via polygon-clipping
// (Martinez-Rueda algorithm), not a hand-rolled approximation — the same class
// of operation Bluebeam/Togal's own split/merge/cutout tools do.
//
// Honest scope limit, stated up front: the unified Annotation model
// (annotations/types.js) stores geometry as a single flat ring
// (`number[][]`), with no support for polygons-with-holes. A backout whose
// deducted shape is fully enclosed inside the base shape (never touching its
// boundary) produces exactly that — a ring with a hole — which this module
// cannot represent. It's detected and rejected with a clear error rather
// than silently dropping the hole (which would overstate the area) or
// silently keeping only the outer ring. Extending the Annotation model to
// carry holes is a real, separate, larger change, not taken on here.

import polygonClipping from 'polygon-clipping';

function toRing(points) {
  const ring = points.map(([x, y]) => [x, y]);
  const [x0, y0] = ring[0];
  const [xn, yn] = ring[ring.length - 1];
  if (x0 !== xn || y0 !== yn) ring.push([x0, y0]); // polygon-clipping expects closed rings
  return ring;
}

function fromRing(ring) {
  // Drop the closing duplicate point polygon-clipping/us both use.
  const pts = ring.map(([x, y]) => [x, y]);
  const [x0, y0] = pts[0];
  const [xn, yn] = pts[pts.length - 1];
  if (pts.length > 1 && x0 === xn && y0 === yn) pts.pop();
  return pts;
}

function singlePolygon(points) {
  return [[toRing(points)]]; // MultiPolygon with exactly one Polygon, one ring
}

// Unwraps a polygon-clipping MultiPolygon result into a single simple-ring
// geometry, or throws a clear, specific error for every shape this module
// can't represent (disjoint pieces, holes, empty result).
function expectSingleSimplePolygon(multiPolygon, { emptyMessage, multiMessage, holeMessage }) {
  if (!multiPolygon || multiPolygon.length === 0) {
    throw new Error(emptyMessage);
  }
  if (multiPolygon.length > 1) {
    throw new Error(multiMessage);
  }
  const polygon = multiPolygon[0]; // array of rings: [exterior, ...holes]
  if (polygon.length > 1) {
    throw new Error(holeMessage);
  }
  return fromRing(polygon[0]);
}

/** Union of 2+ area annotations' geometry into one. Shapes must overlap or share an edge — a Merge across disjoint shapes isn't one polygon and is rejected rather than silently keeping only one piece. */
export function mergeAreaGeometry(geometries) {
  if (geometries.length < 2) throw new Error('Select at least 2 area shapes to merge');
  const polys = geometries.map((g) => singlePolygon(g));
  const result = polygonClipping.union(...polys);
  return expectSingleSimplePolygon(result, {
    emptyMessage: 'Merge produced no area — check the selected shapes',
    multiMessage: "These shapes don't touch or overlap, so merging them wouldn't be one continuous shape",
    holeMessage: 'Merging these shapes would leave a hole in the middle, which is not supported',
  });
}

/** base minus deduct — e.g. deduct a stairwell opening from a floor area. */
export function backoutAreaGeometry(baseGeometry, deductGeometry) {
  const result = polygonClipping.difference(singlePolygon(baseGeometry), singlePolygon(deductGeometry));
  return expectSingleSimplePolygon(result, {
    emptyMessage: 'Backout removed the entire shape — nothing left to keep',
    multiMessage: 'This deduction splits the shape into two disconnected pieces — use Split instead, or deduct a shape that touches the edge',
    holeMessage: 'This deduction is fully enclosed inside the shape, which would leave a hole — not supported. Extend the deduction shape to touch the boundary instead.',
  });
}

function extendSegmentAcrossBounds(p1, p2, bounds) {
  const [x1, y1] = p1, [x2, y2] = p2;
  const dx = x2 - x1, dy = y2 - y1;
  const len = Math.hypot(dx, dy);
  if (len === 0) throw new Error('Cut line has zero length');
  const ux = dx / len, uy = dy / len;
  const [bx1, by1, bx2, by2] = bounds;
  const diag = Math.hypot(bx2 - bx1, by2 - by1) * 4 + 1; // comfortably past the shape either direction
  return [[x1 - ux * diag, y1 - uy * diag], [x2 + ux * diag, y2 + uy * diag]];
}

/**
 * Splits `targetGeometry` (an area shape) into two pieces along `cutLine`
 * (a line annotation's geometry — just its first and last point are used,
 * extended across the target's bounding box so the user doesn't have to
 * draw the line perfectly edge-to-edge). Returns [pieceA, pieceB].
 */
export function splitAreaGeometry(targetGeometry, cutLine) {
  if (!cutLine || cutLine.length < 2) throw new Error('Draw a line across the shape to use as the cut line');

  const xs = targetGeometry.map((p) => p[0]);
  const ys = targetGeometry.map((p) => p[1]);
  const bounds = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
  const [a, b] = extendSegmentAcrossBounds(cutLine[0], cutLine[cutLine.length - 1], bounds);

  // Perpendicular offset far enough to form a "slab" (half-plane rectangle)
  // fully covering the target shape on each side of the (extended) line.
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const len = Math.hypot(dx, dy) || 1;
  const nx = -dy / len, ny = dx / len; // unit normal
  const reach = Math.hypot(bounds[2] - bounds[0], bounds[3] - bounds[1]) * 2 + 1;

  const slabSide1 = [
    [a[0] + nx * reach, a[1] + ny * reach],
    [b[0] + nx * reach, b[1] + ny * reach],
    [b[0], b[1]],
    [a[0], a[1]],
  ];
  const slabSide2 = [
    [a[0] - nx * reach, a[1] - ny * reach],
    [b[0] - nx * reach, b[1] - ny * reach],
    [b[0], b[1]],
    [a[0], a[1]],
  ];

  const target = singlePolygon(targetGeometry);
  const crossMessages = {
    emptyMessage: "Cut line doesn't cross the shape — draw it all the way through",
    multiMessage: 'Cut line crosses the shape more than once — draw a single straight cut',
    holeMessage: 'Cut produced an unsupported hole',
  };
  const side1 = expectSingleSimplePolygon(polygonClipping.intersection(target, singlePolygon(slabSide1)), crossMessages);
  const side2 = expectSingleSimplePolygon(polygonClipping.intersection(target, singlePolygon(slabSide2)), crossMessages);
  return [side1, side2];
}

/**
 * Joins line annotations into one continuous polyline, in the order given —
 * unlike area merge (a true geometric union), a line "merge" is just
 * concatenation, so the caller (UI) should let the user pick the order.
 * Errors if any segment doesn't connect within `tolerance` plan-space units
 * of the running line's current end, so this can't silently produce a
 * polyline with a visible jump in it.
 */
export function mergeLineGeometry(geometries, tolerance = 1e-6) {
  if (geometries.length < 2) throw new Error('Select at least 2 line shapes to merge');
  let joined = [...geometries[0]];
  for (let i = 1; i < geometries.length; i++) {
    const next = geometries[i];
    const end = joined[joined.length - 1];
    const distToStart = Math.hypot(next[0][0] - end[0], next[0][1] - end[1]);
    const distToEnd = Math.hypot(next[next.length - 1][0] - end[0], next[next.length - 1][1] - end[1]);
    if (distToStart <= tolerance) {
      joined = joined.concat(next.slice(1));
    } else if (distToEnd <= tolerance) {
      joined = joined.concat([...next].reverse().slice(1));
    } else {
      throw new Error(`Line ${i + 1} doesn't connect to the previous one — lines must share an endpoint to merge`);
    }
  }
  return joined;
}
