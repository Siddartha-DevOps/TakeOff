import { expect } from '@playwright/test';

export const API_URL = 'http://127.0.0.1:8000';
export const PASSWORD = 'E2e-pass-123!';

export function uniqueIdentity(prefix = 'estimator') {
  const suffix = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return { email: `${prefix}-${suffix}@example.com`, organization: `${prefix}-${suffix}` };
}

export async function signup(request, identity) {
  const response = await request.post(`${API_URL}/api/auth/signup`, {
    data: {
      email: identity.email,
      password: PASSWORD,
      full_name: 'Golden Estimator',
      organization_name: identity.organization,
    },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json();
}

export async function loginInBrowser(page, email) {
  await page.goto('/login');
  await page.getByLabel('Work email').fill(email);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: /sign in/i }).click();
  await expect(page).toHaveURL(/\/app$/);
  await expect(page.getByText('Welcome back, Golden.')).toBeVisible();
}

export async function waitForAutosave(page) {
  const response = await page.waitForResponse((candidate) =>
    candidate.request().method() === 'PUT'
      && /\/api\/takeoff\/drawings\/\d+\/annotations$/.test(candidate.url()),
  );
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json();
}

export async function clickPlan(page, points) {
  const surface = page.getByTestId('plan-surface');
  await expect(surface).toBeVisible();
  const box = await surface.boundingBox();
  if (!box) throw new Error('Plan surface has no browser bounding box');
  for (const [xRatio, yRatio] of points) {
    await page.mouse.click(box.x + box.width * xRatio, box.y + box.height * yRatio);
  }
  return box;
}
