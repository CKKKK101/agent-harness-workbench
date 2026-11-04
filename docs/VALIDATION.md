# 本地验证记录

## 2026-11-04：跨 Session 记忆增强

Windows 全量 **146 项 pytest、25 项浏览器检查、5/5 原恢复场景通过**；Ruff 通过。新增 18 项后端回归和 3 项浏览器检查。原有 13 条 LangSmith 弃用提示保留。设计与适用边界见 [MEMORY_UPGRADE.md](MEMORY_UPGRADE.md)。

新增覆盖客观经验卡与独立验收来源、无有效验收不得写入、当前文件事实严格校验、历史经验仅供参考、服务重启后第二个任务的实际上下文注入、精确经验去重、来源失效、推理期间删除/替代/失效、向量缓存不复活删除记忆、超时/异常降级及调试接口。实际本地 BGE 另驱动两次确定性修复任务，两次均验收成功，第二个任务的模型输入确实包含第一次的经验；这仍不代表真实 LLM 的修复质量收益。

真实 BGE 检索：8 条手工备注、24 条自建查询，开发和留出各 8 正例 + 4 无关问题。留出 Hit@3：BM25 **5/8（62.5%）**、向量 **4/8（50%）**、混合 **6/8（75%）**，各方法无关问题均拒绝 4/4。保留失败样本；没有用留出结果反复调阈值。小样本多命中 1 条不能写成通用任务成功率提升。原始结果见 [memory-retrieval-evaluation.json](memory-retrieval-evaluation.json)，验证汇总见 [memory-upgrade-validation.json](memory-upgrade-validation.json)。

原生模型使用现有本地缓存，无新模型下载或付费 LLM 调用。当前本机默认 `.workbench` 已准备模型配置；使用其他数据目录需另行准备。Linux 分支仍以远端实际运行记录为准，不把 Windows 验证当作 Linux 实测。

## 2026-11-04：项目导入与候选测试确认

Windows 本地全量 **128 项 pytest 通过**（原有 91 项加本轮 37 项）、**22 项浏览器检查通过**（原有 17 项加本轮 5 项）、原有子进程恢复评测 **5/5 通过**，Ruff 通过。全量测试继续覆盖 Worker 在 Agent 测试与最终验收实际运行时退出、清理测试进程树及未知结果阻断。

新增覆盖静态导入不执行代码、嵌套测试及 src 布局、pytest / unittest 完整验收、部分通过与完整失败、全部跳过不得成功、测试配置只读、归档路径与大小限制、候选预览不创建任务、人工确认门槛、输入变化使候选过期、用户修订版本冻结、模型失败和新 API。浏览器执行真实文件夹上传与后台导入，检查已有测试自动发现、候选展示和确认、修改后取消确认及移动端；模型候选和 GitHub 网络使用 Mock，浏览器提交拦截以避免真实模型执行。后端通过确定性模型驱动真实图与测试子进程验证完整任务。

设计与限制见 [PROJECT_WORKFLOW.md](PROJECT_WORKFLOW.md)，机器可读记录见 [project-workflow-validation.json](project-workflow-validation.json)。没有测量真实模型修复率、候选测试充分性或公开 GitHub 仓库总体兼容性。只支持文档所列的小型可信 Python 快照；依赖、数据文件、插件和 Linux 实测边界没有扩大。

本次 pytest JUnit 输出附带 13 条既有 LangSmith 弃用提示及 2 条 pytest 报告格式提示；测试无失败。原始结果位于忽略目录 `artifacts/project-workflow-junit.xml`，UI 结果及截图位于 `artifacts/ui-projects*` / `artifacts/ui-candidates*`。

## 2026-11-03：项目记忆与上下文管理

Windows 本地全量 **91 项 pytest 通过**（本轮新增 36 项）、**17 项浏览器检查通过**（原有 11 项加新增 6 项）、原有子进程恢复评测 **5/5 通过**。原进程生命周期、完整验收和冲突保护回归继续通过。

