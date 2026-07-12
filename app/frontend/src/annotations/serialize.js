// Lossless JSON round-trip for the annotation set, per the spec's serialization rule.
// On ingest, measuredValue is always recomputed rather than trusted from the payload —
// this guards deserialize the same way fromDetection.js guards AI ingest.

import { computeMeasuredValue } from './geometry';

/** @param {import('./types').Annotation[]} annotations */
export function serializeAnnotations(annotations) {
  return JSON.stringify(annotations);
}

/**
 * @param {string | object[]} json
 * @returns {import('./types').Annotation[]}
 */
export function deserializeAnnotations(json) {
  const parsed = typeof json === 'string' ? JSON.parse(json) : json;
  if (!Array.isArray(parsed)) return [];
  return parsed.map((a) => ({ ...a, measuredValue: computeMeasuredValue(a) }));
}
