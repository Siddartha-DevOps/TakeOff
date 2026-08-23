// Unified annotation document with bounded undo/redo history. Every geometry
// mutation recomputes its measured value before the autosave layer persists it.

import { useCallback, useMemo, useState } from 'react';
import { annotationsFromDetection } from './fromDetection';
import { computeMeasuredValue } from './geometry';
import { deserializeAnnotations, serializeAnnotations } from './serialize';

export function useAnnotationStore() {
  const [history, setHistory] = useState({ past: [], present: [], future: [] });
  const annotations = history.present;

  const replaceDocument = useCallback((next) => {
    setHistory({ past: [], present: next, future: [] });
  }, []);

  const commit = useCallback((mutator) => {
    setHistory((current) => {
      const next = mutator(current.present);
      if (next === current.present) return current;
      return {
        past: [...current.past, current.present].slice(-100),
        present: next,
        future: [],
      };
    });
  }, []);

  const loadFromDetection = useCallback((detection, measurementContext = null) => {
    replaceDocument(annotationsFromDetection(detection, measurementContext));
  }, [replaceDocument]);

  const loadFromJSON = useCallback((json, measurementContext = null) => {
    replaceDocument(deserializeAnnotations(json, measurementContext));
  }, [replaceDocument]);

  const toJSON = useCallback(() => serializeAnnotations(annotations), [annotations]);

  // Box-select -> right-click -> assign to condition. `ids` are Annotation.id
  // values (AI or manual, doesn't matter — same store, same object).
  const assignCondition = useCallback((ids, conditionId) => {
    const idSet = new Set(ids);
    commit((prev) => prev.map((a) => (
      idSet.has(a.id) ? { ...a, meta: { ...a.meta, conditionId } } : a
    )));
  }, [commit]);

  // Accept/reject/relabel from DetectionHoverCard — same rule as
  // assignCondition: meta only, geometry/measuredValue untouched.
  const updateAnnotationMeta = useCallback((id, patch) => {
    commit((prev) => prev.map((a) => (
      a.id === id ? { ...a, meta: { ...a.meta, ...patch } } : a
    )));
  }, [commit]);

  // AI Search results -> count/area annotation (the same "source: 'manual',
  // since the user triggered it" rule the original overlay spec gives for
  // Smart-fill — a search match only becomes a real shape once a person
  // picks it, but it's the identical Annotation object from then on).
  const addAnnotation = useCallback((partial, measurementContext = null) => {
    const annotation = { style: {}, meta: {}, ...partial };
    annotation.measuredValue = computeMeasuredValue(annotation, measurementContext);
    commit((prev) => [...prev, annotation]);
    return annotation;
  }, [commit]);

  const updateGeometry = useCallback((id, geometry, measurementContext = null) => {
    commit((prev) => {
      const index = prev.findIndex((annotation) => annotation.id === id);
      if (index < 0) return prev;
      const current = prev[index];
      const unchanged = current.geometry.length === geometry.length
        && current.geometry.every((point, pointIndex) => (
          point[0] === geometry[pointIndex][0] && point[1] === geometry[pointIndex][1]
        ));
      if (unchanged) return prev;
      const updated = { ...current, geometry: geometry.map((point) => [...point]) };
      const next = [...prev];
      next[index] = { ...updated, measuredValue: computeMeasuredValue(updated, measurementContext) };
      return next;
    });
  }, [commit]);

  const deleteAnnotation = useCallback((id) => {
    commit((prev) => prev.filter((annotation) => annotation.id !== id));
  }, [commit]);

  const undo = useCallback(() => {
    setHistory((current) => {
      if (current.past.length === 0) return current;
      return {
        past: current.past.slice(0, -1),
        present: current.past[current.past.length - 1],
        future: [current.present, ...current.future].slice(0, 100),
      };
    });
  }, []);

  const redo = useCallback(() => {
    setHistory((current) => {
      if (current.future.length === 0) return current;
      return {
        past: [...current.past, current.present].slice(-100),
        present: current.future[0],
        future: current.future.slice(1),
      };
    });
  }, []);

  const historyState = useMemo(() => ({
    canUndo: history.past.length > 0,
    canRedo: history.future.length > 0,
  }), [history.past.length, history.future.length]);

  return {
    annotations,
    loadFromDetection,
    loadFromJSON,
    toJSON,
    assignCondition,
    updateAnnotationMeta,
    addAnnotation,
    updateGeometry,
    deleteAnnotation,
    undo,
    redo,
    ...historyState,
  };
}
