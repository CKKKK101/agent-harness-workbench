"use strict";

(() => {
  const ICONS = {
    layers: '<path d="m12 3 9 4.5-9 4.5-9-4.5L12 3Z"/><path d="m3 12 9 4.5 9-4.5M3 16.5 12 21l9-4.5"/>',
    grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    history: '<path d="M3 11a9 9 0 1 1 2.7 7M3 4v7h7M12 7v5l3 2"/>',
    settings: '<path d="m9 3-1 3-3 1-2 4 2 2v4l4 3 3-1 3 1 4-3v-4l2-2-2-4-3-1-1-3Z"/><circle cx="12" cy="12" r="3"/>',
    book: '<path d="M4 4h6l2 2 2-2h6v16h-6l-2 1-2-1H4V4ZM12 6v15"/>',
    external: '<path d="M14 3h7v7M21 3 11 13M10 3H4v17h17v-6"/>',
    shield: '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z"/><path d="m8 12 3 3 5-6"/>',
    chevrons: '<path d="m8 9 4-4 4 4M8 15l4 4 4-4"/>',
    panel: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
    refresh: '<path d="M20 7v5h-5M4 17v-5h5M5.6 7a7.5 7.5 0 0 1 12.7-1L20 9M4 15l1.7 3A7.5 7.5 0 0 0 18.4 17"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    "play-circle": '<circle cx="12" cy="12" r="9"/><path d="m10 8 6 4-6 4V8Z"/>',
    play: '<path d="m8 4 12 8-12 8V4Z"/>',
    stack: '<rect x="5" y="3" width="14" height="15" rx="2"/><path d="M9 7h6M9 11h6M2 7v12a2 2 0 0 0 2 2h11"/>',
    "check-circle": '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
    activity: '<path d="M2 12h5l3-8 4 16 3-8h5"/>',
    flag: '<path d="M5 21V3h7l2 2h6v10h-7l-2-2H5"/>',
    spark: '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3ZM20 2v4M18 4h4"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/>',
    terminal: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m7 9 3 3-3 3M13 15h4"/>',
    flask: '<path d="M9 3h6M10 3v6l-6 10a1 1 0 0 0 1 2h14a1 1 0 0 0 1-2L14 9V3M7 14h10"/>',
    upload: '<path d="M12 16V3m-5 5 5-5 5 5M4 15v5h16v-5"/>',
    search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
    code: '<path d="m8 6-6 6 6 6M16 6l6 6-6 6M14 3l-4 18"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
    "arrow-right": '<path d="M4 12h16m-6-6 6 6-6 6"/>',
    route: '<circle cx="6" cy="5" r="2"/><circle cx="18" cy="19" r="2"/><path d="M6 7v8a4 4 0 0 0 4 4h6M18 17V9a4 4 0 0 0-4-4h-3"/>',
    copy: '<rect x="8" y="8" width="12" height="13" rx="2"/><path d="M16 8V3H3v13h5"/>',
    "git-diff": '<path d="M9 3H4v7M4 6l6 6M15 21h5v-7M20 18l-6-6M14 5h7M17.5 1.5v7M3 19h7"/>',
    list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    download: '<path d="M12 3v13m-5-5 5 5 5-5M4 17v4h16v-4"/>',
    inbox: '<path d="m3 4-1 12v4h20v-4L21 4H3ZM2 15h6l2 3h4l2-3h6"/>',
    x: '<path d="m6 6 12 12M6 18 18 6"/>',
    menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  };
  const $ = (id) => document.getElementById(id);
  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  function icon(name) {
    const span = el("span");
    span.dataset.icon = name;
    span.setAttribute("aria-hidden", "true");
    paintIcons(span);
    return span;
  }
  function paintIcons(root = document) {
    const nodes = [...root.querySelectorAll("[data-icon]")];
    if (root.matches?.("[data-icon]")) nodes.push(root);
    for (const node of nodes) {
      if (node.dataset.iconReady) continue;
      node.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[node.dataset.icon] || ICONS.code}</svg>`;
      node.dataset.iconReady = "true";
    }
  }
  const STATUS = {
    queued: ["等待执行", "neutral"], running: ["正在执行", "running"],
    succeeded: ["已验证完成", "success"], failed: ["执行失败", "failed"],
    interrupted: ["执行中断", "warning"], blocked: ["等待处理", "warning"],
  };
  const TERMINAL = new Set(["succeeded", "failed", "interrupted", "blocked"]);
  const EVENT_TYPES = [
    "task.created", "task.running", "task.succeeded", "task.failed", "task.interrupted", "task.blocked",
    "tool.prepared", "tool.completed", "tool.reused", "tool.input_error", "tool.retry_authorized",
    "model.completed", "verification.completed", "fault.injected", "execution.error",
  ];
  const DEMO_PROMPT = $("task-prompt").value;
  const state = {
    tasks: [], health: null, selectedId: null, task: null, events: [],
    diff: { files: [], baseline_available: false }, chosenFile: null,
    mode: "demo", realPrompt: "", tab: "diff", view: "workspace",
    uploads: new Map(), source: null, generation: 0, busy: false,
    toastTimer: null, polling: false, online: false,
  };

  function toast(message, error = false) {
    clearTimeout(state.toastTimer);
    $("toast-message").textContent = message;
    $("toast").classList.toggle("error", error);
    $("toast").hidden = false;
    state.toastTimer = setTimeout(() => { $("toast").hidden = true; }, error ? 6000 : 3500);
  }
  function friendlyError(message) {
    if (message.includes("requires OPENAI_API_KEY")) return "请先配置模型密钥与模型名称，然后重新启动服务。";
    if (message.includes("already executing")) return "任务已经在运行，请等待当前执行完成。";
    if (message.includes("Finished tasks")) return "该任务已经结束，请创建一个新任务。";
    if (message.includes("test_*.py")) return "请同时上传至少一个 test_*.py 单元测试文件。";
    return message;
  }
  async function api(path, options = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(path, {
        ...options, signal: controller.signal,
        headers: { "Content-Type": "application/json", ...options.headers },
      });
      const data = await response.json();
      if (!response.ok) {
        const detail = typeof data.detail === "string" ? data.detail
          : Array.isArray(data.detail) ? data.detail.map((d) => d.msg).join("；") : `请求失败（${response.status}）`;
        throw new Error(friendlyError(detail));
      }
      return data;
    } catch (error) {
      if (error.name === "AbortError") throw new Error("请求超时，请检查本地服务是否仍在运行。");
      if (error instanceof TypeError) throw new Error("暂时无法连接服务，请检查启动窗口或稍后重试。");
      throw error;
    } finally { clearTimeout(timeout); }
  }
  function setConnection(online) {
    state.online = online;
    $("connection-status").className = `connection ${online ? "online" : "offline"}`;
    $("connection-status").lastElementChild.textContent = online ? "本地服务已连接" : "服务未连接";
    $("connection-banner").hidden = online;
    $("model-dot").classList.toggle("configured", Boolean(state.health?.model_configured));
    updateRunButton();
  }
  async function refreshHealth() {
    try { state.health = await api("/health"); setConnection(true); }
    catch { setConnection(false); }
  }
  function badge(status) {
    const [label, kind] = STATUS[status] || ["未知状态", "neutral"];
    return el("span", `status-badge ${kind}`, label);
  }
  function shortId(id) { return id ? id.slice(0, 8).toUpperCase() : ""; }
  function taskTitle(task) {
    return task.model_mode === "demo" ? "修复 calculator.py 的加法逻辑" : task.prompt.split("\nWorkspace files:")[0];
  }
  function formatTime(seconds, date = false) {
    if (!seconds) return "—";
    return new Intl.DateTimeFormat("zh-CN", date ? {
      month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
    } : { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(new Date(seconds * 1000));
  }
  function duration(task) {
    if (!task) return "—";
    const end = task.status === "running" ? Date.now() / 1000 : task.updated_at;
    const seconds = Math.max(0, end - task.created_at);
    return seconds >= 60 ? `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s` : `${seconds.toFixed(1)}s`;
  }
  function renderStats() {
    $("stat-total").textContent = state.tasks.length;
    $("stat-completed").textContent = state.tasks.filter((t) => t.status === "succeeded").length;
    $("stat-running").textContent = state.tasks.filter((t) => ["running", "queued"].includes(t.status)).length;
    $("stat-attention").textContent = state.tasks.filter((t) => ["failed", "blocked", "interrupted"].includes(t.status)).length;
    $("nav-count").textContent = state.tasks.length;
    $("history-total").textContent = state.tasks.length;
  }
  function renderHistory() {
    const query = $("task-search").value.trim().toLowerCase();
    const tasks = state.tasks.filter((t) => `${taskTitle(t)} ${t.id} ${STATUS[t.status]?.[0]}`.toLowerCase().includes(query));
    const visible = state.view === "history" || query ? tasks : tasks.slice(0, 5);
    $("history-body").replaceChildren();
    $("history-empty").hidden = visible.length > 0;
    if (!visible.length) {
      $("history-empty").querySelector("strong").textContent = query ? "没有找到匹配任务" : "从第一个任务开始";
      $("history-empty").lastElementChild.textContent = query ? "试试其他关键词或任务编号。" : "点击「运行示例任务」，体验完整流程。";
    }
    for (const task of visible) {
      const row = el("tr", task.id === state.selectedId ? "selected-row" : "");
      const titleCell = el("td");
      const titleButton = el("button", "task-title-button");
      titleButton.title = taskTitle(task);
      const marker = el("span", "task-row-icon"); marker.append(icon("code"));
      const text = el("span");
      text.append(el("span", "task-title", taskTitle(task)), el("span", "task-row-id", `TASK-${shortId(task.id)}`));
      titleButton.append(marker, text);
      titleButton.addEventListener("click", () => openTask(task.id));
      titleCell.append(titleButton);
      const status = el("td"); status.append(badge(task.status));
      const mode = el("td");
      const modeLabel = el("span", "mode-label");
      modeLabel.append(icon(task.model_mode === "demo" ? "flask" : "spark"), document.createTextNode(task.model_mode === "demo" ? "示例演示" : "真实模型"));
      mode.append(modeLabel);
      const calls = el("td", "table-number", String(task.metrics.tool_calls));
      const time = el("td", "table-number", formatTime(task.created_at, true));
      const action = el("td");
      const button = el("button", "row-open", ["interrupted", "blocked"].includes(task.status) ? "查看与恢复" : "查看详情");
      button.append(icon("arrow-right")); button.addEventListener("click", () => openTask(task.id));
      action.append(button); row.append(titleCell, status, mode, calls, time, action);
      $("history-body").append(row);
    }
    $("history-footer-label").textContent = query ? `找到 ${tasks.length} 个匹配任务`
      : state.view === "history" ? `共 ${tasks.length} 个任务 · 数据保存在本地`
      : `显示最近 ${visible.length} 个任务 · 共 ${state.tasks.length} 个`;
  }
  async function refreshTasks(autoSelect = false) {
    try {
      state.tasks = await api("/tasks");
      renderStats(); renderHistory();
      if (autoSelect && state.tasks.length && !state.selectedId) await selectTask(state.tasks[0].id);
    } catch (error) { setConnection(false); throw error; }
  }

  function getToolData() {
    const names = new Map();
    for (const event of state.events) if (event.kind === "tool.prepared") names.set(event.payload.call_id, event.payload.name);
    const completed = state.events.filter((e) => e.kind === "tool.completed").map((e) => ({
      ...e, name: names.get(e.payload.call_id), result: e.payload.result,
    }));
    return {
      names, completed,
      read: completed.filter((e) => e.name === "inspect_file").at(-1),
      edit: completed.filter((e) => e.name === "replace_text").at(-1),
      test: completed.filter((e) => e.name === "harness_acceptance").at(-1)
        || completed.filter((e) => e.name === "run_tests").at(-1),
      verification: state.events.filter((e) => e.kind === "verification.completed").at(-1),
    };
  }
  function renderTrace() {
    const { read, edit, test, verification } = getToolData();
    const stages = [
      { title: "读取源码", note: "检索业务代码，获取待修改文件的版本。", event: read,
        done: Boolean(read), detail: read ? `${read.result.path} · 已读取源码与文件版本` : null },
      { title: "应用修复", note: "根据问题修改代码，并记录执行结果。", event: edit,
        done: Boolean(edit), detail: edit ? (edit.result.reconciled ? "已确认先前修改，恢复时未重复写入" : `${edit.result.path} · 已保存修改结果`) : null },
      { title: "运行测试", note: "执行单元测试，检查修复是否符合预期。", event: test,
        done: Boolean(test?.result.verified), error: Boolean(test && !test.result.verified),
        detail: test ? `${test.result.tests_run} 条测试 · ${test.result.verified ? "全部通过" : test.result.timed_out ? "执行超时" : "验证未通过"}` : null },
      { title: "验证并完成", note: "独立运行完整验收测试集，并核对最终代码状态。", event: verification,
        done: Boolean(verification?.payload.verified), error: Boolean(verification && !verification.payload.verified),
        detail: verification ? (verification.payload.verified ? "测试证据与工作区指纹一致，任务已完成" : "尚未获得最终代码通过测试的有效证据") : null },
    ];
    const current = stages.findIndex((s) => !s.done);
    $("trace-list").replaceChildren();
    stages.forEach((stage, index) => {
      const active = state.task?.status === "running" && index === current;
      const row = el("div", `trace-step ${stage.done ? "done" : stage.error ? "error" : active ? "active" : ""}`);
      const marker = el("span", "trace-marker");
      if (stage.done || stage.error) marker.append(icon(stage.done ? "check" : "x"));
      else marker.textContent = String(index + 1).padStart(2, "0");
      const content = el("div", "trace-step-content");
      const top = el("div", "trace-step-top");
      const time = el("time", "", stage.event ? formatTime(stage.event.created_at) : active ? "执行中" : "—");
      top.append(el("h3", "", stage.title), time);
      content.append(top, el("p", "", stage.detail || stage.note));
      row.append(marker, content); $("trace-list").append(row);
    });
    const task = state.task;
    const [label, kind] = task ? (STATUS[task.status] || ["未知", "neutral"]) : ["等待任务", "neutral"];
    $("execution-status").textContent = label;
    $("execution-status").className = `status-badge ${kind}`;
    $("task-id-label").textContent = task ? `TASK-${shortId(task.id)} · ${task.model_mode === "demo" ? "示例演示" : "真实模型"}` : "尚未选择任务";
    $("task-time-label").textContent = task ? `历时 ${duration(task)}` : "—";
    $("task-time-label").title = "从任务创建到最近状态更新的时间，含中断等待时间";
    $("copy-task-id").hidden = !task;
    $("live-label").classList.toggle("active", task?.status === "running");
    $("live-label").lastElementChild.textContent = !task ? "执行记录将显示在这里"
      : task.status === "running" ? "正在接收执行事件" : `已保存 ${state.events.length} 条执行事件`;
    const finished = task && TERMINAL.has(task.status);
    $("result-banner").hidden = !finished;
    if (finished) {
      const success = task.status === "succeeded";
      $("result-banner").classList.toggle("error", !success);
      const message = success ? `修复已验证${test ? ` · ${test.result.tests_run} 条测试通过` : ""}`
        : task.status === "interrupted" ? "执行已中断，保存的状态可用于继续任务。"
        : task.status === "blocked" ? "任务需要处理，请检查下方恢复说明。" : "任务未完成验证，请查看测试输出和执行事件。";
      $("result-banner").replaceChildren(icon(success ? "check-circle" : "info"), el("strong", "", message));
    }
    const recoverable = task && ["interrupted", "blocked"].includes(task.status);
    $("recovery-actions").hidden = !recoverable;
    const uncertain = task?.error?.includes("Previous test execution");
    $("retry-tests-label").hidden = !uncertain;
    $("resume-button").disabled = state.busy || (uncertain && !$("retry-tests").checked);
    if (recoverable) $("recovery-explanation").textContent = uncertain
      ? "上次测试已经启动，但没有保存最终结果。请先检查是否产生副作用，再决定是否允许重试。"
      : task.status === "blocked" ? "工作区可能与保存的执行意图存在冲突。请检查源码与执行事件，确认恢复条件。"
      : "可以从已保存的执行状态继续；已经记录的工具结果会被复用。";
  }
  function renderTests() {
    const { test } = getToolData();
    $("test-output").textContent = test?.result.output || "测试输出将在任务运行后显示。";
    $("test-summary").textContent = test ? `${test.result.tests_run} TESTS / ${test.result.verified ? "PASSED" : "NOT VERIFIED"}` : "等待测试执行";
    $("test-summary").style.color = test ? (test.result.verified ? "#60937a" : "#b78b6b") : "";
  }
  function renderEvents() {
    $("event-count").textContent = state.events.length;
    if (!state.events.length) return;
    const previousScroll = $("events-list").scrollTop;
    $("events-list").replaceChildren();
    for (const event of state.events) {
      const row = el("div", "event-row");
      const detail = el("details");
      detail.append(el("summary", "", event.kind), el("pre", "", JSON.stringify(event.payload, null, 2)));
      row.append(el("time", "", formatTime(event.created_at)), detail);
      $("events-list").append(row);
    }
    $("events-list").scrollTop = previousScroll;
  }
  function renderExecution() { renderTrace(); renderTests(); renderEvents(); }

  function lines(text) {
    if (text === "" || text === null || text === undefined) return [];
    const result = text.replace(/\r\n/g, "\n").split("\n");
    if (result.at(-1) === "") result.pop();
    return result;
  }
  function diffLines(before, after) {
    const a = lines(before).slice(0, 500), b = lines(after).slice(0, 500);
    const width = b.length + 1;
    const matrix = new Uint16Array((a.length + 1) * width);
    for (let i = a.length - 1; i >= 0; i--) for (let j = b.length - 1; j >= 0; j--) {
      matrix[i * width + j] = a[i] === b[j] ? matrix[(i + 1) * width + j + 1] + 1
        : Math.max(matrix[(i + 1) * width + j], matrix[i * width + j + 1]);
    }
    const rows = []; let i = 0, j = 0;
    while (i < a.length || j < b.length) {
      if (i < a.length && j < b.length && a[i] === b[j]) {
        rows.push({ kind: "same", text: a[i], old: ++i, next: ++j });
      } else if (i < a.length && (j === b.length || matrix[(i + 1) * width + j] >= matrix[i * width + j + 1])) {
        rows.push({ kind: "remove", text: a[i], old: ++i, next: "" });
      } else rows.push({ kind: "add", text: b[j], old: "", next: ++j });
    }
    return rows;
  }
  function syntaxLine(text) {
    const output = el("span", "line-text");
    const regex = /#[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\b(?:def|return|import|from|class|self|if|else|elif|for|while|try|except|raise|with|as|pass|True|False|None|assert|in|not|and|or)\b|\b\d+(?:\.\d+)?\b/g;
    let index = 0;
    for (const match of text.matchAll(regex)) {
      output.append(document.createTextNode(text.slice(index, match.index)));
      const value = match[0];
      const kind = value.startsWith("#") ? "comment" : /^["']/.test(value) ? "string" : /^\d/.test(value) ? "number" : "keyword";
      output.append(el("span", `syntax-${kind}`, value)); index = match.index + value.length;
    }
    output.append(document.createTextNode(text.slice(index)));
    return output;
  }
  function currentFile() { return state.diff.files.find((f) => f.path === state.chosenFile); }
  function renderCode() {
    const file = currentFile();
    $("copy-file").disabled = !file || file.after === null;
    $("download-file").disabled = !file || file.after === null;
    if (!file) return;
    const unknown = file.change === "unknown";
    const rows = unknown ? lines(file.after).slice(0, 500).map((text, i) => ({ kind: "same", text, old: "", next: i + 1 })) : diffLines(file.before, file.after);
    const long = Math.max(lines(file.before).length, lines(file.after).length) > 500;
    $("diff-summary").replaceChildren();
    if (unknown) $("diff-summary").textContent = "未保存原始版本 · 当前源码";
    else if (file.change === "unchanged") $("diff-summary").textContent = "未修改";
    else {
      if (long) $("diff-summary").append(document.createTextNode("预览 "));
      $("diff-summary").append(el("span", "added", `+${rows.filter((r) => r.kind === "add").length}`), el("span", "removed", `−${rows.filter((r) => r.kind === "remove").length}`));
    }
    $("code-view").replaceChildren();
    for (const row of rows) {
      const line = el("div", `code-line ${row.kind}`);
      line.append(el("span", "line-number", String(row.old)), el("span", "line-number", String(row.next)),
        el("span", "line-sign", row.kind === "add" ? "+" : row.kind === "remove" ? "−" : " "), syntaxLine(row.text));
      $("code-view").append(line);
    }
    if (long) $("code-view").append(el("p", "composer-footnote", "预览最多展示前 500 行，可下载查看完整文件。"));
  }
  function renderDiff() {
    const files = state.diff.files;
    const previous = state.chosenFile;
    state.chosenFile = files.some((f) => f.path === previous) ? previous
      : (files.find((f) => ["modified", "added", "deleted"].includes(f.change)) || files[0])?.path;
    $("file-select").replaceChildren();
    for (const file of files) {
      const option = el("option", "", file.path); option.value = file.path;
      $("file-select").append(option);
    }
    if (!files.length) $("file-select").append(el("option", "", "尚无任务文件"));
    else $("file-select").value = state.chosenFile;
    $("changed-count").textContent = files.filter((f) => ["modified", "added", "deleted"].includes(f.change)).length;
    renderCode();
  }
  function stopStream() { state.source?.close(); state.source = null; }
  async function allEvents(taskId) {
    let cursor = 0; const events = [];
    while (true) {
      const batch = await api(`/tasks/${taskId}/events?after=${cursor}`);
      events.push(...batch);
      if (batch.length < 500) return events;
      cursor = batch.at(-1).id;
    }
  }
  async function selectTask(taskId, connect = true) {
    const generation = ++state.generation;
    stopStream();
    state.selectedId = taskId;
    $("retry-tests").checked = false;
    try {
      let [events, diff] = await Promise.all([
        allEvents(taskId), api(`/tasks/${taskId}/diff`),
      ]);
      // Read status after the event cursor. Otherwise a very fast completion can
      // leave a stale "running" status paired with a cursor past the final event.
      const task = await api(`/tasks/${taskId}`);
      if (TERMINAL.has(task.status)) {
        [events, diff] = await Promise.all([allEvents(taskId), api(`/tasks/${taskId}/diff`)]);
      }
      if (generation !== state.generation) return;
      state.task = task; state.events = events; state.diff = diff;
      state.tasks = state.tasks.map((entry) => entry.id === taskId ? task : entry);
      renderExecution(); renderDiff(); renderStats(); renderHistory();
      if (connect && !TERMINAL.has(task.status)) subscribe(taskId, generation);
    } catch (error) { if (generation === state.generation) toast(error.message, true); }
  }
  function subscribe(taskId, generation) {
    const cursor = state.events.at(-1)?.id || 0;
    const source = new EventSource(`/tasks/${taskId}/stream?after=${cursor}`);
    state.source = source;
    for (const kind of EVENT_TYPES) source.addEventListener(kind, (message) => {
      if (generation !== state.generation) { source.close(); return; }
      let event;
      try { event = JSON.parse(message.data); } catch { return; }
      if (state.events.some((e) => e.id === event.id)) return;
      state.events.push(event); state.events.sort((a, b) => a.id - b.id);
      renderExecution();
      if (kind.startsWith("task.") && TERMINAL.has(kind.slice(5))) {
        source.close(); state.source = null;
        selectTask(taskId, false); refreshTasks().catch(() => {});
      }
    });
    source.onerror = () => {
      if (state.task?.status === "running") $("live-label").lastElementChild.textContent = "连接重试中，执行记录已保存";
    };
  }
  async function openTask(taskId) {
    setView("workspace"); await selectTask(taskId);
    $("execution-heading").scrollIntoView({ behavior: "smooth", block: "center" });
  }
  function setTab(tab, focus = false) {
    state.tab = tab;
    for (const name of ["diff", "tests", "events"]) {
      const selected = name === tab;
      $(`tab-${name}`).classList.toggle("selected", selected);
      $(`tab-${name}`).setAttribute("aria-selected", String(selected));
      $(`tab-${name}`).tabIndex = selected ? 0 : -1;
      $(`content-${name}`).hidden = !selected;
    }
    if (focus) $(`tab-${tab}`).focus();
  }
  function setView(view) {
    state.view = view;
    document.body.classList.toggle("history-view", view === "history");
    $("workspace-view").hidden = view === "history";
    $("breadcrumb-current").textContent = view === "history" ? "任务记录" : "任务工作台";
    $("page-title").replaceChildren(document.createTextNode(view === "history" ? "任务记录" : "任务工作台"), el("span", "heading-dot", "."));
    $("page-description").textContent = view === "history" ? "每一次执行，都有完整的记录与结果。" : "从问题到修复，让每一步执行都有迹可循。";
    for (const button of document.querySelectorAll("[data-view]")) {
      button.classList.toggle("active", button.dataset.view === view);
      if (button.dataset.view === view) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    }
    $("sidebar").classList.remove("open"); renderHistory();
  }
  function setMode(mode) {
    if (state.mode === "real") state.realPrompt = $("task-prompt").value;
    state.mode = mode;
    const demo = mode === "demo";
    $("mode-demo").classList.toggle("selected", demo); $("mode-real").classList.toggle("selected", !demo);
    $("mode-demo").setAttribute("aria-pressed", String(demo)); $("mode-real").setAttribute("aria-pressed", String(!demo));
    $("task-prompt").readOnly = demo;
    $("task-prompt").value = demo ? DEMO_PROMPT : state.realPrompt;
    $("task-prompt").placeholder = "描述需要修复的问题、预期行为与测试文件名…";
    $("prompt-readonly").textContent = demo ? "预设示例" : "最多 8000 字";
    $("prompt-hint").textContent = demo ? "代码修复 / Python" : "请注明要执行的 test_*.py 文件";
    $("mode-explanation").lastElementChild.textContent = demo ? "无需密钥，体验完整的修复与验证流程。" : "使用已配置的模型，修复你上传的 Python 代码。";
    $("demo-files").hidden = !demo; $("real-files").hidden = demo;
    $("composer-footnote").lastChild.textContent = demo ? "固定演示流程 · 实际修改文件并运行测试" : "只运行可信代码 · 文件会复制到独立工作区";
    updateRunButton();
  }
  function updateRunButton() {
    $("run-button").disabled = state.busy || !state.online;
    $("run-button-label").textContent = state.busy ? "正在提交任务…" : state.mode === "demo" ? "运行示例任务" : !state.health?.model_configured ? "配置模型后开始" : "开始修复任务";
  }
  async function submitTask() {
    if (state.busy) return;
    if (state.mode === "real" && !state.health?.model_configured) { showSettings(); return; }
    let payload;
    if (state.mode === "real") {
      const prompt = $("task-prompt").value.trim();
      if (prompt.length < 5) { toast("请先描述要修复的问题。", true); $("task-prompt").focus(); return; }
      if (!state.uploads.size) { toast("请上传业务代码与 test_*.py 单元测试文件。", true); return; }
      if (![...state.uploads.keys()].some((name) => /^test_\w+\.py$/.test(name))) { toast("需要一个根目录的 test_*.py 单元测试文件。", true); return; }
      payload = { prompt, files: Object.fromEntries(state.uploads), model_mode: "openai" };
    }
    state.busy = true; updateRunButton();
    try {
      const task = await api(state.mode === "demo" ? "/tasks/demo" : "/tasks", {
        method: "POST", body: JSON.stringify(payload || {}),
      });
      state.chosenFile = null; setTab("diff");
      await refreshTasks(); await selectTask(task.id);
      toast("任务已创建，执行轨迹会自动更新。");
    } catch (error) { toast(error.message, true); }
    finally { state.busy = false; updateRunButton(); }
  }
  async function addFiles(files) {
    const pending = new Map(state.uploads);
    try {
      for (const file of files) {
        if (!/^[^\\/:]+\.py$/i.test(file.name)) throw new Error("当前支持上传同一目录下的 Python（.py）文件。");
        if (file.size > 256000) throw new Error(`${file.name} 超过 256 KB 限制。`);
        if ([...pending.keys()].some((name) => name.toLowerCase() === file.name.toLowerCase() && name !== file.name)) throw new Error("文件名仅大小写不同，请先重命名后上传。");
        pending.set(file.name, await file.text());
      }
      if (pending.size > 30) throw new Error("一次最多上传 30 个文件。");
      if ([...pending.values()].reduce((n, text) => n + new TextEncoder().encode(text).length, 0) > 512000) throw new Error("上传文件总大小不能超过 512 KB。");
      state.uploads = pending; renderUploads();
    } catch (error) { toast(error.message, true); }
    finally { $("file-input").value = ""; }
  }
  function renderUploads() {
    $("uploaded-files").replaceChildren();
    for (const [name] of state.uploads) {
      const row = el("div", "uploaded-file");
      const remove = el("button"); remove.setAttribute("aria-label", `移除 ${name}`); remove.append(icon("x"));
      remove.addEventListener("click", () => { state.uploads.delete(name); renderUploads(); });
      row.append(icon("code"), el("span", "", name), remove); $("uploaded-files").append(row);
    }
  }

  function showDialog(title, eyebrow, content) {
    $("dialog-title").textContent = title; $("dialog-eyebrow").textContent = eyebrow;
    $("dialog-body").replaceChildren(...content); $("info-dialog").showModal();
  }
  function showGuide() {
    const steps = [
      ["运行示例任务", "选择「示例演示」，点击运行。无需密钥，系统会实际修复预设代码并执行测试。"],
      ["跟踪执行过程", "右侧展示源码读取、文件修改和测试验证。任务状态与执行记录会自动更新。"],
      ["检查代码与测试", "在下方切换代码差异、测试输出和执行事件，确认发生了哪些修改。"],
      ["接入你自己的任务", "配置模型后切换到「真实模型」，上传可信的 Python 源码和 test_*.py 测试文件。"],
    ].map(([title, copy], i) => {
      const row = el("div", "guide-step"), text = el("div");
      text.append(el("h3", "", title), el("p", "", copy));
      row.append(el("span", "guide-number", String(i + 1).padStart(2, "0")), text); return row;
    });
    showDialog("开始你的第一个任务", "GET STARTED", steps);
  }
  function showSettings() {
    const configured = state.health?.model_configured;
    const nodes = [el("div", "dialog-status", configured ? `已配置模型：${state.health.model_name}` : "尚未配置真实模型，示例演示仍可正常使用。"),
      el("p", "dialog-copy", "在项目目录的 .env 文件中填写模型配置，然后重启服务。密钥只保存在本地，不会显示在页面中。"),
      el("pre", "dialog-code", "WORKBENCH_MODEL_MODE=openai\nOPENAI_API_KEY=你的密钥\nOPENAI_MODEL=支持工具调用的模型名\nOPENAI_BASE_URL=服务商的兼容接口地址"),
      el("p", "dialog-copy", "配置完成后，刷新本页并切换到「真实模型」即可提交任务。服务暂未提供操作系统级沙箱，请只运行可信代码。")];
    showDialog("连接你的模型", "MODEL CONNECTION", nodes);
  }
  async function resumeTask() {
    if (!state.selectedId || state.busy) return;
    state.busy = true; $("resume-button").disabled = true;
    try {
      const id = state.selectedId;
      await api(`/tasks/${id}/resume`, { method: "POST", body: JSON.stringify({ retry_uncertain_tests: $("retry-tests").checked }) });
      await refreshTasks(); await selectTask(id); toast("任务已恢复，正在继续执行。");
    } catch (error) { toast(error.message, true); }
    finally { state.busy = false; renderTrace(); updateRunButton(); }
  }
  async function copy(text) {
    try { await navigator.clipboard.writeText(text); toast("已复制到剪贴板。"); }
    catch { toast("浏览器未允许复制，请手动选择内容复制。", true); }
  }
  async function refreshAll() {
    await refreshHealth();
    if (!state.online) return;
    try { await refreshTasks(true); if (state.selectedId) await selectTask(state.selectedId); }
    catch (error) { toast(error.message, true); }
  }
  function bindEvents() {
    document.querySelector(".brand").addEventListener("click", () => setView("workspace"));
    $("workspace-info").addEventListener("click", () => showDialog("个人工作空间", "LOCAL WORKSPACE", [
      el("div", "dialog-status", `已保存 ${state.tasks.length} 个任务`),
      el("p", "dialog-copy", "任务记录、源码版本和执行结果保存在当前电脑。刷新页面或重新启动服务后，可以继续查看历史任务。"),
      el("p", "dialog-copy", "选择「任务记录」查看全部任务；需要接入真实模型时，打开「模型连接」。"),
    ]));
    $("run-button").addEventListener("click", submitTask);
    $("mode-demo").addEventListener("click", () => setMode("demo"));
    $("mode-real").addEventListener("click", () => setMode("real"));
    $("guide-button").addEventListener("click", showGuide);
    $("settings-nav").addEventListener("click", showSettings);
    $("refresh-button").addEventListener("click", refreshAll);
    $("retry-connection").addEventListener("click", refreshAll);
    $("new-task-button").addEventListener("click", () => {
      setView("workspace"); $("composer").scrollIntoView({ behavior: "smooth", block: "center" });
      (state.mode === "demo" ? $("mode-demo") : $("task-prompt")).focus({ preventScroll: true });
    });
    for (const button of document.querySelectorAll("[data-view]")) button.addEventListener("click", () => setView(button.dataset.view));
    $("task-search").addEventListener("input", renderHistory);
    $("file-select").addEventListener("change", (event) => { state.chosenFile = event.target.value; renderCode(); });
    for (const button of document.querySelectorAll("[data-tab]")) button.addEventListener("click", () => setTab(button.dataset.tab));
    document.querySelector(".inspector-tabs").addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault(); const tabs = ["diff", "tests", "events"], index = tabs.indexOf(state.tab);
      const next = event.key === "Home" ? 0 : event.key === "End" ? 2 : (index + (event.key === "ArrowRight" ? 1 : -1) + 3) % 3;
      setTab(tabs[next], true);
    });
    $("show-events").addEventListener("click", () => { setTab("events"); $("tab-events").scrollIntoView({ behavior: "smooth", block: "center" }); });
    $("file-input").addEventListener("change", (event) => addFiles(event.target.files));
    $("upload-zone").addEventListener("dragover", (event) => { event.preventDefault(); $("upload-zone").classList.add("dragging"); });
    $("upload-zone").addEventListener("dragleave", () => $("upload-zone").classList.remove("dragging"));
    $("upload-zone").addEventListener("drop", (event) => { event.preventDefault(); $("upload-zone").classList.remove("dragging"); addFiles(event.dataTransfer.files); });
    $("resume-button").addEventListener("click", resumeTask);
    $("retry-tests").addEventListener("change", renderTrace);
    $("copy-file").addEventListener("click", () => { const file = currentFile(); if (file?.after !== null && file?.after !== undefined) copy(file.after); });
    $("copy-task-id").addEventListener("click", () => state.selectedId && copy(state.selectedId));
    $("download-file").addEventListener("click", () => {
      const file = currentFile(); if (!file || file.after === null) return;
      const url = URL.createObjectURL(new Blob([file.after], { type: "text/plain;charset=utf-8" }));
      const anchor = el("a"); anchor.href = url; anchor.download = file.path.split("/").at(-1);
      document.body.append(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    $("dialog-close").addEventListener("click", () => $("info-dialog").close());
    $("dialog-done").addEventListener("click", () => $("info-dialog").close());
    $("info-dialog").addEventListener("click", (event) => {
      const box = $("info-dialog").getBoundingClientRect();
      if (event.target === $("info-dialog") && (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom)) $("info-dialog").close();
    });
    $("menu-toggle").addEventListener("click", () => {
      const open = $("sidebar").classList.toggle("open"); $("menu-toggle").setAttribute("aria-expanded", String(open));
    });
    document.addEventListener("click", (event) => {
      if (!$("sidebar").contains(event.target) && !$("menu-toggle").contains(event.target)) $("sidebar").classList.remove("open");
    });
    document.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && ["1", "2"].includes(event.key)) { event.preventDefault(); setView(event.key === "1" ? "workspace" : "history"); }
    });
    window.addEventListener("beforeunload", stopStream);
  }
  async function init() {
    paintIcons(); bindEvents(); setTab("diff"); renderTrace(); renderStats(); renderHistory();
    await refreshHealth();
    if (state.online) await refreshTasks(true).catch((error) => toast(error.message, true));
    setInterval(refreshHealth, 15000);
    setInterval(async () => {
      const selectedPending = state.task && !TERMINAL.has(state.task.status);
      if (state.polling || !state.online || (!selectedPending && !state.tasks.some((t) => ["running", "queued"].includes(t.status)))) return;
      state.polling = true;
      try {
        await refreshTasks();
        if (state.selectedId && state.task && !TERMINAL.has(state.task.status)) await selectTask(state.selectedId);
      } catch {} finally { state.polling = false; }
    }, 4000);
  }
  init().catch((error) => toast(error.message, true));
})();
