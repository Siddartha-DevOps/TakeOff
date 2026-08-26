import test from 'node:test';
import assert from 'node:assert/strict';

import { buildDashboardStats, presentActivity, relativeTime } from './dashboardData.js';

test('buildDashboardStats uses project and billing API values', () => {
  const stats = buildDashboardStats(
    [
      { status: 'active', sheets_count: 2 },
      { status: 'review', sheets_count: 3 },
      { status: 'active', sheets_count: null },
    ],
    { projects: { used: 2 }, ai_takeoffs: { used: 7 } },
  );

  assert.deepEqual(stats, {
    activeProjects: 2,
    totalProjects: 3,
    drawings: 5,
    projectsThisMonth: 2,
    aiTakeoffsThisMonth: 7,
  });
});

test('relativeTime formats recent activity without fabricated timestamps', () => {
  const now = Date.parse('2026-08-26T12:00:00Z');
  assert.equal(relativeTime('2026-08-26T11:55:00Z', now), '5m ago');
  assert.equal(relativeTime('invalid', now), 'Recently');
});

test('presentActivity maps known and unknown audit actions', () => {
  const now = Date.parse('2026-08-26T12:00:00Z');
  assert.equal(presentActivity({ action: 'login', created_at: '2026-08-26T11:00:00Z' }, now).text, 'Signed in');
  assert.equal(presentActivity({ action: 'drawing.uploaded', created_at: '2026-08-25T12:00:00Z' }, now).text, 'Drawing uploaded');
});
