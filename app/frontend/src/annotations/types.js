// Unified annotation model — see Editable Annotation Overlay spec, Milestone 0.
// Plain JSDoc typedefs: this app is JS/JSX (no TypeScript in the toolchain today).

/**
 * @typedef {'ai' | 'manual'} Source
 * @typedef {'count' | 'line' | 'area'} AnnotationType
 *
 * @typedef {Object} AnnotationStyle
 * @property {string} [stroke]
 * @property {string} [fill]
 * @property {number} [strokeWidth]
 * @property {number} [fillOpacity]
 *
 * @typedef {Object} Annotation
 * @property {string} id
 * @property {AnnotationType} type
 * @property {number[][]} geometry     Coords in PLAN space (source raster pixels), not screen pixels.
 * @property {AnnotationStyle} style
 * @property {string} layerId          e.g. 'rooms' | 'doors' | 'windows' | 'mep' | 'walls'
 * @property {number} measuredValue    Always recomputed from geometry — never trusted from source.
 * @property {Source} source
 * @property {Record<string, unknown>} meta  e.g. { confidence, aiModelVersion } for AI shapes.
 */

export {};
