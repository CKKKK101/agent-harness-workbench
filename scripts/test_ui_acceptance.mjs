// Regression: display Harness failure over partial success, and authorize unknown acceptance.
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { existsSync, writeFileSync } from "node:fs";
import path from "node:path";
import { promisify } from "node:util";
import { chromium } from "playwright-core";

const python = [".venv/Scripts/python.exe", ".venv/bin/python"].map((p) => path.resolve(p)).find(existsSync);
const executablePath = [process.env.CHROME_PATH,
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "/usr/bin/google-chrome", "/usr/bin/chromium",
].find((p) => p && existsSync(p));
const base = process.env.WORKBENCH_UI_URL || "http://127.0.0.1:8000";
assert.ok(["127.0.0.1", "localhost"].includes(new URL(base).hostname));
const execute = promisify(execFile);
const create = async (body) => {
  const { stdout } = await execute(python, ["-c", `
import json
from harness_workbench.config import Settings
from harness_workbench.service import TaskService
from harness_workbench.fixtures import demo_files
import harness_workbench.service as module
s = TaskService(Settings.from_env())
try:
${body.split("\n").map((line) => `    ${line}`).join("\n")}
finally:
    s.close()
`], { encoding: "utf8" });
  return JSON.parse(stdout);
};
const browser = await chromium.launch({ executablePath, headless: true });
const checks = [];
try {
  const failed = await create(String.raw`files = demo_files() | {"test_other.py": "import unittest\nclass Other(unittest.TestCase):\n    def test_failure(self): self.fail('full suite failure')\n"}
module.demo_files = lambda: files
t = s.create_task("Repair calculator and run all tests", files, mode="demo")
print(json.dumps(s.run_sync(t["id"])))`);
  assert.equal(failed.status, "failed");
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(base, { waitUntil: "networkidle" });
  await page.waitForFunction((id) => document.querySelector("#task-id-label").textContent.includes(id), failed.id.slice(0, 8).toUpperCase());
  await page.locator("#tab-tests").click();
  assert.match(await page.locator("#test-output").innerText(), /full suite failure/);
  assert.match(await page.locator("#test-summary").innerText(), /4 TESTS \/ NOT VERIFIED/);
  checks.push("Harness full-suite failure overrides Agent partial-test success in UI");

  const unknown = await create(`t = s.create_demo(fault="after_graph")
s.run_sync(t["id"])
s.store.prepare(t["id"], "harness:acceptance:v1", "harness_acceptance", {"targets": ["test_calculator.py"], "scope": "original_test_manifest_v1"}, {})
s.store.tool_started(t["id"], "harness:acceptance:v1")
print(json.dumps(s.run_sync(t["id"])))`);
  assert.equal(unknown.status, "blocked");
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForFunction((id) => document.querySelector("#task-id-label").textContent.includes(id), unknown.id.slice(0, 8).toUpperCase());
  assert.equal(await page.locator("#retry-tests-label").isVisible(), true);
  assert.equal(await page.locator("#resume-button").isDisabled(), true);
  await page.locator("#retry-tests").check();
  await page.locator("#resume-button").click();
  await page.waitForFunction(() => document.querySelector("#execution-status").textContent === "已验证完成");
  checks.push("Unknown Harness acceptance requires explicit retry through existing UI");
  assert.deepEqual(errors, []);
  writeFileSync("artifacts/ui-acceptance.json", JSON.stringify({ passed: true, checks, errors }, null, 2));
  for (const check of checks) console.log(`PASS ${check}`);
} finally { await browser.close(); }
