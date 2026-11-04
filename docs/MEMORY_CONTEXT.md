# 跨任务记忆与上下文管理

实现日期：2026-11-03（Asia/Shanghai）。本项目以一个 task / LangGraph thread 作为一次执行会话；跨会话记忆表示不同 task 在显式指定相同项目标识后共享记录，不是把同一 task 的 Checkpoint 改个名字。

## 使用入口

启动方式不变：`uv run harness serve --port 8000`。在工作台展开「项目记忆」，填写项目标识（例如 `calculator-project`），保存项目约定，再创建任务。项目标识留空时不读取其他任务的记忆。

同一标识下的第二个新任务会重新召回当前有效版本。可以在界面查看、编辑、标记失效和删除。每次编辑都生成新版本，旧版本不会因为新版本被删除而重新成为有效记忆。执行轨迹上方显示本次准备/调用的上下文和记忆版本，演示模型会明确标注。

命令行也可绑定作用域：

```powershell
uv run harness demo --memory-scope calculator-project
uv run harness run --workspace examples/calculator --prompt "修复加法，保留测试" --memory-scope calculator-project
```

第二条使用真实模型，需要原有模型配置；本轮未调用付费模型。命令行不会从未指定的项目召回记忆。

## 结构化长期记忆

应用 SQLite 新增 `task_scopes`、`memories` 和 `context_views`，通过 `CREATE TABLE IF NOT EXISTS` 兼容原数据库。原任务、文件、工具日志与 Checkpoint 不迁移、不删除。

一条记忆包含：项目 scope、key、version、kind、content、status、source_task、文件 SHA256 evidence、创建时间、可选过期时间。内容修订保留历史；当前状态由同一 scope/key 的最大版本决定。

| 类型 | 写入方式 | 作用 |
|---|---|---|
| constraint | 用户在页面/API 显式保存 | 项目惯例，召回时优先考虑；仍低于当前任务要求 |
| fact | 用户通过 API 保存，可绑定源任务文件哈希 | 有依据的文件事实或用户备注；没有证据的备注不等于系统验证事实 |
| experience | Harness 最终验收通过后自动生成，或引用成功源任务写入 | 记录修改过哪些文件和历史验收结果，不能替代新任务验收 |

没有让 LLM 将自己的回答直接写成事实。自动经验由真实工具日志和服务层成功状态生成，不保存密钥或完整源码文本，默认 30 天过期。其他手工记录可指定 TTL；未指定时不会自动过期。

### 召回与失效

1. 只查询任务绑定的 scope 的最新版本；默认最多 3 条。
2. 排除 superseded、invalid、deleted、已过期记录。
3. 带文件证据的条目，逐路径重新校验目标工作区的 SHA256。不同分支文件不匹配时标为 `stale_for_workspace`，不全局作废该记录。
4. 普通事实/经验使用英文词项和中文二元字组匹配相关性；项目约定优先。第一版没有向量召回或长期记忆质量基准。
5. 上下文预算不足时丢弃整条低优先级记忆并记录 `context_budget`，不截断后冒充完整事实。

更新、失效和删除使用 `BEGIN IMMEDIATE` 与 `expected_version`：并发写入只有持有最新版本的一方成功，其余返回 409，避免无提示覆盖。失效/删除都会创建新版本；更新已有 key 必须明确提交预期版本。

每次模型调用都重新读取记忆状态，不直接重放上次召回列表。删除前保存的上下文缓存也不能绕过版本检查。不过删除不能撤回已经在进行的模型请求，也不清除历史版本、上下文审计记录或模型以前复述过的内容。这是后续召回控制，不是合规数据擦除接口。

## Key Fact Snapshot 与分层预算

`BudgetContextMiddleware` 通过 Deep Agents 0.7.32 支持的同名替换机制接管 `SummarizationMiddleware`，避免默认摘要与应用压缩同时改写历史。工具白名单和原有 JournalMiddleware 保留。

每次调用前构建事实快照，保存：

- 完整任务要求；不做摘要、不截断。
- 原始测试文件哈希、当前工作区指纹。
- 工具日志中的最近文件观察及其哈希、最近测试结果、未确定结果的调用。
- 各工具调用计数和“仍需 Harness 独立最终验收”的完成规则。

其中 `last_observed_files` 是工具曾返回的观察，不承诺在任意外部并发写入后仍然新鲜；执行修改时仍须经过原有哈希检查。工作区继续要求独占。

输入超过预算时，按以下优先级组装模型输入：

1. 原系统提示、工具 schema、完整任务要求及额外用户要求、执行事实快照。
2. 最近的完整工具轮次，至少保留最新一轮；一个 assistant 的多个 tool_calls 与其全部 ToolMessage 不能拆开。
3. 可容纳的项目记忆，整条加入或整条排除。
4. 确定性历史摘要，记录省略轮数、工具分布，并提示需要时重新读文件。

