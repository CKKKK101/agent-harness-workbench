# 已有项目修复与验收工作流

## 有测试的项目

用户选择文件夹或输入公开 GitHub 仓库地址 → 导入不可变文本快照 → 静态发现测试 → 描述 Bug → Agent 读取源码、修改、选择测试调试 → Harness 独立运行全部基线测试 → 对比指纹并给出结果。

本地选择使用浏览器文件夹上传，保留相对目录；API 不接受宿主机路径。GitHub 下载公开仓库默认分支 ZIP，限定 GitHub HTTPS 地址及重定向域名，不调用 git 或执行 hooks。路径穿越、符号链接、大小写重名和超限快照被拒绝。导入仅存储文件，不导入 Python 模块、不运行测试。

发现规则：任意导入目录中的 `test_*.py`、`*_test.py`。识别顶层测试函数、pytest 导入或 conftest 时使用 pytest；否则使用 unittest。此为有限的静态启发式，不支持任意测试框架和自定义命名。模型工具仍只有 `inspect_file`、`replace_text`、`run_tests`，没有新增图节点或 Shell 工具。

## 没有测试的项目

1. 用户明确描述 Bug 与预期行为，最好提供输入、正确输出及边界情况。
2. Agent 仅提出候选测试；也可以手动录入测试 JSON。
3. 页面展示完整候选代码供检查，默认不勾选确认，不运行候选代码，也不创建修复任务。
4. 用户确认后才创建任务，将检查过的测试内容和预期行为冻结。修改预期、描述或测试代码会取消页面确认；服务端候选记录绑定项目、描述和预期，不能跨输入复用。
5. Harness 执行确认后的完整测试基线。任务记录及测试区域显示 `user_confirmed_candidates`，避免将模型自行提出的测试当成独立正确性证明。

语法校验仅检查测试可解析、路径是新测试文件、包含测试函数/方法，不判断测试断言是否正确、是否覆盖需求，也不保证必然被框架收集或执行。执行阶段必须有非零测试数且退出码为 0；全部跳过不算验收成功。可信 conftest 仍能改变收集规则，这不是针对恶意项目的证明系统。

## 接口示例

```json
POST /projects/import
{"label":"calculator","files":{"calculator.py":"def add(a,b): return a-b\n","tests/test_add.py":"from calculator import add\ndef test_add(): assert add(2,3)==5\n"}}

POST /tasks/from-project
{"project_id":"导入返回的id","prompt":"add(2,3)返回-1，预期5，请修复"}
```

没有测试时，先登记模型生成或手动编辑的候选：

```json
POST /projects/{id}/candidate-tests
{"prompt":"add错误执行减法，请修复","expected":"add(2,3)应返回5，包括零和负数也正确相加","files":{"tests/test_add.py":"from calculator import add\ndef test_add(): assert add(2,3)==5\n"}}
```

省略 `files` 时调用配置的模型生成候选，不执行它们。生成可能产生 API 费用。候选生成输入限 80000 UTF-8 字节；更大项目可手工提供候选。

```json
POST /tasks/from-project
{"project_id":"导入id","prompt":"add错误执行减法，请修复","expected":"add(2,3)应返回5，包括零和负数也正确相加","candidate_id":"候选id","confirm_acceptance":true}
```

`candidate_files` 可在同一确认请求中提交用户审阅后的修改版本；服务端重新验证并冻结实际提交内容。`memory_scope` 可选，接口继续兼容现有任务恢复。`GET /tasks/{id}` 的 `acceptance` 包含项目快照摘要、测试路径、框架、预期行为及来源；候选实际代码保存于 `source_files`。

## 范围与边界

- 当前为小型可信 Python 项目执行环境。最多 200 个文件 / 2 MB；单文件 256 KB。公开 ZIP 最大 10 MB，最多 20000 条目录记录。
- 复制 `.py`、`pyproject.toml`、`pytest.ini`、`setup.cfg`、`tox.ini`、`requirements*.txt`、`README.md`；过滤凭据、虚拟环境、依赖目录、构建产物和缓存。JSON/图片/其他测试数据不复制，依赖这些文件的项目需要扩展导入范围后才能使用。私有仓库、子模块、指定分支、非 UTF-8 文件和任意大仓库不支持。
- 使用运行 Harness 的解释器及已安装依赖；不自动执行 pip 或项目启动脚本。`src/` 和项目根目录加入测试导入路径。pytest 禁用外部插件自动加载并清空 addopts；第三方插件、复杂安装布局和项目专用 runner 需单独适配。
- Agent 无权修改测试及测试配置（包括整个 pyproject.toml / setup.cfg）。最终验收核对所有原始测试和配置，显式传递完整文件清单；继承已有进程监督、清理租约、未知结果阻断、指纹与独占工作区契约。
- 仓库未被原地修改，改动留在任务副本中，可查看差异并下载当前文件；没有自动提 PR 或写回原仓库。
- 通过代表选定基线在该环境通过；已有测试可能不覆盖这次 Bug，候选测试可能不充分。人工检查与补充验收仍有必要。测试代码拥有宿主权限，不承诺容器隔离、恶意代码防护或消除 TOCTOU。

## 验证

后端 `tests/test_projects.py` 覆盖导入不执行源码、目录与测试发现、归档与路径限制、完整 pytest 验收覆盖 Agent 部分通过、候选确认门槛、确认过期、候选代码修订和冻结、配置只读及 API 流程。真实测试子进程执行，模型决策和 GitHub 下载使用 Mock。

浏览器 `scripts/test_ui_projects.mjs` 覆盖真实文件夹导入、无测试门槛、候选预览、修改后取消确认、明确确认后的提交、公开仓库控件和移动端布局。候选模型与仓库网络响应使用 Mock，任务提交被拦截以避免真实模型调用；完整执行由后端确定性模型集成测试覆盖。这些不是实际公开仓库的模型修复率实验。
