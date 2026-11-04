// Real local memory lifecycle + deterministic graph. No paid model calls.
import assert from "node:assert/strict";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { chromium } from "playwright-core";

const executablePath = [process.env.CHROME_PATH,
  "C:/Program Files/Google/Chrome/Application/chrome.exe", "/usr/bin/chromium"]
  .find((path) => path && existsSync(path));
const base = process.env.WORKBENCH_UI_URL || "http://127.0.0.1:8000";
const browser = await chromium.launch({ executablePath, headless: true });
const checks = [], errors = [];
const check = (name) => { checks.push(name); console.log(`PASS ${name}`); };
mkdirSync("artifacts", { recursive: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1040 } });
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(base);
  await page.waitForFunction(() => document.querySelector("#connection-status").classList.contains("online"));
  await page.locator("#memory-settings summary").click();
  const scope = `ui-memory-${Date.now()}`;
  await page.locator("#memory-scope").fill(scope);
  await page.locator("#memory-key").fill("style");
  await page.locator("#memory-content").fill("Preserve calculator.py public function names.");
  await page.locator("#memory-save").click();
  await page.locator("#memory-list").getByText("style · v1 · active", { exact: true }).waitFor();
  check("project memory can be saved and listed in the workbench");
  await page.locator("#memory-content").fill("Use explicit types and preserve calculator.py function names.");
  await page.locator("#memory-save").click();
  await page.locator("#memory-list").getByText("style · v2 · active", { exact: true }).waitFor();
  check("editing memory creates a new revision");

  const tasks = [];
  for (let attempt = 0; attempt < 2; attempt++) {
    const created = page.waitForResponse((r) => r.url() === `${base}/tasks/demo` && r.request().method() === "POST");
    await page.locator("#run-button").click();
    const task = await (await created).json(); tasks.push(task.id);
    await page.waitForFunction((id) =>
      document.querySelector("#task-id-label").textContent.toUpperCase().includes(id.slice(0, 8).toUpperCase())
      && document.querySelector("#execution-status").textContent.includes("已验证完成"), task.id);
    const response = await page.request.get(`${base}/tasks/${task.id}/context`);
    const contexts = await response.json();
    assert.ok(contexts[0].memory_references.some((m) => m.key === "style" && m.version === 2));
    assert.match(await page.locator("#context-info").innerText(), /演示模型上下文已调用/);
  }
  assert.notEqual(tasks[0], tasks[1]);
  check("two independent tasks recall the same current project-memory revision");
  await page.locator("#memory-refresh").click();
  const row = page.locator(".memory-record").filter({ hasText: "style · v2 · active" });
  await row.getByRole("button", { name: "标记失效" }).click();
  await page.locator("#memory-list").getByText("style · v3 · invalid", { exact: true }).waitFor();
  const recall = await (await page.request.post(`${base}/memory/${scope}/recall`, {
    data: { task_id: tasks[1] },
  })).json();
  assert.ok(!recall.selected.some((m) => m.key === "style"));
  check("invalidating memory excludes it from subsequent recall");
  await page.evaluate(() => {
    document.querySelector("#memory-list").scrollTop = 0;
    window.scrollTo({ top: 0, behavior: "instant" });
  });
  await page.waitForFunction(() => document.querySelector("#toast").hidden && scrollY === 0);
  await page.screenshot({ path: "artifacts/memory-desktop.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForFunction(() => document.querySelector("#sidebar").getBoundingClientRect().right <= 1);
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.screenshot({ path: "artifacts/memory-mobile.png", fullPage: true });
  check("expanded memory controls fit a 390px mobile viewport");
  assert.deepEqual(errors, []);
  check("no uncaught browser errors");
  writeFileSync("artifacts/ui-memory.json", JSON.stringify({ passed: true, checks,
    errors, model: "deterministic_fixture", generation_quality_evaluated: false }, null, 2));
} finally { await browser.close(); }