“最近轮次”上限默认 2；较早轮次只有在预算允许时保留。历史摘要没有另调 LLM，也不会生成新的事实。必要事实或最新完整轮次无法放入预算时返回阻断状态，要求增大预算或缩小任务，而不是静默丢掉要求继续执行。

### 配置

| 环境变量 | 默认值 | 含义 |
|---|---:|---|
| WORKBENCH_CONTEXT_ENABLED | true | 启用应用投影与记忆注入；false 恢复框架默认行为 |
| WORKBENCH_CONTEXT_MAX_TOKENS | 32768 | 总预算的估算单位 |
| WORKBENCH_CONTEXT_OUTPUT_RESERVE | 2048 | 输出预留，同时限制本次模型 max_tokens |
| WORKBENCH_CONTEXT_MEMORY_TOKENS | 1800 | 记忆最多占用的估算预算 |
| WORKBENCH_CONTEXT_RECENT_TURNS | 2 | 尝试保留的最近完整轮次数 |

计数使用 JSON 序列化后的 UTF-8 字节数并加 framing 余量，涵盖系统提示、工具定义与消息。它是保守估算，**不是供应商 tokenizer、实际计费 Token 或所有模型的通用上界**。本轮未实测真实模型 Token/费用下降，不把估算压缩比例写成真实 Token 节省。

## 压缩提交与恢复一致性

压缩的是**送给模型的输入视图**。原图状态和完整消息仍在 Checkpoint 中，因此减少模型输入不等于减少 Checkpoint 大小；也没有承诺保留所有历史推理细节。

视图以原始消息、系统提示、工具 schema、事实、记忆版本与策略共同计算输入摘要。SQLite 事务一次提交视图、校验和及 `context.prepared` 事件。相同来源输入可复用同一个视图；损坏或不一致的缓存阻断调用。模型返回后才追加 `context.applied`，准备完成不等于模型已经使用，也不等于任务成功。

模型调用失败或 Worker 退出后，恢复者仍从原 Checkpoint 和工具日志重建，再检查当前工作区及记忆状态。图 Checkpoint 与应用 SQLite 之间没有新增跨库全局事务，不声称实现两者的原子提交。

视图幂等不等于模型 API 恰好调用一次：模型返回后、图保存前退出时仍可能重新调用模型。保护重点是工具副作用、输入来源及验收，不把缓存视图当成已完成的模型结果。

故障注入点：`before_context_commit`、`after_context_commit`。测试在独立进程执行 `os._exit(86)`，验证提交前没有半条视图、提交后可一致复用。图集成测试实际触发多轮压缩，检查模型收到事实快照、原始 Checkpoint 仍保留全部读取轮次，并最终通过原有测试验收。

## 接口

| 接口 | 用途 |
|---|---|
| POST /tasks、POST /tasks/demo | 增加可选 memory_scope；旧请求仍有效 |
| GET /memory/{scope}?history=false | 当前各 key 的最新版本，或完整历史 |
| PUT /memory/{scope} | 创建/更新，提交 key、content、kind 和可选 expected_version / source_task / evidence / expires_in_seconds |
| POST /memory/{scope}/invalidate | 提交 key、expected_version，标为失效 |
| DELETE /memory/{scope}/{key}?expected_version=N | 创建删除标记，后续不再召回 |
| POST /memory/{scope}/recall | 提交 task_id，预览对该工作区的召回和排除原因 |
| GET /tasks/{id}/context | 检查上下文视图、事实快照、引用版本与估算预算 |

这是原有单用户本地服务的接口，不提供多租户身份权限或不可信代码沙箱。历史视图包含任务内容，只应在本机调试环境查看。

## 验证范围

`tests/test_memory.py` 覆盖跨任务/重启召回、作用域隔离、版本 CAS、TTL、证据变化、删除与失效不复活旧版本、并发写入、旧数据库兼容以及 API。

`tests/test_context.py` 覆盖完整用户要求、最近完整工具轮次、多工具调用配对、系统和 schema 预算、预算不足阻断、快照幂等与损坏、删除记忆后的重新投影、真实进程退出，以及真实图压缩与完整 Checkpoint 恢复读取。

`scripts/test_ui_memory.mjs` 覆盖页面写入/编辑、两个新任务召回同一版本、失效后排除、390px 布局和浏览器错误。演示运行的是确定性模型，不冒充真实 LLM 记忆推理效果。

当前保证的是受控执行条件下的记录、过滤、协议和恢复契约；未验证任意模型的语义质量、跨仓库知识迁移、真实 Token 成本收益或抗提示注入的完整性。
