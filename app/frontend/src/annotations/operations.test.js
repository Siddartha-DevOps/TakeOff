import assert from 'node:assert/strict';
import test from 'node:test';

import { computeMeasuredValue } from './geometry.js';
import { addAreaHole, duplicateAnnotations, mergeAreaAnnotations, splitAreaAnnotation, transformAnnotation } from './operations.js';

const area = (id, geometry) => ({ id, type: 'area', geometry, holes: [], source: 'manual', meta: {}, style: {} });

test('area measurements subtract polygon holes', () => {
  const annotation = area('room', [[0, 0], [10, 0], [10, 10], [0, 10]]);
  annotation.holes = [[[2, 2], [4, 2], [4, 4], [2, 4]]];
  assert.equal(computeMeasuredValue(annotation), 96);
});

test('three point arc measures a semicircle', () => {
  const value = computeMeasuredValue({ type: 'line', geometry: [[-1, 0], [0, 1], [1, 0]], meta: { curve: 'arc' } });
  assert.ok(Math.abs(value - Math.PI) < 0.01);
});

test('split creates two measurable polygons without keeping the source id', () => {
  const source = area('room', [[0, 0], [10, 0], [10, 10], [0, 10]]);
  const result = splitAreaAnnotation(source, 0, 2, (index) => `part-${index}`);
  assert.equal(result.length, 2);
  assert.deepEqual(result.map((item) => item.measuredValue), [50, 50]);
});

test('split preserves contained holes and refuses to cut through one', () => {
  const source = area('room', [[0, 0], [10, 0], [10, 10], [0, 10]]);
  source.holes = [[[1, 7], [2, 7], [2, 8], [1, 8]]];
  const preserved = splitAreaAnnotation(source, 0, 2, (index) => `part-${index}`);
  assert.equal(preserved.reduce((count, item) => count + item.holes.length, 0), 1);
  source.holes = [[[4, 4], [6, 4], [6, 6], [4, 6]]];
  assert.deepEqual(splitAreaAnnotation(source, 0, 2, (index) => `part-${index}`), []);
});

test('merge replaces touching areas with their exact union', () => {
  const input = [area('a', [[0, 0], [2, 0], [2, 2], [0, 2]]), area('b', [[2, 0], [4, 0], [4, 2], [2, 2]])];
  const result = mergeAreaAnnotations(input, ['a', 'b']);
  assert.equal(result.annotations.length, 1);
  assert.equal(result.merged.measuredValue, 8);
});

test('merge preserves a concave union and refuses disconnected polygons', () => {
  const elbow = area('a', [[0, 0], [4, 0], [4, 1], [1, 1], [1, 4], [0, 4]]);
  const square = area('b', [[1, 1], [2, 1], [2, 2], [1, 2]]);
  const merged = mergeAreaAnnotations([elbow, square], ['a', 'b']);
  assert.equal(merged.merged.measuredValue, 8);
  const remote = area('c', [[10, 10], [11, 10], [11, 11], [10, 11]]);
  const rejected = mergeAreaAnnotations([elbow, remote], ['a', 'c']);
  assert.equal(rejected.merged, null);
  assert.equal(rejected.annotations.length, 2);
});

test('holes must be contained by their area', () => {
  const source = area('room', [[0, 0], [10, 0], [10, 10], [0, 10]]);
  assert.equal(addAreaHole(source, [[20, 20], [21, 20], [21, 21], [20, 21]]), null);
  const cut = addAreaHole(source, [[2, 2], [4, 2], [4, 4], [2, 4]]);
  assert.equal(cut.measuredValue, 96);
});

test('duplicate and transform preserve source while creating independent geometry', () => {
  const source = area('a', [[0, 0], [2, 0], [2, 2], [0, 2]]);
  const transformed = transformAnnotation(source, { dx: 5, rotation: 90, scale: 2 });
  assert.equal(transformed.measuredValue, 16);
  assert.notDeepEqual(transformed.geometry, source.geometry);
  const result = duplicateAnnotations([source], ['a'], { idFactory: () => 'copy' });
  assert.equal(result.copies[0].id, 'copy');
  assert.deepEqual(source.geometry[0], [0, 0]);
});
