// The single annotation store. Milestone 0 was load/serialize only.
// assignCondition() is the first real mutation — it only tags meta.conditionId,
// never touches geometry/measuredValue, so it doesn't reach into the
// select/move/resize/delete territory still gated behind Milestone 1.

import { useCallback, useState } from 'react';
import { annotationsFromDetection } from './fromDetection';
import { computeMeasuredValue } from './geometry';
import { deserializeAnnotations, serializeAnnotations } from './serialize';

export function useAnnotationStore() {
  const [annotations, setAnnotations] = useState([]);

  const loadFromDetection = useCallback((detection) => {
    setAnnotations(annotationsFromDetection(detection));
  }, []);

  const loadFromJSON = useCallback((json) => {
    setAnnotations(deserializeAnnotations(json));
  }, []);

  const toJSON = useCallback(() => serializeAnnotations(annotations), [annotations]);

  // Box-select -> right-click -> assign to condition. `ids` are Annotation.id
  // values (AI or manual, doesn't matter — same store, same object).
  const assignCondition = useCallback((ids, conditionId) => {
    const idSet = new Set(ids);
    setAnnotations((prev) => prev.map((a) => (
      idSet.has(a.id) ? { ...a, meta: { ...a.meta, conditionId } } : a
    )));
  }, []);

  // Accept/reject/relabel from DetectionHoverCard — same rule as
  // assignCondition: meta only, geometry/measuredValue untouched.
  const updateAnnotationMeta = useCallback((id, patch) => {
    setAnnotations((prev) => prev.map((a) => (
      a.id === id ? { ...a, meta: { ...a.meta, ...patch } } : a
    )));
  }, []);

  // AI Search results -> count/area annotation (the same "source: 'manual',
  // since the user triggered it" rule the original overlay spec gives for
  // Smart-fill — a search match only becomes a real shape once a person
  // picks it, but it's the identical Annotation object from then on).
  const addAnnotation = useCallback((partial) => {
    const annotation = { style: {}, meta: {}, ...partial };
    annotation.measuredValue = computeMeasuredValue(annotation);
    setAnnotations((prev) => [...prev, annotation]);
    return annotation;
  }, []);

  return { annotations, loadFromDetection, loadFromJSON, toJSON, assignCondition, updateAnnotationMeta, addAnnotation };
}
