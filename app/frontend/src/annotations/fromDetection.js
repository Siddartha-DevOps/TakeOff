// Adapter: AI detection JSON (mock/mockAI.js shape, matches backend
// ai/detection_engine.py output) -> unified Annotation[].
//
// This is the one and only place AI output is translated into the store.
// After this runs, an AI-produced shape and a hand-drawn shape are the same
// Annotation object — there is no separate "AI layer".

import { getRoomColor } from '../mock/mockAI';
import { computeMeasuredValue, rectFromBbox } from './geometry';

function finalize(annotation) {
  annotation.measuredValue = computeMeasuredValue(annotation);
  return annotation;
}

function roomToAnnotation(room, detectionMeta) {
  return finalize({
    id: room.id,
    type: 'area',
    geometry: rectFromBbox(room.bbox),
    style: { stroke: getRoomColor(room.label), fill: getRoomColor(room.label), fillOpacity: 0.22 },
    layerId: 'rooms',
    source: 'ai',
    meta: {
      label: room.label,
      confidence: room.confidence,
      aiReportedArea: room.area, // kept for audit only — never used as measuredValue
      ...detectionMeta,
    },
  });
}

function wallSegmentToAnnotation(seg, detectionMeta) {
  return finalize({
    id: seg.id,
    type: 'line',
    geometry: seg.geometry,
    style: { stroke: seg.wallType === 'exterior' ? '#eab308' : '#ca8a04', strokeWidth: seg.wallType === 'exterior' ? 4 : 2 },
    layerId: 'walls',
    source: 'ai',
    meta: {
      label: seg.wallType === 'exterior' ? 'Exterior wall' : 'Interior wall',
      wallType: seg.wallType,
      roomIds: seg.roomIds,
      confidence: seg.confidence,
      ...detectionMeta,
    },
  });
}

const DEFAULT_SYMBOL_LABEL = { doors: 'Door', windows: 'Window', mep: 'Fixture' };

// Doors / windows / MEP symbols all carry a bbox in the real detection engine
// (mock data derives one from x/y/width when it's missing). Modeled as
// `count` shapes: a placed symbol with a footprint, worth 1 unit each.
function symbolToAnnotation(item, layerId, detectionMeta) {
  const bbox = item.bbox ?? [
    item.x - (item.width ?? 20) / 2,
    item.y - 10,
    item.x + (item.width ?? 20) / 2,
    item.y + 10,
  ];
  return finalize({
    id: item.id,
    type: 'count',
    geometry: rectFromBbox(bbox),
    style: {},
    layerId,
    source: 'ai',
    meta: {
      // label mirrors room.label — a uniform relabel target across all AI shapes.
      label: item.type ?? DEFAULT_SYMBOL_LABEL[layerId] ?? 'Element',
      symbolType: item.type ?? layerId,
      confidence: item.confidence,
      rotation: item.rotation ?? 0,
      widthInches: item.width,
      ...detectionMeta,
    },
  });
}

/**
 * @param {object} detection - result of runTakeoffAI() / GET /takeoff/drawings/:id/results
 * @returns {import('./types').Annotation[]}
 */
export function annotationsFromDetection(detection) {
  if (!detection) return [];

  const detectionMeta = {
    detectionId: detection.id,
    aiModelVersion: detection.ai_model_version ?? detection.aiModelVersion ?? 'unknown',
  };

  const rooms = (detection.rooms ?? []).map((r) => roomToAnnotation(r, detectionMeta));
  const doors = (detection.doors ?? []).map((d) => symbolToAnnotation(d, 'doors', detectionMeta));
  const windows = (detection.windows ?? []).map((w) => symbolToAnnotation(w, 'windows', detectionMeta));
  const mep = (detection.mep ?? []).map((m) => symbolToAnnotation(m, 'mep', detectionMeta));
  // wall_segments: true vectorized centerlines (wallVectorization.js / backend's
  // ai/wall_vectorization.py), typed exterior/interior — see CanvasFull for the
  // matching data-driven render, which replaced the old hardcoded SVG lines.
  const walls = (detection.wall_segments ?? []).map((w) => wallSegmentToAnnotation(w, detectionMeta));

  return [...rooms, ...doors, ...windows, ...mep, ...walls];
}
