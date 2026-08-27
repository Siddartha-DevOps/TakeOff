// Unified annotation document with bounded undo/redo history. Every geometry
// mutation recomputes its measured value before the autosave layer persists it.

import { useCallback, useMemo, useState } from 'react';
import { annotationsFromDetection } from './fromDetection';
import { computeMeasuredValue } from './geometry';
import { deserializeAnnotations, serializeAnnotations } from './serialize';
import { addAreaHole, duplicateAnnotations, mergeAreaAnnotations, splitAreaAnnotation, transformAnnotation } from './operations';

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

  const deleteAnnotations = useCallback((ids) => {
    const idSet = new Set(ids);
    commit((prev) => prev.filter((annotation) => !idSet.has(annotation.id)));
  }, [commit]);

  const updateAnnotationsMeta = useCallback((ids, patch) => {
    const idSet = new Set(ids);
    commit((prev) => prev.map((annotation) => idSet.has(annotation.id)
      ? { ...annotation, meta: { ...annotation.meta, ...patch } }
      : annotation));
  }, [commit]);

  const transformAnnotations = useCallback((ids, transform, measurementContext = null) => {
    const idSet = new Set(ids);
    commit((prev) => prev.map((annotation) => idSet.has(annotation.id)
      ? transformAnnotation(annotation, transform, measurementContext)
      : annotation));
  }, [commit]);

  const duplicate = useCallback((ids, measurementContext = null) => {
    let created = [];
    commit((prev) => {
      const result = duplicateAnnotations(prev, ids, {}, measurementContext);
      created = result.copies;
      return result.annotations;
    });
    return created;
  }, [commit]);

  const pasteAnnotations = useCallback((clipboard, measurementContext = null) => {
    commit((prev) => {
      const copies = clipboard.map((item, index) => {
        const copy = transformAnnotation(item, { dx: 12, dy: 12 }, measurementContext);
        return {
          ...copy,
          id: `${item.id}_paste_${Date.now()}_${index}`,
          source: 'manual',
          meta: { ...copy.meta, duplicatedFrom: item.id },
        };
      });
      return copies.length ? [...prev, ...copies] : prev;
    });
  }, [commit]);

  const mergeAreas = useCallback((ids, measurementContext = null) => {
    let merged = null;
    commit((prev) => {
      const result = mergeAreaAnnotations(prev, ids, measurementContext);
      merged = result.merged;
      return result.annotations;
    });
    return merged;
  }, [commit]);

  const splitArea = useCallback((id, firstIndex, secondIndex, measurementContext = null) => {
    let created = [];
    commit((prev) => {
      const annotation = prev.find((item) => item.id === id);
      if (!annotation) return prev;
      created = splitAreaAnnotation(
        annotation,
        firstIndex,
        secondIndex,
        (index) => `${id}_split_${Date.now()}_${index}`,
        measurementContext,
      );
      if (created.length !== 2) return prev;
      return [...prev.filter((item) => item.id !== id), ...created];
    });
    return created;
  }, [commit]);

  const addHole = useCallback((id, ring, measurementContext = null) => {
    commit((prev) => prev.map((annotation) => {
      if (annotation.id !== id) return annotation;
      return addAreaHole(annotation, ring, measurementContext) || annotation;
    }));
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
    deleteAnnotations,
    updateAnnotationsMeta,
    transformAnnotations,
    duplicate,
    pasteAnnotations,
    mergeAreas,
    splitArea,
    addHole,
    undo,
    redo,
    ...historyState,
  };
}
