// Optional UI checks. Uses an isolated, headless browser with no personal profile.
import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { chromium } from "playwright-core";

const browserPath = [
  process.env.CHROME_PATH,
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "/usr/bin/google-chrome", "/usr/bin/chromium",
].find((entry) => entry && existsSync(entry));
if (!browserPath) throw new Error("Set CHROME_PATH to a local Chrome/Chromium/Edge executable.");
const base = process.env.WORKBENCH_UI_URL || "http://127.0.0.1:8000";
mkdirSync("artifacts", { recursive: true });
const browser = await chromium.launch({ executablePath: browserPath, headless: true });
const errors = [];
const passed = [];
const check = (name) => { passed.push(name); console.log(`PASS ${name}`); };
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1040 }, locale: "zh-CN" });
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(base, { waitUntil: "networkidle" });
  await page.waitForFunction(() => document.querySelector("#connection-status").classList.contains("online"));
  assert.equal(await page.title(), "Harness Studio · Agent 工作台");
  check("desktop shell loads and connects to the backend");

  const previousId = await page.locator("#task-id-label").innerText();
  await page.locator("#run-button").click();
  await page.waitForFunction((prior) => {
    const id = document.querySelector("#task-id-label").textContent;
    return id !== prior && document.querySelector("#execution-status").textContent === "已验证完成";
  }, previousId);
  await page.locator("#code-view .code-line.add").waitFor();
  assert.match(await page.locator("#code-view .code-line.add").innerText(), /return a \+ b/);
  assert.match(await page.locator("#code-view .code-line.remove").innerText(), /return a - b/);
  assert.equal(await page.locator("#trace-list .trace-step.done").count(), 4);
  check("create demo, complete four stages, and render real source diff");

  await page.locator("#file-select").selectOption("test_calculator.py");
  assert.equal(await page.locator("#diff-summary").innerText(), "未修改");
  await page.locator("#file-select").selectOption("calculator.py");
  await page.locator("#tab-tests").click();
  assert.match(await page.locator("#test-output").innerText(), /Ran 3 tests/);
  assert.match(await page.locator("#test-output").innerText(), /OK/);
  await page.locator("#tab-events").click();
  assert.match(await page.locator("#events-list").innerText(), /task\.succeeded/);
  await page.locator("#tab-diff").click();
  const downloadEvent = page.waitForEvent("download");
  await page.locator("#download-file").click();
  const download = await downloadEvent;
  assert.equal(download.suggestedFilename(), "calculator.py");
  assert.match(readFileSync(await download.path(), "utf8"), /return a \+ b/);
  check("switch files, test output, and persisted execution events");

  await page.locator('[data-view="history"]').click();
  assert.equal(await page.locator("#workspace-view").isVisible(), false);
  await page.locator("#task-search").fill("no-such-task-xyz");
  assert.equal(await page.locator("#history-empty strong").innerText(), "没有找到匹配任务");
  await page.locator("#task-search").fill("");
  await page.locator("#history-body .row-open").first().click();
  assert.equal(await page.locator("#workspace-view").isVisible(), true);
  check("search task history and open a persisted task");

  await page.locator("#guide-button").click();
  assert.equal(await page.locator("#info-dialog").isVisible(), true);
  await page.keyboard.press("Escape");
  await page.locator("#mode-real").click();
  await page.locator("#task-prompt").fill("修复 calculator.py 中的 add 函数，并使用 test_calculator.py 验证。");
  await page.locator("#file-input").setInputFiles([
    path.resolve("examples/calculator/calculator.py"), path.resolve("examples/calculator/test_calculator.py"),
  ]);
  await page.waitForFunction(() => document.querySelectorAll(".uploaded-file").length === 2);
  assert.equal(await page.locator(".uploaded-file").count(), 2);
  await page.getByRole("button", { name: "移除 calculator.py", exact: true }).click();
  assert.equal(await page.locator(".uploaded-file").count(), 1);
  const health = await (await page.request.get(`${base}/health`)).json();
  if (!health.model_configured) {
    await page.locator("#run-button").click();
    assert.equal(await page.locator("#dialog-title").innerText(), "连接你的模型");
    await page.locator("#dialog-done").click();
  }
  await page.locator("#mode-demo").click();
  assert.match(await page.locator("#task-prompt").inputValue(), /当前错误地执行了减法/);
  check("guide, real-model upload/remove controls, and missing-model setup");

  await page.route("**/health", (route) => route.abort());
  await page.locator("#refresh-button").click();
  await page.waitForFunction(() => !document.querySelector("#connection-banner").hidden);
  assert.equal(await page.locator("#run-button").isDisabled(), true);
  await page.unroute("**/health");
  await page.locator("#retry-connection").click();
  await page.waitForFunction(() => document.querySelector("#connection-banner").hidden);
  assert.equal(await page.locator("#run-button").isDisabled(), false);
  check("connection failure and retry without losing the page");

  await page.locator("#toast").waitFor({ state: "hidden" });
  await page.screenshot({ path: "artifacts/ui-desktop.png", fullPage: true });
  const desktopLayout = await page.evaluate(() => ({
    width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
    heading: document.querySelector("h1").getBoundingClientRect().toJSON(),
    inspector: document.querySelector(".inspector-panel").getBoundingClientRect().toJSON(),
  }));
  assert.ok(desktopLayout.scrollWidth <= desktopLayout.width, "Desktop page overflows horizontally");

  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 }, locale: "zh-CN" });
  mobile.on("pageerror", (error) => errors.push(error.message));
  await mobile.goto(base, { waitUntil: "networkidle" });
  await mobile.waitForFunction(() => document.querySelector("#execution-status").textContent === "已验证完成");
  const mobileLayout = await mobile.evaluate(() => ({ width: innerWidth, scrollWidth: document.documentElement.scrollWidth }));
  assert.ok(mobileLayout.scrollWidth <= mobileLayout.width, "Mobile page overflows horizontally");
  await mobile.locator("#menu-toggle").click();
  assert.ok((await mobile.locator("#sidebar").getAttribute("class")).includes("open"));
  await mobile.locator('[data-view="history"]').click();
  assert.equal(await mobile.locator("#workspace-view").isVisible(), false);
  await mobile.locator("#new-task-button").click();
  assert.equal(await mobile.locator("#workspace-view").isVisible(), true);
  await mobile.waitForFunction(() => document.querySelector("#sidebar").getBoundingClientRect().right <= 1);
  await mobile.screenshot({ path: "artifacts/ui-mobile.png", fullPage: true });
  check("390px responsive layout and mobile navigation");
  assert.deepEqual(errors, [], "Browser JavaScript errors");
  check("no uncaught browser JavaScript errors");
  const report = { passed: passed.length, checks: passed, errors, desktopLayout, mobileLayout };
  writeFileSync("artifacts/ui-report.json", JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
} finally { await browser.close(); }
