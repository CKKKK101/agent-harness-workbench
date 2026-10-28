# 架构与恢复边界

## 三层职责

```text
Harness Studio（HTML / CSS / JavaScript） / CLI
        │ HTTP + SSE
FastAPI
        │
TaskService ── application.sqlite（任务、事件、工具执行意图与结果）
        │
Deep Agents 0.7.32
        │  JournalMiddleware：工具白名单、参数校验、日志与恢复
        │
LangChain Agent Loop / LangGraph
        │  每任务 SQLite Checkpoint：消息、图状态、下一执行节点
        │
ToolRunner ── 工作区文件 / 受限 unittest 子进程
```

LangGraph Checkpoint 负责运行图恢复；本项目的执行日志负责判断工作区副作用。二者没有跨数据库与文件系统的全局事务。

前端静态文件随 Python 包一同发布。任务创建时，将初始源码写入应用数据库的 `source_files` 表，与任务元数据处于同一事务；差异接口比较该快照与当前工作区，旧任务没有快照时显式返回 `baseline_available=false`，不推测历史内容。

## 文件修改流程

1. `inspect_file` 返回源码和 SHA256。
2. 模型调用 `replace_text`，携带先前的 SHA256 和唯一替换片段。
3. 工具准备阶段校验文件版本、替换次数、路径和测试文件保护规则。
4. 把 before hash、after hash、目标内容写入数据库并提交。
5. 将目标内容写入同目录临时文件，flush + fsync，然后 `os.replace`。
6. 记录成功结果，再把 ToolMessage 交回 LangGraph。

只读工具的持久结果可按相同调用 ID 复用；恢复新规划时使用新的调用 ID，避免把旧快照当成最新读数。

## 故障窗口

| 故障位置 | Checkpoint 可能看到什么 | 工具日志看到什么 | 恢复行为 |
|---|---|---|---|
| 意图提交后、写文件前 | 工具待执行 | prepared + 原文件 | 执行一次写入 |
| 写文件后、成功记账前 | 工具待执行 | started + 目标文件 | 哈希确认已完成，补记结果 |
| 成功记账后、图保存前 | 工具待执行 | succeeded | 复用结果 |
| 图完成后、任务状态提交前 | 已完成的图 | 全部结果已有记录 | 重新验证工作区，补交任务结果 |
| 写入过程中发生外部修改 | 工具待执行 | 保存的意图与文件均不一致 | blocked，保留外部内容 |
| 测试启动后退出、结果未知 | 工具待执行 | started，无成功结果 | blocked，确认后才重试 |

## 并发与状态

同一任务的执行入口持有跨进程文件锁。另一个 worker 拿不到锁就返回冲突，不抢占活跃任务。进程退出后 OS 会释放锁，新服务扫描 `running` 任务，只将已经没有锁持有者的任务标为 `interrupted`。

不同任务使用不同工作区和不同 Checkpoint 数据库；应用数据库使用短事务与 busy timeout。

状态含义：

```text
queued → running → succeeded
                 → failed
                 → interrupted → running
                 → blocked     → running（满足恢复条件或明确允许测试重试）
```

`failed`/`succeeded` 任务不再接受 API 恢复，保留结果用于审计；修改需求时新建任务。

## 完成证据

`unittest` 返回 0 也可能表示“没有发现测试”。因此必须同时满足：

- 退出码为 0，未超时。
- 输出中报告至少执行一条测试。
- 测试前后工作区内容指纹一致。
- 最终提交时的指纹仍与通过测试时相同。

这是对可信 fixture 的工程验证，不能证明恶意代码没有伪造 stdout，也不能取代独立评测环境。

## 有意限制的范围

- 模型只看到本项目的三个受控工具；上游内置文件、Shell、子 Agent 工具不会旁路执行日志。
- 默认上下文管理来自上游，本项目没有声称实现新的压缩算法。
- 没有跨 Session 的自定义长期记忆、分布式 worker、任务取消与容器沙箱。
- 恢复模型消息依赖持久 Checkpoint，恢复外部副作用依赖各工具自己的协议。
- 原子文件替换与哈希对账覆盖进程退出场景，不承诺主机掉电或所有文件系统上的事务语义。

## 推荐阅读顺序

1. `reproduce.py`：先看一个完全没有应用中间件的上游工具循环。
2. `models.py`：理解 fixture 模型只负责决定固定工具调用。
3. `agent.py`：中间件怎样拦截真实图的模型与工具边界。
4. `tools.py`：文件 CAS、意图记录、测试执行与恢复分支。
5. `service.py`：Checkpoint、运行锁、任务状态、完成判定。
6. `evaluation.py`：真实 worker 退出如何验证恢复。

