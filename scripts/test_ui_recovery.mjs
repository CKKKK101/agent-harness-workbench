// Check the resume button and a fast-completion/event-cursor race against the real local server.
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { promisify } from "node:util";
import { chromium } from "playwright-core";

const python = [".venv/Scripts/python.exe", ".venv/bin/python"].map((p) => path.resolve(p)).find(existsSync);
const executablePath = [process.env.CHROME_PATH,
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "/usr/bin/google-chrome", "/usr/bin/chromium",
].find((p) => p && existsSync(p));
const base = process.env.WORKBENCH_UI_URL || "http://127.0.0.1:8000";
assert.ok(python && executablePath, "A project virtual environment and Chrome/Edge are required");
assert.ok(["127.0.0.1", "localhost"].includes(new URL(base).hostname), "Recovery test requires a local server using the project's .env");
const { stdout } = await promisify(execFile)(python, [
  "-m", "harness_workbench.cli", "demo", "--fault", "after_effect",
], { encoding: "utf8" });
const task = JSON.parse(stdout);
assert.equal(task.status, "interrupted");
mkdirSync("artifacts", { recursive: true });
const browser = await chromium.launch({ executablePath, headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1040 }, locale: "zh-CN" });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(base, { waitUntil: "networkidle" });
  await page.waitForFunction((id) => document.querySelector("#task-id-label").textContent.includes(id)
    && document.querySelector("#execution-status").textContent === "执行中断", task.id.slice(0, 8).toUpperCase());
  // Let the worker finish before the event history is read. A stale status paired
  // with the final cursor must not leave the page permanently showing "running".
  await page.route(/\/tasks\/[a-f0-9]+\/events\?after=/, async (route) => {
    await delay(500); await route.continue();
  });
  await page.locator("#resume-button").click();
  await page.waitForFunction(() => document.querySelector("#execution-status").textContent === "已验证完成", null, { timeout: 15000 });
  const final = await (await page.request.get(`${base}/tasks/${task.id}`)).json();
  assert.equal(final.status, "succeeded");
  assert.equal(final.metrics.file_write_attempts, 1);
  assert.ok(final.metrics.reused_results >= 1);
  assert.equal(await page.locator("#trace-list .trace-step.done").count(), 4);
  assert.deepEqual(errors, []);
  await page.locator("#toast").waitFor({ state: "hidden" });
  await page.screenshot({ path: "artifacts/ui-desktop.png", fullPage: true });
  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 }, locale: "zh-CN" });
  await mobile.goto(base, { waitUntil: "networkidle" });
  await mobile.waitForFunction(() => document.querySelector("#execution-status").textContent === "已验证完成");
  await mobile.screenshot({ path: "artifacts/ui-mobile.png", fullPage: true });
  const report = {
    passed: true, scenario: "resume_after_effect_with_delayed_event_history",
    task_id: task.id, status: final.status, metrics: final.metrics, errors,
  };
  writeFileSync("artifacts/ui-recovery.json", JSON.stringify(report, null, 2));
  console.log("PASS resume interrupted task via UI and reconcile fast completion");
  console.log(JSON.stringify(report, null, 2));
} finally { await browser.close(); }
