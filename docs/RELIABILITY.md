# 可靠性契约与回归覆盖

更新日期：2026-10-29（Asia/Shanghai）。本文描述当前本机可信代码执行模式；不将测试覆盖扩大为生产级或通用外部副作用保证。

## 1. 文件覆盖不变量

工具可读取或修改的普通工作区文件必须参与内容指纹计算，不能因为路径以点号开头就被忽略。`.settings.py`、`.custom/settings.py` 等均参与 SHA256 聚合。

只排除 `__pycache__`、`.pytest_cache`、`.ruff_cache` 路径，以及保留的 `.harness-write-*` 临时路径。应用工具也拒绝访问这些排除路径，因此它们不能成为工具可编辑但验收漏检的文件。缓存内容仍可能被 Python 运行时使用；契约依赖可信代码，不提供对恶意缓存注入的隔离保证。

原始测试验收结果与工作区指纹绑定。隐藏文件在测试后变化，已有证据即失效。文件列表采用同一缓存排除规则，不再漏掉普通隐藏源码。

对应回归：

- `test_hidden_operable_file_changes_fingerprint`：两类隐藏路径的读取、修改、指纹变化和文件列表。
- `test_hidden_change_invalidates_cached_final_evidence`：通过验收后修改隐藏文件，最终状态不得成功。
- `test_excluded_generated_files_cannot_be_tool_inputs`：四类排除路径不可通过工具访问。

## 2. Harness 指定最终验收范围

任务初始快照中的全部 `test_*.py` 是最终验收清单，允许嵌套和隐藏目录。Agent 的 `run_tests(target)` 仍用于自主检查单个根目录测试文件，不决定最终范围。

服务层在图结束后调用 `ToolRunner.acceptance()`，核对原始测试内容，使用内部测试入口逐个加载清单文件并合并 unittest 测试集。清单中任一文件加载失败或任一测试失败，都不能使任务成功。新增文件不会替代初始测试；验收范围不包含清单以外的新测试。

验收写入现有 `tool_calls` 表，名称为 `harness_acceptance`，调用 ID 为 `harness:acceptance:v1`，不暴露给模型。复用成功结果时仍核对原始测试和当前工作区指纹。没有原始测试清单的旧任务阻断，需要创建新任务。

验收必须满足：退出码为 0、至少运行一条测试、测试前后指纹一致、最终指纹与证据一致。该结论不等于满足全部自然语言需求，也不支持不可信代码伪造输出或自行修改状态文件的对抗场景。

对应回归：

- `test_final_acceptance_runs_all_original_files`：根目录/隐藏目录分别覆盖部分测试通过但完整集失败，以及完整集通过的四个组合。
- `test_original_acceptance_tests_cannot_be_changed_or_removed`：原始测试修改、删除均阻断。
- `test_acceptance_preserves_original_crlf_bytes`：不因文本读取的换行转换误判原始文件。
- 浏览器 `test_ui_acceptance.mjs`：页面展示完整验收失败而非 Agent 部分测试成功；未知验收结果需要显式重试。

## 3. Worker 退出后的测试清理

测试执行由独立监督进程协调，协议为：

```text
Worker 持有任务锁
  → 监督进程取得 tests.lock 清理租约
  → 通知 Worker ready
  → Worker 发 go 并保持管道打开
  → 监督进程建立进程树管理，放行内部启动入口
  → 测试执行，可能产生派生进程
  → 正常结束 / 超时 / Worker 管道 EOF
  → 清理整个受控进程树
  → 清理确认后移除 uncertain 标记、释放租约
```

Windows 使用 Job Object，将内部启动入口加入 Job 后才传入测试命令。清理调用终止整个 Job，并查询活跃进程数直至为零。Linux 分支在发送终止信号后扫描进程组，确认没有仍在运行的成员才继续；已退出的僵尸不具有工作区执行能力。其他 POSIX 平台保守等待进程组消失。进程树的管理不依赖恢复进程根据旧 PID 猜测和终止进程。

