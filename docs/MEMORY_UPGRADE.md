# 跨 Session 记忆：结构化经验与混合召回

日期：2026-11-04。这里的 Session 对应 task：新建任务可在相同显式 `memory_scope` 下使用历史有效记录。Checkpoint 仍只负责同一个任务的执行恢复。

## 运行链路

```text
用户保存约定 / Harness 独立验收通过
  → 原子保存记忆版本、来源和结构化详情
新任务的每次模型调用
  → 同 scope 最新版本 → 状态、TTL 和证据过滤
  → 相同经验去重 → BM25 + 本地 BGE 向量 → RRF → Top 3
  → 再查版本、TTL 和证据 → 上下文预算 → 作为参考注入
  → Agent 读当前代码并修复 → Harness 重新验收
```

## 写入什么

继续使用 `constraint`、`fact`、`experience` 三类；修改、失效和删除继续通过版本 CAS。新增 `memory_details` 和 `memory_vectors`，没有改变原 `memories` 的 11 列结构，因此旧库、原 API 及历史版本保持兼容。

自动修复经验来自实际需求、原始/最终文件差异和独立 `harness_acceptance`，包含：

- `problem`：用户要求，不冒充已查明的根因。
- `observed_remedy` / `changes`：实际新增/删除片段、文件、函数/类名、修改前后哈希。
- `verification`：来源任务、非零测试数量、验收文件清单、指纹和验收来源。
- `applicability`：同项目 Python 经验，仅供参考，必须重新读取当前代码并验收。
- `root_cause=not_inferred`：没有调用 LLM 编造因果解释，也没有自动抽取经人工确认的根因。

只有任务已成功、独立验收已通过且其指纹仍对应当前工作区时才生成。无最终净修改不创建经验；同任务重复记录和删除后的自动重建不会复活旧 key。默认 30 天过期。记录包含少量经规则脱敏的差异片段；这是尽力脱敏，不保证识别所有秘密格式，应仅使用可信项目。

相同问题与相同最终修改生成稳定签名：保留每个来源任务的审计记录，召回只占一个名额。这是精确经验去重，不是任意语义相似记忆自动合并。

## 文件事实与历史经验分开处理

文件事实绑定 SHA256，目标文件不一致就排除，不能作为当前事实注入。

系统生成的结构化修复经验记录的是历史结果。来源任务及其验收记录仍须有效；新工作区文件变化或路径不存在时，经验可作为 `reference_only` 返回，并标注 `changed_or_missing_files`，不能声称当前问题根因已被证明。模型提示词要求先查当前源码再使用，最终验收继续由 Harness 决定。

旧版经验和手工备注若绑定文件证据，继续遵循原来的严格校验规则；只有系统生成且关联验收依据的结构化经验采用上述参考策略。scope 是单用户本地项目分组，没有多租户身份权限或跨项目经验共享。

## 检索、缓存与撤销

BM25 使用英文词项和中文二元字组，正 IDF，零匹配不贡献分数。向量使用本地 `BAAI/bge-small-zh-v1.5`，归一化余弦排序，默认门槛 0.5。两路各取最多 20 条，以 `1/(60+rank)` 融合，约定优先，默认总共 3 条；召回不足允许为空。阈值是当前小语料策略，不是通用最优值。

ONNX 放在隔离 Python 子进程，主服务不导入原生推理库。显式准备模型后才启用向量；缺模型、超时、进程失败或向量损坏时返回 BM25，响应说明降级原因，不阻塞服务启动。推理默认 12 秒超时，无常驻模型服务；首次缓存未命中有进程启动及模型加载成本。

向量缓存按“准备时模型权重/分词文件指纹 + 文本 SHA256”隔离，缓存不保存召回资格。排序后再次读取最新记忆版本并检查 TTL/证据，避免推理期间删除、替代或失效的旧候选回流。不能撤回已经发送的请求；最终复核后发生的撤销作用于后续召回，不能宣称任意时刻即时取消在途请求。

模型准备文件位于数据目录 `memory-model.json`，仅保存本机解释器、缓存位置和模型身份；不上传。更换权重或分词文件后需重新准备。缓存命中不重新扫描权重文件；不承诺对外部并发修改模型目录的供应链隔离。历史记录和旧向量仍保留，删除是后续召回控制，不是数据擦除。

## 开启本地向量

Windows 独立环境示例，不改变 Harness 现有解释器：

```powershell
uv venv .workbench/memory-env --python 3.12 --managed-python
uv pip install --python .workbench/memory-env/Scripts/python.exe -r requirements-memory.txt
.venv/Scripts/python.exe -m harness_workbench.memory_search --python .workbench/memory-env/Scripts/python.exe --cache-dir .workbench/memory-models --download
```

只有显式 `--download` 允许下载；已有缓存时去掉它。数据目录默认 `.workbench`，自定义启动目录必须给准备命令同样的 `--data-dir`。已安装 FastEmbed 的外部 Python 3.12 环境也可通过 `--python` 复用。模型目录、运行数据和向量不提交 Git。

`GET /memory-status` 只返回准备状态和检索策略，不启动模型，`model_checked=false`。准备状态不等于实际推理可用。

`POST /memory/{scope}/recall` 在原 `task_id` 基础上增加可选 `query`、`mode=bm25|dense|hybrid`、`top_k=1..10`；向量不可用时包括 dense 调试模式也明确降级为 BM25。结果包含分数、使用策略、证据状态和排除原因。界面在「项目记忆」显示结构化经验与「召回预览」。

## 实际验证与可说的指标

本轮 Windows **146 项后端测试、25 项浏览器检查、5/5 原恢复场景通过**。新增 18 项后端回归包括跨任务重启后的真实图输入注入、严格事实与经验参考区分、验收来源核对、精确去重、语义召回协议、推理期间撤销/替代、向量缓存不复活删除记录、故障降级、脱敏和调试 API。

真实 BGE 检索使用 8 条手工知识备注、24 条自建查询，开发/留出各 12 条（各 8 正例、4 无关问题）。语料与标签均由开发者整理，不是第三方盲测，也不是自动生成经验质量评测。没有使用留出集调阈值。结果：

| 方法 | 开发 Hit@3 | 留出 Hit@3 | 留出无关问题拒绝 |
|---|---|---|---|
| BM25 | 8/8 | 5/8（62.5%） | 4/4 |
| 向量 | 8/8 | 4/8（50%） | 4/4 |
| 混合 | 8/8 | 6/8（75%） | 4/4 |

混合在这 8 条留出正例上比 BM25 多命中 1 条，即 12.5 个百分点。纯向量并未全面优于关键词，失败查询保留在 [原始报告](memory-retrieval-evaluation.json)。ranking 延迟不含 embedding；报告单独保存整批向量计算耗时。尚未测量真实 LLM 的修复率、工具调用节省或计费 Token 变化，不能将检索数字写成任务成功率提升。

复现：

```powershell
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe scripts/evaluate_memory.py --data-dir .workbench
.venv/Scripts/python.exe scripts/run_ui_checks.py
```

源码入口：`memory.py` 管生命周期，`repair_memory.py` 生成客观经验卡，`memory_recall.py` 过滤和复核，`memory_search.py` 排名及向量缓存，`memory_embedding_worker.py` 隔离原生推理。原始测试与评测任务仍为可信代码，不提供 OS 沙箱。