新增覆盖跨任务重启召回、scope 隔离、版本 CAS 并发冲突、TTL、文件证据变化、失效和删除后的缓存重建、工具轮次完整性、必要上下文超预算阻断、快照损坏，以及压缩提交前后真实 `os._exit(86)`。实际图集成检查确认压缩输入与完整 Checkpoint 历史可以共存。浏览器检查含两次不同任务的真实记忆注入记录和移动端。

详细设计见 [MEMORY_CONTEXT.md](MEMORY_CONTEXT.md)，机器可读记录见 [memory-context-validation.json](memory-context-validation.json)。这些验证使用确定性模型及 HTTP Mock，不是长期记忆语义质量、真实模型修复率或 Token 成本评测。本机仍未执行真实 Linux 分支；原 13 条 LangSmith 弃用提示仍存在。

## 2026-10-29：上轮复审快照

上轮复审补充验证：**55 项 pytest、11 项浏览器检查、5/5 恢复评测通过**。此前 49 项为第一轮修复结果；当时新增 6 项清理与监督协议回归。详见 [REVIEW.md](REVIEW.md) 和 [review-report.json](review-report.json)。Linux 作业已配置，等待远端实际执行，不将 Windows 模拟检查视为 Linux 已验证。

## 2026-10-29：可靠性审查修复后的验证

本轮为 Windows 本地实际执行结果，完整报告见 [reliability-report.json](reliability-report.json)，保证与限制见 [RELIABILITY.md](RELIABILITY.md)。下方 2026-10-28 内容保留为历史记录，不能与本轮计数混用。

| 检查 | 本轮结果 |
|---|---|
| pytest 全量 | **49 passed**，含 20 项新增回归 |
| Ruff | 通过 |
| 原有子进程恢复评测 | **5/5 通过**，每场景文件写入尝试 1 次 |
| Worker 在 Agent 测试执行时真实退出 | 退出码 86；测试与派生进程停止；默认阻断；允许重试后成功 |
| Worker 在 Harness 验收执行时真实退出 | 退出码 86；测试与派生进程停止；默认阻断；允许重试后成功 |
| 前端浏览器检查 | **11 项通过**，无未捕获 JavaScript 错误 |
| 完整测试集有失败文件 | Agent 部分测试通过仍不能成功，页面展示完整验收失败输出 |
| 隐藏文件证据与并发 | 隐藏文件变化使旧证据失效；检测可见冲突，并验证最后检查后的 TOCTOU 限制 |

两个运行中崩溃实验均在测试及派生进程写出心跳后才退出 Worker；立即请求恢复，确认清理后心跳不再变化、进程不再存活、清理租约可获取。未知结果未自动重跑，显式允许后成功，文件写入尝试保持 1。

本轮针对本机可信代码。未验证 POSIX 进程组分支、真实模型修复质量、主机掉电或恶意测试逃逸。独占工作区是协作约束，不是权限隔离。Python 3.14 仍产生既有 13 条 LangSmith 弃用提示，没有隐藏。

前端重跑包含原有 8 项常规检查、1 项恢复与状态竞态检查，以及 `test_ui_acceptance.mjs` 新增的 2 项验收展示与重试检查。独立验证服务使用 8001 端口和单独数据目录，与原有任务数据隔离；报告见 [ui-acceptance.json](ui-acceptance.json)。

重跑命令：

```powershell
uv run pytest -q -o junit_family=xunit1 --junitxml=artifacts/reliability-junit.xml
uv run ruff check src tests
uv run harness evaluate
# 先启动相同数据目录的本地服务
npm.cmd run test:ui
```

## 2026-10-28：初始验证（历史）

日期：2026-10-28（Asia/Shanghai）。这是一次本地开发验证，不是线上业务数据。

## 环境与来源

- Windows，Python 3.14.0。
- Deep Agents 0.7.32，官方标签 `deepagents==0.7.32`，发布提交短哈希 `e85c6b9`。
- 官方源码已保存于 `upstream/deepagents-deepagents-0.7.32`。
- ZIP SHA256：`181fe2b866e601f51c05f35c333840762467c1c1d502483a66ed394edc084702`。
- 依赖由 `uv.lock` 锁定，隔离虚拟环境通过依赖一致性检查。

