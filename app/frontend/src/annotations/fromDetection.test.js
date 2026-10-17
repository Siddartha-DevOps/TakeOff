import test from 'node:test';
import assert from 'node:assert/strict';

import { annotationsFromDetection } from './fromDetection.js';

test('Mask R-CNN room polygons and holes become editable area annotations', () => {
  const detection = {
    ai_model_version: 'maskrcnn-fixture',
    rooms: [{
      id: 'room-1', label: 'living', confidence: 0.9,
      bbox: [0, 0, 20, 20],
      polygon: [[1, 1], [19, 1], [19, 19], [1, 19]],
      holes: [[[8, 8], [12, 8], [12, 12], [8, 12]]],
      area: 308,
    }],
  };
  const [annotation] = annotationsFromDetection(detection);
  assert.deepEqual(annotation.geometry, detection.rooms[0].polygon);
  assert.deepEqual(annotation.holes, detection.rooms[0].holes);
  assert.equal(annotation.measuredValue, 308);
  assert.equal(annotation.meta.aiModelVersion, 'maskrcnn-fixture');
});

test('legacy room detections still fall back to their bounding box', () => {
  const [annotation] = annotationsFromDetection({
    rooms: [{ id: 'legacy', label: 'bedroom', bbox: [1, 2, 3, 4], area: 4 }],
  });
  assert.deepEqual(annotation.geometry, [[1, 2], [3, 2], [3, 4], [1, 4]]);
});
