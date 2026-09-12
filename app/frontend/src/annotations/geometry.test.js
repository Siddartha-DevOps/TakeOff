import test from 'node:test';
import assert from 'node:assert/strict';

import { computeMeasuredValue, planUnitsToFeet, snapPoint } from './geometry.js';
import { deserializeAnnotations } from './serialize.js';

test('snaps to a nearby existing vertex before applying angle snapping', () => {
  assert.deepEqual(snapPoint([9.5, 10.5], {
    anchor: [0, 0], vertices: [[10, 10]], tolerance: 2,
  }), [10, 10]);
});

test('snaps a segment to 45 degree increments', () => {
  const result = snapPoint([10, 8], { anchor: [0, 0], angleStep: 45 });
  assert.ok(Math.abs(result[0] - result[1]) < 1e-9);
});

test('converts PDF plan points to linear feet at architectural scale', () => {
  assert.equal(planUnitsToFeet(72, 96, 'PDF'), 8);
  assert.equal(computeMeasuredValue({
    type: 'line',
    geometry: [[0, 0], [72, 0]],
  }, { scaleRatio: 96, fileType: 'PDF' }), 8);
});

test('converts PDF polygon area to square feet', () => {
  assert.equal(computeMeasuredValue({
    type: 'area',
    geometry: [[0, 0], [72, 0], [72, 72], [0, 72]],
  }, { scaleRatio: 96, fileType: 'PDF' }), 64);
});

test('uses the 300 DPI reference coordinate system for raster drawings', () => {
  assert.equal(computeMeasuredValue({
    type: 'line',
    geometry: [[0, 0], [300, 0]],
  }, { scaleRatio: 48, fileType: 'PNG', planDpi: 300 }), 4);
});

test('does not assume a raster DPI when metadata/calibration did not provide one', () => {
  assert.equal(computeMeasuredValue({
    type: 'line', geometry: [[0, 0], [300, 0]],
  }, { scaleRatio: 48, fileType: 'PNG' }), 0);
});

test('count annotations always measure one item', () => {
  assert.equal(computeMeasuredValue({ type: 'count', geometry: [[25, 40]] }, {
    scaleRatio: 96,
    fileType: 'PDF',
  }), 1);
});

test('persisted annotations recompute measurements with the drawing scale', () => {
  const [annotation] = deserializeAnnotations([{
    id: 'manual-line-1', type: 'line', geometry: [[0, 0], [72, 0]], measuredValue: 999,
  }], { scaleRatio: 96, fileType: 'PDF' });
  assert.equal(annotation.measuredValue, 8);
});
