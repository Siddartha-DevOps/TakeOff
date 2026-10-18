import { test, expect } from '@playwright/test';
import { scannedFloorPlanPdf } from './fixtures/scannedFloorPlan.js';
import { API_URL, clickPlan, loginInBrowser, signup, uniqueIdentity, waitForAutosave } from './helpers.js';

async function downloadBytes(download) {
  const stream = await download.createReadStream();
  if (!stream) throw new Error('Browser download did not expose a readable stream');
  const chunks = [];
  for await (const chunk of stream) chunks.push(Buffer.from(chunk));
  return Buffer.concat(chunks);
}

test('raster upload produces calibrated editable Mask R-CNN room overlay and export', async ({ page, request }) => {
  const identity = uniqueIdentity('mask-room');
  const session = await signup(request, identity);
  let projectId;
  try {
    await loginInBrowser(page, identity.email);
    await page.getByRole('button', { name: /new project/i }).click();
    await page.getByLabel('Project Name').fill('Mask Room Acceptance');
    await page.getByRole('button', { name: 'Create Project' }).click();
    await page.getByText('Mask Room Acceptance', { exact: true }).click();
    projectId = Number(page.url().match(/projects\/(\d+)/)[1]);

    await page.getByRole('button', { name: /upload blueprint/i }).click();
    await page.locator('input[type=file]').setInputFiles({
      name: 'scanned-mask-room.pdf', mimeType: 'application/pdf', buffer: scannedFloorPlanPdf(),
    });
    await page.getByRole('button', { name: /upload 1 file/i }).click();
    await expect(page.getByTestId('plan-surface')).toHaveAttribute('data-plan-ready', 'true', { timeout: 30_000 });

    await page.getByRole('button', { name: /calibrate scale/i }).click();
    await clickPlan(page, [[0.2, 0.8], [0.8, 0.8]]);
    await page.getByPlaceholder('e.g. 3').fill('40');
    const initialSave = waitForAutosave(page, (projection) => projection.quantities.some((row) => row.item === 'living area'));
    await page.getByRole('button', { name: 'Save scale' }).click();
    await expect(page.getByText(/AI complete/)).toBeVisible({ timeout: 45_000 });
    const projection = await initialSave;
    expect(projection.quantities.find((row) => row.item === 'living area')?.quantity).toBeGreaterThan(0);

    const room = page.locator('[data-annotation-source="ai"][data-annotation-type="area"]').first();
    await expect(room).toBeVisible();
    const pathData = await room.getByTestId('manual-annotation-shape').getAttribute('d');
    expect((pathData.match(/M /g) || []).length).toBeGreaterThanOrEqual(2);

    const selectTool = page.getByTitle('Select, move, or edit annotation vertices');
    await selectTool.click();
    await expect(selectTool).toHaveAttribute('aria-pressed', 'true');
    await room.getByTestId('manual-annotation-shape').click();
    const handle = room.getByTestId('manual-annotation-handle').first();
    const handleBox = await handle.boundingBox();
    expect(handleBox).not.toBeNull();
    const originalArea = projection.quantities.find((row) => row.item === 'living area').quantity;
    const correctionSave = waitForAutosave(page, (saved) => {
      const value = saved.quantities.find((row) => row.item === 'living area')?.quantity;
      return value > 0 && value !== originalArea;
    });
    await page.mouse.move(handleBox.x + handleBox.width / 2, handleBox.y + handleBox.height / 2);
    await page.mouse.down();
    await page.mouse.move(handleBox.x - 25, handleBox.y - 15, { steps: 5 });
    await page.mouse.up();
    const corrected = await correctionSave;
    const correctedArea = corrected.quantities.find((row) => row.item === 'living area').quantity;
    expect(correctedArea).not.toBe(originalArea);

    await page.reload();
    await expect(page.locator('[data-annotation-source="ai"][data-annotation-type="area"]')).toHaveCount(1);
    const persistedQuantity = page.locator('[data-quantity-item="living area"] .mono');
    await expect.poll(async () => Number((await persistedQuantity.innerText()).replaceAll(',', ''))).toBeCloseTo(correctedArea, 3);

    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Export', exact: true }).click();
    await page.getByRole('button', { name: 'Export as CSV' }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/\.csv$/);
    const csv = (await downloadBytes(download)).toString('utf8');
    expect(csv).toContain('living area');
    expect(csv).toContain(String(correctedArea));
  } finally {
    if (projectId) {
      await request.delete(`${API_URL}/api/projects/${projectId}`, {
        headers: { Authorization: `Bearer ${session.access_token}` },
      }).catch(() => {});
    }
  }
});
