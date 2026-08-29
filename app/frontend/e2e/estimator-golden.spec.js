import { test, expect } from '@playwright/test';
import { vectorFloorPlanPdf } from './fixtures/vectorFloorPlan.js';
import { API_URL, clickPlan, loginInBrowser, signup, uniqueIdentity, waitForAutosave } from './helpers.js';

async function downloadBytes(download) {
  const stream = await download.createReadStream();
  if (!stream) throw new Error('Browser download did not expose a readable stream');
  const chunks = [];
  for await (const chunk of stream) chunks.push(Buffer.from(chunk));
  return Buffer.concat(chunks);
}

test.describe('TakeOff estimator golden workflow', () => {
  let cleanupProjects = [];

  test.beforeEach(() => {
    cleanupProjects = [];
  });

  test.afterEach(async ({ request }) => {
    for (const project of cleanupProjects.reverse()) {
      await request.delete(`${API_URL}/api/projects/${project.id}`, {
        headers: { Authorization: `Bearer ${project.token}` },
      });
    }
  });

  test('login, project, upload, scale, takeoff, correction, persistence and exports', async ({ page, request }) => {
    const identity = uniqueIdentity('golden');
    const session = await signup(request, identity);
    await loginInBrowser(page, identity.email);

    await page.getByRole('button', { name: /new project/i }).click();
    await page.getByLabel('Project Name').fill('Golden Workflow Project');
    await page.getByLabel('Description').fill('Deterministic browser E2E fixture');
    await page.getByRole('button', { name: 'Create Project' }).click();
    await page.getByText('Golden Workflow Project', { exact: true }).click();
    await expect(page).toHaveURL(/\/app\/projects\/\d+$/);
    const projectId = Number(page.url().match(/projects\/(\d+)/)[1]);
    cleanupProjects.push({ id: projectId, token: session.access_token });

    await page.getByRole('button', { name: /upload blueprint/i }).click();
    await page.locator('input[type=file]').setInputFiles({
      name: 'golden-vector-floor-plan.pdf',
      mimeType: 'application/pdf',
      buffer: vectorFloorPlanPdf(),
    });
    const uploadResponse = page.waitForResponse((response) =>
      response.request().method() === 'POST'
        && /\/api\/uploads\/project\/\d+\/drawings$/.test(response.url()),
    );
    await page.getByRole('button', { name: /upload 1 file/i }).click();
    expect((await uploadResponse).ok()).toBeTruthy();
    await expect(page.getByTestId('plan-surface')).toBeVisible({ timeout: 30_000 });

    await page.getByRole('button', { name: /calibrate scale/i }).click();
    await clickPlan(page, [[0.25, 0.45], [0.65, 0.45]]);
    await page.getByPlaceholder('e.g. 3').fill('40');
    const initialSave = waitForAutosave(page);
    await page.getByRole('button', { name: 'Save scale' }).click();
    await expect(page.getByText(/AI complete/)).toBeVisible({ timeout: 45_000 });
    await expect(page.getByTestId('quantity-row').first()).toBeVisible();
    await initialSave;

    const rerunResponse = page.waitForResponse((response) =>
      response.request().method() === 'POST' && /\/api\/takeoff\/drawings\/\d+\/autodetect$/.test(response.url()),
    );
    await page.getByRole('button', { name: 'Re-run AI' }).click();
    expect((await rerunResponse).ok()).toBeTruthy();
    await expect(page.getByText(/AI complete/)).toBeVisible({ timeout: 45_000 });

    // Real manual area, line, and count operations.
    await page.getByTitle('Draw Area (sf)').click();
    const areaSave = waitForAutosave(page);
    await clickPlan(page, [[0.18, 0.28], [0.32, 0.28], [0.32, 0.42], [0.18, 0.42]]);
    await page.keyboard.press('Enter');
    const areaProjection = await areaSave;
    expect(areaProjection.quantities.some((row) => row.item === 'Manual area')).toBeTruthy();
    await expect(page.locator('[data-quantity-item="Manual area"]')).toBeVisible();

    await page.getByTitle('Draw Line (lf)').click();
    const lineSave = waitForAutosave(page);
    await clickPlan(page, [[0.42, 0.30], [0.58, 0.30], [0.68, 0.38]]);
    await page.keyboard.press('Enter');
    const lineProjection = await lineSave;
    expect(lineProjection.quantities.some((row) => row.item === 'Manual line linear footage')).toBeTruthy();

    await page.getByTitle('Draw Count (ea)').click();
    const countSave = waitForAutosave(page);
    await clickPlan(page, [[0.76, 0.35]]);
    const countProjection = await countSave;
    expect(countProjection.quantities.find((row) => row.item === 'Manual count')?.quantity).toBe(1);

    // Select the manual area and drag one vertex: the real server must return a changed area.
    await page.getByTitle('Select, move, or edit annotation vertices').click();
    const area = page.locator('[data-annotation-type="area"]').filter({ has: page.getByTestId('manual-annotation-shape') }).last();
    await area.getByTestId('manual-annotation-shape').click({ force: true });
    const handle = area.getByTestId('manual-annotation-handle').first();
    const handleBox = await handle.boundingBox();
    expect(handleBox).not.toBeNull();
    const editSave = waitForAutosave(page);
    await page.mouse.move(handleBox.x + handleBox.width / 2, handleBox.y + handleBox.height / 2);
    await page.mouse.down();
    await page.mouse.move(handleBox.x - 35, handleBox.y - 20, { steps: 5 });
    await page.mouse.up();
    const editedProjection = await editSave;
    const editedArea = editedProjection.quantities.find((row) => row.item === 'Manual area')?.quantity;
    expect(editedArea).toBeGreaterThan(0);
    expect(editedArea).not.toBe(areaProjection.quantities.find((row) => row.item === 'Manual area')?.quantity);
    await expect(page.locator('[data-quantity-item="Manual area"]')).toContainText(String(editedArea));

    // Delete then undo the count annotation; both transitions are persisted and reflected.
    const count = page.locator('[data-annotation-type="count"]').last();
    await count.getByTestId('manual-annotation-shape').click({ force: true });
    const deleteSave = waitForAutosave(page);
    await page.getByLabel('Delete selected annotation').click();
    const deletedProjection = await deleteSave;
    expect(deletedProjection.quantities.some((row) => row.item === 'Manual count')).toBeFalsy();
    const undoSave = waitForAutosave(page);
    await page.getByLabel('Undo').click();
    const restoredByUndo = await undoSave;
    expect(restoredByUndo.quantities.find((row) => row.item === 'Manual count')?.quantity).toBe(1);

    // Version restore must update the visible quantity panel as well as persisted data.
    await page.getByLabel('Annotation version history').click();
    await expect(page.getByText('Annotation history')).toBeVisible();
    const restoreButtons = page.getByRole('button', { name: 'Restore' });
    await expect(restoreButtons.first()).toBeVisible();
    await restoreButtons.first().click();
    await expect(page.locator('[data-quantity-item="Manual count"]')).toBeVisible();

    const annotationsResponse = page.waitForResponse((response) =>
      response.request().method() === 'GET' && /\/annotations$/.test(response.url()),
    );
    await page.reload();
    expect((await annotationsResponse).ok()).toBeTruthy();
    await expect(page.getByText(/AI complete/)).toBeVisible({ timeout: 45_000 });
    await expect(page.locator('[data-quantity-item="Manual area"]')).toContainText(String(editedArea));
    await expect(page.locator('[data-annotation-type="area"]')).toHaveCount(1);
    await expect(page.locator('[data-annotation-type="line"]')).toHaveCount(1);
    await expect(page.locator('[data-annotation-type="count"]')).toHaveCount(1);

    for (const format of ['CSV', 'Excel']) {
      const downloadPromise = page.waitForEvent('download');
      await page.getByRole('button', { name: 'Export', exact: true }).click();
      await page.getByRole('button', { name: `Export as ${format}` }).click();
      const download = await downloadPromise;
      const bytes = await downloadBytes(download);
      expect(bytes.length).toBeGreaterThan(100);
      expect(download.suggestedFilename()).toMatch(format === 'CSV' ? /\.csv$/ : /\.xlsx$/);
      if (format === 'CSV') {
        const csv = bytes.toString('utf8');
        expect(csv).toContain('Manual area');
        expect(csv).toContain(String(editedArea));
      } else {
        expect(bytes.subarray(0, 2).toString('ascii')).toBe('PK');
      }
    }

  });

  test('failed cross-tenant project request shows a usable isolated error state', async ({ page, request }) => {
    const identity = uniqueIdentity('isolated-estimator');
    await signup(request, identity);
    const other = uniqueIdentity('other-tenant');
    const otherSession = await signup(request, other);
    const otherProject = await request.post(`${API_URL}/api/projects`, {
      headers: { Authorization: `Bearer ${otherSession.access_token}` },
      data: { name: 'Other Tenant Secret', project_type: 'Commercial' },
    });
    expect(otherProject.ok(), await otherProject.text()).toBeTruthy();
    const secretProject = await otherProject.json();
    cleanupProjects.push({ id: secretProject.id, token: otherSession.access_token });

    await loginInBrowser(page, identity.email);
    const forbiddenResponse = page.waitForResponse((response) =>
      response.url().endsWith(`/api/projects/${secretProject.id}`),
    );
    await page.goto(`/app/projects/${secretProject.id}`);
    expect((await forbiddenResponse).status()).toBe(404);
    await expect(page.getByTestId('project-error-state')).toContainText('Project unavailable');
    await expect(page.getByTestId('project-error-state')).toContainText('Project not found');
    await expect(page.getByText('Other Tenant Secret')).toHaveCount(0);
  });
});
