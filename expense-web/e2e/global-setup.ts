import { chromium } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const STORAGE_DIR = path.resolve(HERE, '.auth');
const STORAGE_PATH = path.join(STORAGE_DIR, 'user.json');
const BASE_URL = 'http://localhost:5173';

const globalSetup = async (): Promise<void> => {
  await mkdir(STORAGE_DIR, { recursive: true });

  const browser = await chromium.launch();
  const context = await browser.newContext();
  const page = await context.newPage();

  await page.goto(`${BASE_URL}/login`);
  await page.getByRole('button', { name: /sign in \(stub\)/i }).click();
  await page.waitForURL('**/merchants', { timeout: 15_000 });

  await context.storageState({ path: STORAGE_PATH });
  await browser.close();
};

export default globalSetup;
