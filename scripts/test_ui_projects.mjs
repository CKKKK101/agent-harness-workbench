import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { chromium } from "playwright-core";

const executablePath = process.env.CHROME_PATH || [
  "C:/Program Files/Google/Chrome/Application/chrome.exe", "/usr/bin/google-chrome", "/usr/bin/chromium",
].find((p) => existsSync(p));
const base = process.env.WORKBENCH_UI_URL || "http://127.0.0.1:8000";
const root = mkdtempSync(path.join(tmpdir(), "harness-project-ui-"));
const browser = await chromium.launch({ executablePath, headless: true });
const checks = [], errors = [];
const check = (name) => { checks.push(name); console.log(`PASS ${name}`); };
mkdirSync("artifacts", { recursive: true });
try {
  const withTests = path.join(root, "existing-project"), withoutTests = path.join(root, "no-tests-project");
  mkdirSync(path.join(withTests, "tests"), { recursive: true });
  mkdirSync(withoutTests);
  writeFileSync(path.join(withTests, "app.py"), "VALUE=1\n");
  writeFileSync(path.join(withTests, "tests/test_app.py"), "def test_app(): assert True\n");
  writeFileSync(path.join(withoutTests, "app.py"), "VALUE=1\n");
  const page = await browser.newPage({ viewport: { width: 1440, height: 1040 } });
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/health", async (route) => {
    const response = await route.fetch();
    await route.fulfill({ json: { ...await response.json(), model_configured: true, model_name: "browser-mock" } });
  });
  // Never contact a model or execute arbitrary repair code in browser checks.
  const taskBodies = [];
  await page.route("**/tasks/from-project", async (route) => {
    taskBodies.push(route.request().postDataJSON());
    await route.fulfill({ status: 422, json: { detail: "Browser test captured submission; model execution disabled" } });
  });
  await page.goto(base);
  await page.waitForFunction(() => document.querySelector("#connection-status").classList.contains("online"));
  await page.locator("#mode-real").click();
  await page.locator("#folder-input").setInputFiles(withTests);
  await page.locator("#project-preview").getByText("tests/test_app.py", { exact: true }).waitFor();
  assert.equal(await page.locator("#candidate-panel").isVisible(), false);
  await page.locator("#task-prompt").fill("修复 app.py 中 VALUE 的错误，保持原有接口。");
  await page.locator("#run-button").click();
  await page.waitForFunction(() => !document.querySelector("#run-button").disabled);
  assert.equal(taskBodies.length, 1);
  assert.equal(taskBodies[0].confirm_acceptance, undefined);
  check("local folder preserves tests/ paths and submits existing project without manual test upload");

  await page.locator("#folder-input").setInputFiles(withoutTests);
  await page.locator("#candidate-panel").waitFor();
  await page.locator("#run-button").click();
  assert.equal(taskBodies.length, 1);
  const candidateFiles = { "tests/test_app.py": "from app import VALUE\ndef test_value(): assert VALUE == 2\n" };
  let generated = 0;
  await page.route("**/projects/*/candidate-tests", async (route) => {
    if (route.request().postDataJSON().files) { await route.continue(); return; }
    generated++;
    await route.fulfill({ status: 201, json: { id: "model-preview-only", files: candidateFiles, requires_confirmation: true } });
  });
  await page.locator("#expected-behavior").fill("导入 app 后 VALUE 应为 2。");
  await page.locator("#generate-candidates").click();
  await page.waitForFunction(() => document.querySelector("#candidate-json").value.includes("test_value"));
  assert.equal(generated, 1);
  assert.equal(await page.locator("#confirm-acceptance").isChecked(), false);
  assert.equal(taskBodies.length, 1);
  check("candidate generation stays a preview and cannot start repair without human confirmation");

  await page.locator("#confirm-acceptance").check();
  await page.locator("#expected-behavior").fill("导入 app 后 VALUE 应为整数 2。");
  assert.equal(await page.locator("#confirm-acceptance").isChecked(), false);
  await page.locator("#confirm-acceptance").check();
  await page.locator("#candidate-json").fill(JSON.stringify(candidateFiles, null, 2));
  assert.equal(await page.locator("#confirm-acceptance").isChecked(), false);
  await page.locator("#confirm-acceptance").check();
  const reviewed = page.waitForResponse((r) => r.url().includes("/candidate-tests") && r.request().postDataJSON()?.files);
  await page.locator("#run-button").click();
  const saved = await (await reviewed).json();
  await page.waitForFunction(() => !document.querySelector("#run-button").disabled);
  assert.equal(taskBodies.length, 2);
  assert.equal(taskBodies[1].candidate_id, saved.id);
  assert.equal(taskBodies[1].confirm_acceptance, true);
  assert.equal(taskBodies[1].expected, "导入 app 后 VALUE 应为整数 2。");
  check("changing criteria or candidates clears approval; reviewed exact revision binds the submission");

  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForFunction(() => document.querySelector("#sidebar").getBoundingClientRect().right <= 1);
  await page.evaluate(() => scrollTo(0, 0));
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
  await page.screenshot({ path: "artifacts/ui-candidates-mobile.png", fullPage: true });
  await page.setViewportSize({ width: 1440, height: 1040 });
  await page.waitForFunction(() => document.querySelector("#sidebar").getBoundingClientRect().left >= 0);
  await page.screenshot({ path: "artifacts/ui-candidates-desktop.png", fullPage: true });

  await page.route("**/projects/import", async (route) => {
    const body = route.request().postDataJSON();
    assert.equal(body.github_url, "https://github.com/example/small-project");
    await route.fulfill({ status: 201, json: {
      id: "github-preview", label: "example/small-project", files: ["app.py", "tests/test_app.py"],
      test_files: ["tests/test_app.py"], framework: "pytest", needs_acceptance: false,
    } });
  });
  await page.locator("#github-url").fill("https://github.com/example/small-project");
  await page.locator("#github-import").click();
  await page.locator("#project-preview").getByText("example/small-project", { exact: true }).waitFor();
  assert.equal(await page.locator("#candidate-panel").isVisible(), false);
  check("public repository control refreshes the preview and discards stale candidate approval");

  await page.screenshot({ path: "artifacts/ui-projects-desktop.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForFunction(() => document.querySelector("#sidebar").getBoundingClientRect().right <= 1);
  await page.evaluate(() => scrollTo(0, 0));
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
  await page.screenshot({ path: "artifacts/ui-projects-mobile.png", fullPage: true });
  assert.deepEqual(errors, []);
  check("project controls fit mobile without horizontal overflow or uncaught JavaScript errors");
  writeFileSync("artifacts/ui-projects.json", JSON.stringify({ checks, errors, model: "mocked", githubNetwork: "mocked" }, null, 2));
} finally {
  await browser.close();
  if (path.resolve(root).startsWith(path.resolve(tmpdir()) + path.sep)) rmSync(root, { recursive: true, force: true });
}
