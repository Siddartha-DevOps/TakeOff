// The single annotation store. Milestone 0: load/serialize only, no mutation
// API yet — that lands in Milestone 1 (select/move/delete) and beyond.

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

  return { annotations, loadFromDetection, loadFromJSON, toJSON };
}
