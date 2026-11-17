# 软件与 SaaS 技术支持知识助手

面向技术支持、实施人员和产品使用者，解决“查产品文档、问部署步骤、按证据排障、承接追问”的需求。本期用 RAG Knowledge Base 自身作示范产品。没有接入真实厂商工单，也不承诺自动操作服务器或自动解决故障。

## 本期行为与边界

| 模块 | 本期实现 | 后续范围 |
|---|---|---|
| 提示词 | 默认 `support_answer_v3`，保留 v1/v2；明确拒答状态、待验证原因与修复结果边界 | 真人复核与盲测 |
| 多轮检索 | 有历史时一次独立查询改写，8 秒超时/非法输出/丢失部分字面标识时回退；回答仍接收原问题 | 指代语义评测与更完整实体校验 |
| 回答状态 | 已回答、部分可答、待补充信息、资料不足、资料冲突；澄清 1～2 问 | 人工接管和支持工单 |
| 引用 | 事实状态要求至少一个实际上下文的有效编号；坏 JSON、缺失/非法编号降级 | 逐结论证据支持度评测 |
| 权限 | 继续执行本人文档 + 共享资料，沿用文档 ID 过滤 | 产品/版本硬过滤、企业组织与成员权限 |
| 检索 | 现有 FAISS 语义检索 | 先评测错误码召回，再考虑关键词混合检索与重排 |
| 页面/会话 | 示例问题填入输入框；状态、澄清及引用可刷新查看并继续对话 | 用户反馈与人工处理摘要 |
| 评测 | 12 题可审阅草稿、逐题 JSONL、结构检查、原通用管线对照 | 人工复核标签、真实效果与成本基线 |

提示词无法替代权限过滤，也无法保证引用在语义上支持结论。当前 MCP stdio 仍属于可信本机操作者入口，未继承网页用户权限。

## 代码入口

- `app/llm/support_prompts.py`：版本化支持回答与改写规则。
- `app/rag/support.py`、`app/rag/pipeline.py`：改写预算、结构校验与引用映射。
- `app/models/qa.py`：网页默认支持模式，公开接口只接受支持模板与 `rag_context_cited`。
- `app/services/session_service.py`：状态和澄清保存进现有 JSONB，兼容旧消息，无新增数据库迁移。
- `web/src/components/chat-view.tsx`：支持场景入口和回答展示。

线上 Agentic 管线的接入不在本期范围。`RetrievalConfig` 默认仍为通用模板，历史离线实验不因网页默认改变而自动切换。

## 示范知识导入

`data/support_corpus/` 有 20 篇 Markdown 草稿，涵盖上传、索引、Docker 部署、502、认证、邮件、账号恢复、会话与引用。每篇标注产品、来源代码、日期与适用快照；并不代表正式产品版本手册。后续修改代码时应复核相应资料。

导入会把这些文件作为公共资料登记到演示用户；目录只放可公开文档。构建镜像不会自动导入。请先完成原 README 的数据库、账号、模型环境配置，再从仓库根目录手动运行。入库账号由 `DEFAULT_USERNAME` 决定（默认 `demo_user`），必须已存在；新数据库先注册并验证一个专用语料管理账号，配置该用户名后再构建。迁移不会自动创建演示账号。

```powershell
# 本机：会写数据库与索引，并产生向量 API 用量
.\RAG_venv\Scripts\python.exe scripts/build_index.py --corpus data/support_corpus --verify
```

它会入库指定语料，并从数据库中已有分块重建当前策略索引，包含用户上传资料。不会清空原文档表；重复导入会替换该语料当前策略的分块，因此旧会话中的块 ID 可能失效。需要保留现有数据库和 `data/index` 备份，避免并发构建；完成后重启后端，使内存索引更新。`--verify` 只比较向量数和数据库分块数，不代表问答质量通过。

ECS 在新代码和镜像完成部署后，使用运行中 backend 的镜像推导 tag，避免手填占位符：

```bash
cd /opt/RAG_app/RAG_project
export IMAGE_PREFIX="$(docker inspect -f '{{.Config.Image}}' rag_project-backend-1 | sed 's@/backend:[^:]*$@@')"
export IMAGE_TAG="$(docker inspect -f '{{.Config.Image}}' rag_project-backend-1 | awk -F: '{print $NF}')"
test -n "$IMAGE_TAG" && test -d data/support_corpus && test -f scripts/build_index.py || exit 1
# scripts 不在后端镜像内，显式只读挂载；data 已由生产 compose 挂载
docker compose -f docker-compose.prod.yml run --rm \
  -v "$PWD/scripts:/app/scripts:ro" backend \
  python scripts/build_index.py --corpus data/support_corpus --verify && \
docker compose -f docker-compose.prod.yml restart backend
```

仓库脚本必须与该镜像代码一致；生产执行需单独安排，本次开发未执行任何生产导入。

## 评测与人工复核

先验证草稿结构与引用文件是否存在，不会调用模型/数据库：

```powershell
.\RAG_venv\Scripts\python.exe scripts/run_support_eval.py --validate-only
```

真实模式会调用向量和生成 API。用专门评测环境和账号 UUID；不要将生产私有索引作为演示数据。下面的 UUID 需在命令执行前替换为该账号的真实 ID：

```powershell
$evalUserId = "评测账号的真实 UUID"
.\RAG_venv\Scripts\python.exe scripts/run_support_eval.py --viewer-user-id $evalUserId --output reports/support-v3.jsonl
.\RAG_venv\Scripts\python.exe scripts/run_support_eval.py --viewer-user-id $evalUserId --prompt rag_context_cited --output reports/support-baseline.jsonl
```

