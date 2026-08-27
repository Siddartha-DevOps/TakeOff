import polygonClipping from 'polygon-clipping';
import { computeMeasuredValue, ringInsidePolygon } from './geometry.js';

const clonePoints = (points = []) => points.map(([x, y]) => [x, y]);
const cloneHoles = (holes = []) => holes.map(clonePoints);

export function centroidOf(annotation) {
  const points = annotation.geometry || [];
  if (!points.length) return [0, 0];
  return points.reduce(([sx, sy], [x, y]) => [sx + x / points.length, sy + y / points.length], [0, 0]);
}

export function transformAnnotation(annotation, { dx = 0, dy = 0, scale = 1, rotation = 0 } = {}, measurementContext = null) {
  const [cx, cy] = centroidOf(annotation);
  const radians = rotation * Math.PI / 180;
  const transformPoint = ([x, y]) => {
    const localX = (x - cx) * scale;
    const localY = (y - cy) * scale;
    return [
      cx + localX * Math.cos(radians) - localY * Math.sin(radians) + dx,
      cy + localX * Math.sin(radians) + localY * Math.cos(radians) + dy,
    ];
  };
  const updated = {
    ...annotation,
    geometry: clonePoints(annotation.geometry).map(transformPoint),
    holes: cloneHoles(annotation.holes).map((ring) => ring.map(transformPoint)),
  };
  return { ...updated, measuredValue: computeMeasuredValue(updated, measurementContext) };
}

export function duplicateAnnotations(annotations, ids, { offset = [12, 12], idFactory } = {}, measurementContext = null) {
  const selected = new Set(ids);
  const copies = annotations.filter((item) => selected.has(item.id)).map((item, index) => {
    const copy = transformAnnotation(item, { dx: offset[0], dy: offset[1] }, measurementContext);
    return {
      ...copy,
      id: idFactory ? idFactory(item, index) : `${item.id}_copy_${Date.now()}_${index}`,
      source: 'manual',
      meta: { ...copy.meta, duplicatedFrom: item.id },
    };
  });
  return { annotations: [...annotations, ...copies], copies };
}

export function mergeAreaAnnotations(annotations, ids, measurementContext = null) {
  const selected = new Set(ids);
  const areas = annotations.filter((item) => selected.has(item.id) && item.type === 'area');
  if (areas.length < 2) return { annotations, merged: null };
  const polygons = areas.map((item) => [clonePoints(item.geometry), ...cloneHoles(item.holes)]);
  let union;
  try {
    union = polygonClipping.union(...polygons);
  } catch {
    return { annotations, merged: null };
  }
  // One annotation cannot represent disconnected polygons. Keep the source
  // selection unchanged rather than silently filling the gap between shapes.
  if (union.length !== 1 || !union[0]?.[0]?.length) return { annotations, merged: null };
  const [geometry, ...holes] = union[0].map((ring) => ring.slice(0, -1));
  const base = { ...areas[0], geometry, holes, meta: { ...areas[0].meta, mergedFrom: areas.map((item) => item.id) } };
  const merged = { ...base, measuredValue: computeMeasuredValue(base, measurementContext) };
  return {
    annotations: [...annotations.filter((item) => !selected.has(item.id)), merged],
    merged,
  };
}

export function splitAreaAnnotation(annotation, firstIndex, secondIndex, idFactory, measurementContext = null) {
  if (annotation.type !== 'area') return [];
  const points = annotation.geometry;
  const low = Math.min(firstIndex, secondIndex);
  const high = Math.max(firstIndex, secondIndex);
  if (low < 0 || high >= points.length || high - low < 2 || (low === 0 && high === points.length - 1)) return [];
  const rings = [points.slice(low, high + 1), [...points.slice(high), ...points.slice(0, low + 1)]];
  const assignedHoles = rings.map(() => []);
  for (const hole of cloneHoles(annotation.holes)) {
    const targetIndex = rings.findIndex((geometry) => ringInsidePolygon(hole, geometry));
    // Splitting through an existing opening would corrupt its geometry. Ask
    // the user to choose a different split line instead of losing the hole.
    if (targetIndex < 0) return [];
    assignedHoles[targetIndex].push(hole);
  }
  return rings.map((geometry, index) => {
    const item = {
      ...annotation,
      id: idFactory(index),
      geometry: clonePoints(geometry),
      holes: assignedHoles[index],
      meta: { ...annotation.meta, splitFrom: annotation.id },
    };
    return { ...item, measuredValue: computeMeasuredValue(item, measurementContext) };
  });
}

export function addAreaHole(annotation, ring, measurementContext = null) {
  if (annotation.type !== 'area' || !ringInsidePolygon(ring, annotation.geometry)) return null;
  const updated = { ...annotation, holes: [...cloneHoles(annotation.holes), clonePoints(ring)] };
  return { ...updated, measuredValue: computeMeasuredValue(updated, measurementContext) };
}
