// The single annotation store. Milestone 0 was load/serialize only.
// assignCondition() is the first real mutation — it only tags meta.conditionId,
// never touches geometry/measuredValue, so it doesn't reach into the
// select/move/resize/delete territory still gated behind Milestone 1.

import { useCallback, useState } from 'react';
import { annotationsFromDetection } from './fromDetection';
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

  return { annotations, loadFromDetection, loadFromJSON, toJSON, assignCondition };
}