输出文件禁止覆盖。支持模式目前默认 v3，可显式选择 v1/v2 作对照；同一解析器仍执行严格校验，仅补非澄清状态遗漏的空问题数组。报告记录问题/历史、预期与人工复核标准、检索/引用/状态、改写、耗时和 token，并保存配置模型、改写模板版本、索引及元数据 SHA-256。结构检查包括输出校验失败标记、预期状态、澄清数、引用存在性与编号；参考文档召回单独报告。所有 `semantic_review` 均为 `pending`，结构通过不等于答案正确，不得将其宣传成行业准确率。当前 12 题是首批草稿，应逐题审核并扩充产品、错误码、指代、版本冲突、资料缺失与注入案例。

人工重点复核：结论是否被引文支持；追问是否保持原意与字面错误码；版本是否适用；有没有把猜测写成确定根因；是否优先询问关键缺失信息；是否泄露他人资料或索取秘密。越权行为另用确定性 HTTP/隔离测试验收，不能靠模型拒答代替。

Langfuse 沿用已有接入。本期不升级 SDK、不上传或更改在线数据集；本地模板版本和评测结果独立保存。真实模型首轮结果见[评测与逐题核对报告](evaluations/2026-11-13-real-model.md)：已记录样本级时延与 token，货币成本和真人签核尚未完成。

## 上线验收与回退

1. 本地后端全量测试、前端类型/lint/构建及评测草稿检查通过后，再提交和手动部署；本期无需新增迁移。
2. 确认镜像和仓库脚本对应，同步公开语料、备份后显式导入并重启后端。
3. 浏览器以真实账号提问 PDF 无法检索、Docker 502，检查引用可定位；继续问“如何看它的日志”，验证检索改写与原问题分别记录。
4. 提问信息不全的问题，确认澄清最多 2 条；刷新会话仍能看到澄清，再补充环境继续回答。资料无答案时应拒答，未知版本不应编造差异。
5. 用两个用户检验私有文档/会话隔离和公共资料可见；检查旧会话显示正常。
6. 记录实际 token、改写额外延迟、格式降级和人工复核结果后再判断是否扩大使用。

单次接口可显式传 `prompt_name: "rag_context_cited"` 对照。网页没有模板切换开关；整体行为回退需恢复此前稳定的前后端镜像，不要撤销账号相关数据库迁移。支持语料不会随旧镜像恢复而自动撤销；需要回滚知识内容时使用事先保存的数据库/索引备份，并重新验证两者一致。


## 本地验证记录（2026-11-13）

- 后端完整回归：571 passed，使用本地 Python 3.13；生产 Python 3.11 仍需 CI 验证。
- 前端：`npx tsc --noEmit`、`npm run lint`、`npm run build` 均通过。
- 草稿：`--validate-only` 通过 12 题；未调用模型或数据库。
- 本地浏览器配合模拟 API：示例填入、澄清展示、历史刷新、继续提问、引用定位、历史页新建会话清空均验证；控制台无错误。截图：`output/playwright/support-history.png`（本地忽略产物，不入库）。该验证只覆盖界面，不替代真实数据库、模型或生产验收。
- 独立审查后增加路径/版本/错误标识保护，以及输出校验失败标记；格式降级不能被负样本评测算作结构通过。
- 上述开发阶段未执行真实模型/数据库；随后按用户授权完成独立测试环境导入与真实模型评测，结果见下一节。未执行生产验收；分支尚未提交、推送或部署。

## 独立测试环境真实评测（2026-11-13）

已将 20 篇示范资料导入独立 PostgreSQL 测试库并重建专用索引，数量自检 20/20。支持模式和通用对照各完成 12 题，运行异常均为 0；结构检查分别通过 9/12 和 11/12，不能等同于语义正确率。另对 cookie 题补跑三次，复现必填字段缺失导致的降级。

[完整报告](evaluations/2026-11-13-real-model.md)保留题目、原答案、引用证据、对照答案、核对意见和待真人签核栏。发现输出契约不稳定、两题状态不符以及一条 502 过度归因，因此本批尚不能作为行业质量验收通过。首轮结果未被补跑覆盖；未修改提示词或评分标签。测试容器已停止，数据与索引保留；本轮未写入生产库、默认索引或在线 Langfuse 数据集。


## 缺陷修复与回归（2026-11-13）

原缺陷回归已完成：后端 **595 passed**；最终原 12 题与新增 11 题真实模型结构检查均通过、运行异常为 0。v2/v3 中间批次及三个原文诊断结果全部保留，本轮共 87 次题目执行；早期出现过 1 条 partial 状态偏差和 1 条 invalid_json，不能用最后一批结果抹掉波动。模型遗漏非澄清空数组可确定性补全，其他非法输出仍安全降级；审查补充了所有支持状态非法引用统一回退的测试。

[回归报告](evaluations/2026-11-13-regression.md)包含全部批次指标、最终逐题原答案、实际引用、编码助手意见与真人确认栏。语义核对仍发现经验性表述、无关分支和导出能力暗示，尚不能宣称完整行业质量验收通过。代码仍在本地分支，无新增迁移；生产 Python 3.11 和线上验收待后续 CI/部署安排。

本机启动命令与首次注册/索引说明见 [Windows 本地开发指南](local-development.md)。日常开发使用本地数据库及默认索引，不将独立共享评测索引当作生产私有库。
