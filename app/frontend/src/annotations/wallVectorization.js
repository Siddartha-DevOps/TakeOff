// True wall vectorization — typed centerline segments derived from detected
// room bboxes, mirroring app/backend/ai/wall_vectorization.py exactly (same
// sweep-line algorithm) so the demo canvas and the backend agree on what a
// "wall" is instead of CanvasFull's old hardcoded decorative SVG lines.
//
// Two rooms whose bbox edges are collinear and overlap share a wall — the
// overlapping span is an INTERIOR wall segment. Any edge span not shared
// with another room is on the building envelope — an EXTERIOR wall segment.

function snap(value, tol) {
  return tol ? Math.round(value / tol) * tol : value;
}

function roomEdges(room) {
  const [x1, y1, x2, y2] = room.bbox;
  const rid = room.id;
  return [
    ['h', y1, x1, x2, rid], // top
    ['h', y2, x1, x2, rid], // bottom
    ['v', x1, y1, y2, rid], // left
    ['v', x2, y1, y2, rid], // right
  ];
}

function sweepGroup(edges) {
  const breakpoints = [...new Set(edges.flatMap(([s, e]) => [s, e]))].sort((a, b) => a - b);
  const raw = [];
  for (let i = 0; i < breakpoints.length - 1; i++) {
    const p0 = breakpoints[i];
    const p1 = breakpoints[i + 1];
    if (p1 - p0 < 1e-6) continue;
    const mid = (p0 + p1) / 2;
    const covering = [...new Set(edges.filter(([s, e]) => s <= mid && mid <= e).map(([, , rid]) => rid))].sort();
    if (covering.length === 0) continue;
    const wallType = covering.length >= 2 ? 'interior' : 'exterior';
    raw.push([p0, p1, wallType, covering]);
  }

  const merged = [];
  for (const seg of raw) {
    const last = merged[merged.length - 1];
    if (last && last[2] === seg[2] && JSON.stringify(last[3]) === JSON.stringify(seg[3]) && Math.abs(last[1] - seg[0]) < 1e-6) {
      last[1] = seg[1];
    } else {
      merged.push(seg);
    }
  }
  return merged;
}

/**
 * @param {Array<{id:string, bbox:number[]}>} rooms
 * @param {number} tol - snapping tolerance for bucketing near-collinear edges
 * @returns {Array<{id:string, wallType:'interior'|'exterior', geometry:number[][], lengthPx:number, roomIds:string[]}>}
 */
export function vectorizeWallsFromRooms(rooms, tol = 6) {
  const groups = new Map();
  for (const room of rooms) {
    if (!room.bbox) continue;
    for (const [orientation, fixed, s0, e0, rid] of roomEdges(room)) {
      const s = Math.min(s0, e0);
      const e = Math.max(s0, e0);
      const key = `${orientation}:${snap(fixed, tol)}`;
      if (!groups.has(key)) groups.set(key, { orientation, fixedValues: [], edges: [] });
      const g = groups.get(key);
      g.fixedValues.push(fixed);
      g.edges.push([s, e, rid]);
    }
  }

  const segments = [];
  for (const { orientation, fixedValues, edges } of groups.values()) {
    const fixed = fixedValues.reduce((a, b) => a + b, 0) / fixedValues.length;
    for (const [p0, p1, wallType, roomIds] of sweepGroup(edges)) {
      const geometry = orientation === 'h' ? [[p0, fixed], [p1, fixed]] : [[fixed, p0], [fixed, p1]];
      segments.push({
        id: `wallseg_${orientation}${fixed}_${p0}_${segments.length}`,
        wallType,
        geometry,
        lengthPx: Math.round((p1 - p0) * 100) / 100,
        roomIds,
      });
    }
  }
  return segments;
}