新执行者在进入执行图、工具及验收前等待清理租约，最多 10 秒。不能取得租约则阻断；监督进程清理未确认时保留 `<任务id>.tests.uncertain`，即使设置 `retry_uncertain_tests=true` 也不能跳过。

Worker 死亡后清理成功，也不能自动断言上一次测试可安全重跑：调用日志仍是 started，因此默认阻断，需操作者确认副作用后显式允许重试。清理与重试授权处理不同问题。

如果监督进程自身异常退出或系统接口错误，需先确认无测试进程残留，再人工处理该任务的 uncertain 标记。不可批量删除标记后假定安全。当前没有自动修复这一状态的接口。

对应真实实验：

- `test_worker_death_cleans_live_test_tree_before_safe_resume[agent]`。
- `test_worker_death_cleans_live_test_tree_before_safe_resume[acceptance]`。

两种实验均等待测试和派生进程持续写心跳后，令 Worker 调用 `os._exit(86)`；立即请求恢复，不先在测试中等待清理。断言恢复阻断未知结果、两个进程已停止、心跳不再变化、租约可获取；显式允许重试后完成，文件写入尝试仍为 1。

另外覆盖启动授权之前所有者管道关闭时不启动测试，以及未确认清理标记阻断已授权重试。

本轮在 Windows 实测。POSIX 清理等待分支有模拟回归，Linux 真实实验等待 CI 执行，不能将模拟检查当作 Linux 已验证。主动脱离进程组、恶意逃逸、主机掉电和不可信代码不在保证内。监督机制不是容器或 OS 安全沙箱。

监督协议读取有超时；监督进程退出、返回缺失或损坏、清理确认失败均阻断任务，不标为可以绕过的普通失败。`test_cleanup_contract.py` 包含清理等待、持续存活成员、损坏协议以及真实监督进程清理确认失败后的恢复阻断测试。补充复审结果见 [REVIEW.md](REVIEW.md)。

## 4. 文件并发修改契约

任务锁协调所有遵守协议的执行者；工作区执行期间独占，不支持编辑器或任意外部程序同时修改它。这是约定，不是文件权限强制隔离。

`replace_text` 进行首次版本校验，持久化意图；恢复按 before/after 哈希核对。临时文件写入并 fsync 后，在替换前再次核对目标哈希，能拦截准备写入期间已出现的变更。

最后一次检查与 `os.replace` 不是一个原子操作，仍有 TOCTOU 竞争。因此“保留冲突内容”的保证限于检查时已可见的冲突，不等于覆盖所有不协作外部写入。原子替换也不构成文件系统 CAS。

对应回归：

- `test_change_during_temp_write_is_detected_before_replacement`：在临时文件 fsync 时插入外部修改，确认被阻断且内容保留。
- `test_uncoordinated_write_after_last_check_is_outside_contract`：在最后核对后、替换前插入外部修改，明确验证仍可能被覆盖。这是限制的可执行示例，不是宣称竞争已修复。
- 原有任务锁冲突与恢复时外部变更保护测试继续运行。

## 5. 接口兼容与迁移

- HTTP 路径、请求格式和三个模型工具的参数不变。
- 不引入新数据库表；内部验收复用现有工具日志结构。
- `metrics.tool_calls` 包含内部验收，默认示例从 3 变成 4；它不表示模型发出了 4 次工具请求。
- 前端优先展示 Harness 验收输出；旧任务没有该记录时回退到 Agent 测试输出。
- 未知验收结果沿用现有测试重试复选框。
- 没有原始文件快照的历史任务不能生成可靠验收清单，需要新建任务。

## 6. 重跑

```powershell
uv run pytest -q
uv run ruff check src tests
uv run harness evaluate
# 先启动使用相同 WORKBENCH_DATA_DIR 的本地服务
npm.cmd run test:ui
```

本轮结果与机器可读报告见 [VALIDATION.md](VALIDATION.md) 和 [reliability-report.json](reliability-report.json)。
