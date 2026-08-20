import test from 'node:test';
import assert from 'node:assert/strict';

import { computeMeasuredValue, planUnitsToFeet } from './geometry.js';

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
  }, { scaleRatio: 48, fileType: 'PNG' }), 4);
});

test('count annotations always measure one item', () => {
  assert.equal(computeMeasuredValue({ type: 'count', geometry: [[25, 40]] }, {
    scaleRatio: 96,
    fileType: 'PDF',
  }), 1);
});