Git clone 在本地网络中连接重置，因此使用固定标签的官方 codeload 压缩包获取源码；这是源码归档，不含上游 Git 历史。

## 已执行的验证

| 项目 | 结果 |
|---|---|
| 原始 Deep Agents 图的模型→工具→模型闭环 | 通过，无应用 JournalMiddleware |
| pytest | **29 passed**（含前端资源、源码版本快照与旧任务兼容验证） |
| Ruff 检查 | 通过 |
| 隔离虚拟环境依赖一致性检查 | 通过，78 个包 |
| 真实 HTTP 本地服务调用 | 创建任务、查询、读取文件与事件均通过 |
| SSE 持久事件流 | 通过，演示任务包含 14 个事件 |
| OpenAI-compatible 模型适配 | 通过内存 HTTP transport 的协议测试，4 次模型响应 |
| 真实 LLM 推理效果 | **未验证：没有配置真实模型密钥** |
| 前端浏览器交互检查 | **9/9 通过**（8 项常规检查 + 1 项恢复与状态竞态回归），没有未捕获的 JavaScript 错误 |
| 响应式布局 | 1440px 桌面、390px 窄屏通过，页面没有横向溢出 |
| Python wheel 包 | 构建通过，包含全部 4 个前端静态资源 |

Python 3.14 下 LangSmith 依赖产生 13 条 `asyncio.iscoroutinefunction` 弃用提示，未隐藏；没有测试失败。Python 3.14 对“没有发现测试”返回码为 5，本项目仍独立检查测试数量，以兼容旧版本可能返回 0 的行为。

前端测试使用本机 Chrome 的独立无头实例，没有读取用户浏览器配置。覆盖：服务连接、创建任务、四步执行轨迹、真实源码差异、文件切换与下载、测试输出、事件查看、历史搜索、模型配置提示、上传与移除文件、断线重试和移动导航。另通过 CLI 创建文件写入后中断的任务，再在页面点击恢复；延迟事件历史请求以复现快速完成的状态竞态，确认页面显示最终完成状态且写入尝试仍为 1。报告见 `ui-report.json` 和 `ui-recovery.json`，截图见 `screenshots/`。

## 真正退出 worker 进程的恢复实验

模型：确定性 fixture。任务：修复一个加法函数，并通过三条固定 unittest。故障实验在独立进程中调用 `os._exit(86)`，再启动新进程恢复。

| 故障窗口 | 首次退出码 | 最终状态 | 执行尝试次数 | 文件写入尝试 | 结果复用次数 |
|---|---:|---|---:|---:|---:|
| 无故障对照 | 0 | succeeded | 1 | 1 | 0 |
| 修改意图持久化后 | 86 | succeeded | 2 | 1 | 0 |
| 文件修改后、成功记账前 | 86 | succeeded | 2 | 1 | 1 |
| 成功记账后、图保存前 | 86 | succeeded | 2 | 1 | 1 |
| 图完成后、任务完成状态提交前 | 86 | succeeded | 2 | 1 | 0 |

**5/5 场景通过**，每个场景的测试文件保持不变。`file_write_attempts` 统计 started 次数，不是对所有潜在故障的精确磁盘写入计数。

原始数据保存在本目录的 `recovery-report.json`，重新运行 `harness evaluate` 会生成新的 `artifacts/recovery-report.json`。

## 自动化测试还覆盖

- 恢复时发现外部修改：拒绝覆盖，保留手工修改。
- 相同工具调用 ID 携带不同参数：阻断执行。
- 工具路径逃逸、读取凭据路径、修改测试 fixture：拒绝。
- 测试结果未知：先阻断，再经过明确授权重试。
- 没有发现测试：不能标记任务成功。
- 测试超时：终止测试进程。
- 跨服务实例恢复与同任务锁冲突。
- 已完成任务不可再次通过 API 恢复。
- API 输入错误、缺失真实模型配置、事件补读。

## 结论边界

结果证明受限工具与持久化设计在这些可控故障窗口下能够恢复。没有验证通用代码修复能力、真实模型成功率、容器隔离、外部 API 的 exactly-once、断电恢复或大规模并发。

