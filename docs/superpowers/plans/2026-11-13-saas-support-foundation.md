# SaaS Support Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 完成可运行、可回退的技术支持行业化首期。
**Architecture:** 在现有权限检索管线上提供 support_answer_v1 模式；通用实验路径保持独立。结构化状态贯穿 API、会话、前端。
**Tech Stack:** 既有 FastAPI/Pydantic/FAISS/Next.js，无新增运行依赖。
**Spec:** ../specs/2026-11-13-saas-support-design.md

## Global Constraints
- 只在本地功能分支修改，未获本次发布指令不推送/部署。
- 8 秒查询改写超时、最多 2 个澄清问题、公共示范语料显式导入。
- 不读取 .env、不调用生产数据库、邮件或收费模型来运行单元测试。

## Review Focus
- 改写失败、模型坏 JSON、取消/超时，不得返回误导性的成功答案。
- 澄清轮在刷新与继续会话后必须保留。
- 改写不能丢掉当前问题的错误码/版本/配置键。
- 引用只能指向实际装入本轮上下文的片段。
- 原实验路径和旧消息格式必须兼容，所有召回仍执行用户过滤。

## Task 1: 技术支持问答与历史检索
Files: app/llm/support_prompts.py, app/rag/support.py, app/rag/models.py, app/rag/pipeline.py, tests/test_support.py
Interfaces: rewrite_query(llm, question, history) -> RewriteOutcome；parse_support_answer(text) -> SupportReply；RagAnswer 增加可选状态、澄清与改写信息。
- [x] 写行为测试并确认失败：追问送入检索的是改写问题，送入回答的是原问题；错误码丢失/超时回退；状态/引用校验。
- [x] 实现最小支持链路，引用按实际装配上下文截断。
- [x] 运行新测试与原 test_rag_pipeline.py。

## Task 2: API 与会话契约
Files: app/models/qa.py, app/api/v1/qa.py, app/models/session.py, app/services/session_service.py, tests/test_support.py
Interfaces: QARequest 默认支持模板、公开模板 Literal 白名单；SessionMessage 保存 answer_status/clarifying_questions。
- [x] 先以模型白名单/会话澄清字段测试确认契约缺失，再补充 HTTP 422 与澄清往返回归。
- [x] 实现 API 默认、状态消息、历史兼容。
- [x] 运行会话与隔离测试。

## Task 3: 业务页面与示范知识
Files: web/src/components/chat-view.tsx, web/src/lib/api.ts, data/support_corpus/, docs/saas-support/README.md
- [x] 按本地 Next 文档实现示例问题、技术支持说明、状态及澄清展示，旧消息兼容。
- [x] 编写带代码来源的示范资料，不编造已上线功能。
- [x] 运行 tsc、lint、build，浏览器验证若可用。

## Task 4: 评测与交付
Files: data/eval/support_eval_draft.json, scripts/run_support_eval.py, tests/test_support_eval.py, README.md
Interfaces: 离线草稿分 input/expected_output/metadata；--validate-only 无模型/数据库调用；真实模式保存逐题状态/引用/改写/延迟/token 与错误，失败返回非零。
- [x] 写数据验证与评测评分的失败测试。
- [x] 实现命令、少量高信号案例与人工复核说明。
- [x] 完整 pytest、前端检查与 diff 检查，独立审查并修复发现的问题。

## Execution ledger
- 2026-11-13：现有基线 520 passed；在 codex/saas-support-foundation 直接执行，原 .claude/settings.local.json 未跟踪内容保留。
- Ruling: 首期先交付问答/澄清/评测闭环；数据库元数据过滤和混合检索后续评测驱动实施，避免将提示词中的版本规则伪称为硬隔离。

- 最终验证：571 passed（本地 Python 3.13，41.46 秒）；前端 tsc/lint/生产 build 通过；草稿 12 题校验通过；diff --check 通过。
- 本地 Playwright 模拟接口验收：示例填入、澄清、历史刷新、追问、引用定位、新建会话清空；控制台无错误。本地截图 output/playwright/support-history.png，不入库。
- 独立审查后修正：自定义语料登记路径、空上下文停止生成、完整诊断标识保护、输出校验失败标记避免评测误通过、资料不足时有效引用链接保留。复查未发现此前阻塞项遗留。
- 实际验证范围：未导入语料、未调用收费模型/生产数据库/邮件、未做真实模型质量或生产浏览器验收；生产 Python 3.11 仍需 CI 确认。无新增迁移。
- 交付：docs/saas-support/README.md 说明显式导入、专用语料管理账号、对照评测、上线与回退；主 README 标明方向和通用旧指标边界。工作仍在本地分支，未提交/推送/合并/部署。原 .claude/settings.local.json 与并行出现的 docs/interview/ 未修改。

## 后续授权与真实测试（2026-11-13）

用户随后明确要求“在测试环境导入示范资料，运行真实模型评测并人工核对答案”，授权本轮使用本机已配置的真实模型及独立测试数据库；前述不调用收费模型的约束继续适用于单元测试，不限制本次真实评测。未连接生产库、发邮件或上传 Langfuse 数据集。

- [x] 新建独立 PostgreSQL 容器，执行 001–008 迁移，创建专用语料归属账号。
- [x] 导入 20 篇示范资料，专用索引与数据库分块数均 20，自检通过。
- [x] 完成支持/通用模式各 12 题真实评测与 cookie 题 3 次诊断；保留首轮失败。
- [x] 编码助手逐题对照源码与引用，生成完整审阅报告。
- [ ] 真人复核并签核答案；处理报告中的输出契约、状态定义与过度归因问题，再完成独立样本回归。

详见 `docs/saas-support/evaluations/2026-11-13-real-model.md`。测试容器已停止；分支未提交、推送、合并或部署。


## 修复和再次评测授权（2026-11-13）

用户要求修复首轮问题、再次回归并提供本地启动方式。本轮先以失败测试复现空字段误拒及审查问题，再实现最小修复；不改变旧数据集预期，不新增生成重试。

- [x] 非澄清输出只补缺省空数组，保留严格 JSON/类型/状态/引用校验与固定错误码。
- [x] 版本化 v2/v3，明确秘密/越权拒答状态、探测不等于根因、操作不保证修复；旧版本保留。
- [x] 新增不同表述及正常配置/找回规则的对照题；v2 前十题预期在 v3 不变。
- [x] 独立审查两项 P2 已失败复现并修复：非事实状态非法引用统一回退、评测记录有效生成预算。
- [x] 最终完整后端 595 passed；最终 23 题真实模型结构通过，早期失败和诊断均保留在新报告，本轮 87 次执行。
- [x] 整理 Windows 本地启动指南、完整逐题答案与来源。
- [ ] 真人复核与行业质量签核，后续盲测仍需覆盖偶发 JSON/状态波动和不充分引用。

报告：`docs/saas-support/evaluations/2026-11-13-regression.md`。没有连接生产库或改默认索引；尚未提交、推送、合并或部署。历史首轮报告保持原样。
