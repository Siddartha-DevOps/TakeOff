// The single annotation store. Milestone 0 was load/serialize only.
// assignCondition() was the first real mutation — meta.conditionId only,
// geometry/measuredValue untouched.
//
// mergeSelection/backoutSelection/splitSelection (Togal parity: "Advanced
// tools — split/merge/cut/backout") are geometry mutations, but a
// deliberately narrow kind: each one replaces whole shapes with new,
// computed ones (real polygon union/difference/intersection — see
// shapeOps.js) triggered by a single menu action. That's different from,
// and doesn't require, the freeform interactive editing (drag a vertex,
// resize a handle live on the canvas) "Milestone 1" of the Editable
// Annotation Overlay spec means — that territory (select/move/resize/
// delete via a Konva-style live-editable canvas) is still unbuilt.

import { useCallback, useState } from 'react';
import { annotationsFromDetection } from './fromDetection';
import { computeMeasuredValue } from './geometry';
import { deserializeAnnotations, serializeAnnotations } from './serialize';
import { mergeAreaGeometry, backoutAreaGeometry, splitAreaGeometry, mergeLineGeometry } from './shapeOps';

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

  // Merge (union): 2+ shapes of the same type -> one. Validation and the
  // actual geometry math happen against the *current* `annotations` closure
  // before calling setAnnotations, so a rejected op (shapes don't touch,
  // would produce a hole, etc.) throws synchronously to the caller and
  // leaves state completely untouched — never a partial/inconsistent update.
  const mergeSelection = useCallback((ids) => {
    const targets = annotations.filter((a) => ids.includes(a.id));
    if (targets.length < 2) throw new Error('Select at least 2 shapes to merge');
    const type = targets[0].type;
    if (!targets.every((a) => a.type === type)) throw new Error('Can only merge shapes of the same type (all area, or all line)');
    if (type === 'count') throw new Error('Count shapes have no shape to merge');

    const geometry = type === 'area'
      ? mergeAreaGeometry(targets.map((a) => a.geometry))
      : mergeLineGeometry(targets.map((a) => a.geometry));

    const merged = {
      ...targets[0],
      id: `merged-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      geometry,
      source: 'manual',
      meta: { ...targets[0].meta, mergedFrom: targets.map((a) => a.id) },
    };
    merged.measuredValue = computeMeasuredValue(merged);

    const idSet = new Set(ids);
    setAnnotations((prev) => [...prev.filter((a) => !idSet.has(a.id)), merged]);
    return merged;
  }, [annotations]);

  // Backout (deduct): exactly 2 area shapes. The larger-area one is always
  // the base and the smaller the deduction — real takeoff deductions are
  // always "cut the small thing out of the big thing," so this avoids
  // needing the box-select interaction to convey an explicit base/deduct
  // order it doesn't naturally carry.
  const backoutSelection = useCallback((ids) => {
    const targets = annotations.filter((a) => ids.includes(a.id));
    if (targets.length !== 2) throw new Error('Select exactly 2 area shapes — the larger becomes the base, the smaller is deducted from it');
    if (!targets.every((a) => a.type === 'area')) throw new Error('Backout only applies to area shapes');
    const [base, deduct] = targets[0].measuredValue >= targets[1].measuredValue ? targets : [targets[1], targets[0]];

    const geometry = backoutAreaGeometry(base.geometry, deduct.geometry);
    const result = { ...base, geometry, source: 'manual', meta: { ...base.meta, backedOutFrom: deduct.id } };
    result.measuredValue = computeMeasuredValue(result);

    const idSet = new Set(ids);
    setAnnotations((prev) => [...prev.filter((a) => !idSet.has(a.id)), result]);
    return result;
  }, [annotations]);

  // Split: exactly one area shape + one line shape (the line is the cut
  // line, auto-extended across the area's bounds — see shapeOps.js). The
  // line annotation is consumed (removed) along with the original area
  // shape, replaced by the two resulting pieces.
  const splitSelection = useCallback((ids) => {
    const targets = annotations.filter((a) => ids.includes(a.id));
    if (targets.length !== 2) throw new Error('Select exactly 1 area shape and 1 line shape to use as the cut line');
    const area = targets.find((a) => a.type === 'area');
    const line = targets.find((a) => a.type === 'line');
    if (!area || !line) throw new Error('Select exactly 1 area shape and 1 line shape to use as the cut line');

    const [geoA, geoB] = splitAreaGeometry(area.geometry, line.geometry);
    const makePiece = (geometry, suffix) => {
      const piece = {
        ...area,
        id: `split-${Date.now()}-${suffix}-${Math.random().toString(36).slice(2, 6)}`,
        geometry,
        source: 'manual',
        meta: { ...area.meta, splitFrom: area.id },
      };
      piece.measuredValue = computeMeasuredValue(piece);
      return piece;
    };
    const pieceA = makePiece(geoA, 'a');
    const pieceB = makePiece(geoB, 'b');

    const idSet = new Set(ids); // removes both the original area AND the cut line
    setAnnotations((prev) => [...prev.filter((a) => !idSet.has(a.id)), pieceA, pieceB]);
    return [pieceA, pieceB];
  }, [annotations]);

  return {
    annotations, loadFromDetection, loadFromJSON, toJSON, assignCondition, updateAnnotationMeta, addAnnotation,
    mergeSelection, backoutSelection, splitSelection,
  };
}
