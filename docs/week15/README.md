# 第 15 周：RAG 项目收尾（前端 + 部署 + 文档）

2026.10.19-10.25 ｜ 把 Agentic RAG 完整版上线，MCP Server 开源，产出面试与实习材料

## 一、本周目标

- 前端从 `static/index.html` 简易版迁移到 Next.js，完成登录、文档列表、会话历史、删除文档
- CI/CD（GitHub Actions）自动跑测试并部署
- Agentic RAG 完整版上线，拿到线上 URL
- MCP Server 独立发布到 GitHub
- 完整 README、3 分钟演示视频、面试讲稿、实习申请材料包

## 二、任务清单

### 1. 前端（Next.js）

- [x] 初始化 Next.js 项目（`web/`，`src/` 目录，`output: "standalone"`）
- [x] 问答页骨架：提问、展示答案、引用来源、LangFuse Trace 链接
- [x] 文档列表页骨架：列表、删除
- [ ] 登录页（后端暂无鉴权接口，待定）
- [ ] 会话历史页（后端 `sessions` 表已存在，待补接口）
- [x] 对接后端 API：`next.config.ts` 将 `/api/v1/*` 代理到 `BACKEND_URL`，同源调用，无需 CORS
- [x] 引用点击后定位原文片段：点击引用展示被引用块及前后文，目标块高亮并滚动到可见区域（`70919df`）
- [x] Next.js 升级至 16.4.3，修复 16.0.0–16.4.0 的 critical 漏洞（use cache RCE、SVG 图片优化 RCE）

### 2. 后端与部署

- [ ] **（紧急）访问控制止血**：`deploy/nginx/rag.conf` 已加 basic auth，服务器需生成 `/etc/nginx/.htpasswd` 并 reload nginx。上线前站点无鉴权，`DELETE /api/v1/documents/{id}` 对公网开放
- [x] 会话历史后端：`SessionRepository` / `SessionService`，接口 `GET/POST/DELETE /api/v1/sessions`，`/qa/ask` 支持 `session_id`，助手消息保存完整引用（含 `chunk_id` 与原文），所有查询带 `user_id`。本地测试 391 passed，尚未部署，真实 PostgreSQL 上的 jsonb 追加需在服务器上做一次端到端验证
- [x] 会话历史前端：左侧栏（会话历史、文档列表、新建会话、可收起，底部用户信息占位），右侧聊天区（底部输入框，Enter 发送，可继续历史会话提问，原文定位黑底白字）。本地 `tsc`、lint、生产构建通过，页面 SSR 返回 200；交互部分待浏览器验证（见验证记录）
- [x] 文档区上传入口：侧边栏「＋ 上传」，调用 `POST /api/v1/upload`，PDF/MD/TXT 上传后自动解析并入索引
- [x] 修复「新建会话」失效：首次提问后不再改地址栏（`replaceState` 与 Next 路由冲突，导致 `<Link href="/">` 无操作，历史会话页上的导航也被取消）；「新建会话」改为 `router.push("/")` + 聊天区重新挂载，当前会话由上下文高亮。代价：刷新页面后回到空白新会话，会话可从侧边栏打开
- [x] 多轮上下文：`/qa/ask` 带 `session_id` 时，服务端取该会话最近 `CHAT_HISTORY_TURNS`（默认 5）轮作为 LLM 历史；被拒答的轮次不计入；检索仍只用本轮问题（追问如「它是什么意思」可能检索不到，待做查询改写）
- [x] 单用户登录（代码完成，待部署）：`/api/v1/auth/login|logout|me`，HMAC 签名的 httpOnly cookie（7 天），`require_user` 守住 upload/documents/qa/sessions，仅 `DEFAULT_USERNAME` 可登录，失败 5 次/15 分钟限流；前端 `proxy.ts` 乐观跳转 + AppShell 调用 `/auth/me` 处理失效；`scripts/set_password.py` 交互设密码。测试 427 passed。部署步骤见下方「单用户登录上线清单」
- [x] 找回密码（邮箱验证码）：`POST /auth/password/forgot`、`POST /auth/password/reset`；验证码 6 位、10 分钟有效、错误 5 次作废，数据库只存 HMAC 摘要（迁移 008）。前端 `/forgot`，登录页有入口。代码完成，待部署验证
- [x] 注销账号（邮箱验证码）：`POST /auth/account/delete-code`、`POST /auth/account/delete`，需登录；事务内级联删除用户、文档与会话，提交后移除向量索引、物理文件与缓存。持有共享语料的账号（`demo_user`）返回 409 拒绝注销。前端 `/account`，侧边栏有入口。代码完成，待部署验证
- [ ] 确认后端接口清单，补齐删除文档/会话历史接口
- [ ] `docker-compose.yml` 补充 MCP 相关配置（如需要）
- [ ] 线上环境变量与密钥管理（`.env.example` 同步更新）
- [x] Dockerfile（后端）与 `web/Dockerfile`（前端，standalone 构建）
- [x] `docker-compose.prod.yml`：postgres + redis + backend + web，端口仅绑定 127.0.0.1
- [x] `.github/workflows/deploy.yml`：手动触发（`workflow_dispatch`），依次执行 test → build → deploy。build 推送镜像到阿里云 ACR 公网地址，ECS 上的自托管 Runner 从 ACR VPC 内网地址拉取并 `up -d`
- [x] 服务器初始化：阿里云 ECS（华东1，Ubuntu 26.04，2C2G）安装 Docker，仓库位于 `/opt/rag-kb`，`.env` 放在仓库根目录
- [x] Nginx 反向代理与 HTTPS：配置见 `deploy/nginx/rag.conf`，证书由 acme.sh 通过阿里云 DNS（DNS-01）签发并自动续期
- [x] 线上 URL 可访问：https://suming.work
- [x] 线上索引构建：`build_index.py` 入库 `data/corpus/` 6 篇语料，`splitter` 策略 33 条向量
- [x] `seed.sql` 移出生产初始化目录（现为 `scripts/dev/seed.sql`，仅新环境手动执行）；`test_user` 待在生产库删除，`demo_user` 保留但更换密码哈希（登录功能上线前完成）
- [ ] 清理 ECS 上 GHCR 的残留登录凭据（`docker logout ghcr.io`，检查 `config.json`）

### 3. CI/CD

- [x] `.github/workflows/ci.yml`：仅 `pull_request` 触发，运行 `pytest`
- [x] `.github/workflows/deploy.yml`：`test` job 作为部署门禁，测试不通过则不构建、不部署
- [x] 所需 Secrets（环境 `production`，build 与 deploy 两个 job 都需声明该环境）：`DEPLOY_DIR`（`/opt/rag-kb`）、`ACR_REGISTRY`、`ACR_IMAGE_PREFIX`（公网）、`ACR_REGISTRY_VPC`、`ACR_PULL_PREFIX`（内网）、`ACR_USERNAME`、`ACR_PASSWORD`。SSH 相关的 `DEPLOY_HOST` / `DEPLOY_USER` / `DEPLOY_SSH_KEY` 与 GHCR 相关的 `GHCR_USER` / `GHCR_TOKEN` 已不再使用，已删除
- [x] Secrets 已配置到 GitHub
- [x] 自托管 Runner：ECS 上以专用用户 `gh-runner` 运行，label `rag-prod`，名称 `rag-ecs`
- [x] 通过 Actions 完整跑通一次 `Build and deploy`（`eeaa148`，test → build → deploy 全部成功）
- [x] 部署 `sha-eeaa148` 后，线上 `web` 与 `backend` 容器均从 ACR 内网地址拉取并运行

### 4. MCP Server 开源

- 独立仓库：<https://github.com/KaiHangJia789/rag-mcp-server>（链接已登记；以下三项在远程仓库核对后再勾选）

- [ ] 拆出独立目录或仓库（当前在 `app/mcp_server/`）
- [ ] README：安装、Claude Desktop 配置、两个 Tool 的示例、截图
- [ ] 发布到 GitHub，写明与主仓库的关系

### 5. 完整 README（主仓库）

- [x] 项目背景、功能（根目录 `README.md`）
- [x] 架构图（线上请求路径 + Agentic 链路，Agentic 部分与 `docs/week13/graph_agentic.md` 一致）
- [x] 技术栈
- [x] 部署方法（摘要 + 环境变量表，完整步骤链接到本文档）
- [x] 指标：引用 `docs/week10/strategy_comparison.md` 与 `docs/week13/ab_report.md` 的数据
- [x] 失败案例：误拒翻倍、top1 未命中、ReAct 引用为 0、计算器资源耗尽
- [x] 已知问题（待提交后在 GitHub 上核对链接与渲染）

### 6. 演示与面试材料

- [ ] 3 分钟演示视频（含 LangFuse Trace 展示 Agent 决策过程）
- [ ] 面试讲稿：1 分钟版
- [ ] 面试讲稿：3 分钟版
- [ ] 实习简历
- [ ] 作品集链接汇总
- [ ] 1 分钟自我介绍

### 7. 每周固定动作

- [ ] 代码提交 ≥ 5 次，至少 1 次有明确功能增量
- [ ] 刷题/复习 ≥ 3 次，每次 45-90 分钟
- [ ] 实习投递：本周起每周 5-8 个（第 16 周前可先行开始）
- [ ] 项目周报

## 三、验收产出对照

| 计划要求 | 状态 | 链接 / 备注 |
|---|---|---|
| RAG 项目 GitHub 完整版 | 待完成 | |
| 线上 URL | 已完成 | https://suming.work |
| 演示视频 | 待完成 | |
| MCP Server 开源仓库 | 待完成 | |
| LangFuse Dashboard 公开截图 | 待完成 | |
| Next.js 前端上线 | 部分完成 | 文档列表、问答、引用定位已上线（`sha-eeaa148`）；登录与会话历史未做 |
| 实习申请材料包 | 待完成 | |

## 四、验证记录

> 每项验证填写：日期、命令或操作、结果、截图路径。

- 全量测试：2026-10-12 本地 `pytest -q`，368 passed
- CI 首次绿灯：2026-10-25 `deploy.yml` 的 `test` job 在 GitHub 上通过（随 `sha-eeaa148` 部署运行）
- 线上 URL 访问：2026-10-23 `curl -sI https://suming.work` → `HTTP/2 200`；浏览器可打开文档列表与问答页
- 线上问答：2026-10-23 提问「什么是 chunk 切分」，回答引用 `03_chunking_parsing.md`，附 LangFuse Trace 链接
- 线上索引：2026-10-23 `build_index.py --verify` → `splitter DB=33 索引=33 ✓`
- 线上部署：2026-10-25 Actions 手动运行 `Build and deploy`，`sha-eeaa148`；服务器 `docker ps` 显示 `web`、`backend` 从 `<ACR_VPC_REGISTRY>/<NAMESPACE>/` 拉取并运行，`postgres`、`redis` 健康
- 线上引用定位：2026-10-26 浏览器提问后点击引用，原文定位面板展示被引用块及前后文，目标块高亮；再次提问后旧面板清除
- HTTPS 证书：acme.sh DNS-01 签发（ZeroSSL，到期 2027-01-21），计划 2027-01-08 自动续期；续期后自动 `systemctl reload nginx`。旧的 certbot 定时器已禁用
- MCP Server 在 Claude Desktop 中调用：

## 五、已知限制

- **注册与邮箱验证上线清单**（分支 `feat/register-verify`，基于 `feat/user-isolation`；两者都未合并，合并顺序：隔离 → 注册 → 部署）：
  1. 服务器 `.env` 增加以下变量（名称如下，值不要写进仓库或发到聊天里）：
     `MAIL_BACKEND=directmail`、`ALIYUN_ACCESS_KEY_ID`、`ALIYUN_ACCESS_KEY_SECRET`、`ALIYUN_DM_ACCOUNT_NAME=noreply@mail.suming.work`、`PUBLIC_BASE_URL=https://suming.work`。
     `ALIYUN_DM_ENDPOINT` 与 `ALIYUN_DM_FROM_ALIAS` 可保持默认。
  2. 确认 DirectMail 控制台中 `noreply@mail.suming.work` 已验证，并且 DNS 的 SPF/DKIM 已生效。
  3. 对已有数据库执行迁移 007（空数据卷才会自动执行，已有库必须手动执行）：
     `docker compose -f docker-compose.prod.yml exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < app/db/migrations/007_email_verification.sql`
     迁移会把 `demo_user` 标记为已验证，否则它会被拦在登录之外。
  4. 部署后用一个真实邮箱注册，确认验证邮件能收到，点击链接后可以登录。之后再用同一链接点第二次，应提示链接无效（一次性）。
  5. 日志中出现 `邮件后端为 log` 或 `DirectMail 拒绝请求` 说明配置有误，此时注册不会收到邮件，用户可以在登录页重新发送。
  - 说明：注册与重发对外的响应与邮箱是否存在无关（防枚举）。已存在但未验证的账号，重新注册会重发验证邮件，并沿用原密码（本次输入的密码不覆盖）。
  - 本地开发保持 `MAIL_BACKEND=log`：验证链接会打印到日志中，仅限本机使用。
- **数据隔离上线清单**（分支 `feat/user-isolation`，未合并；合并前必须按顺序完成，否则用户检索会返回空）：
  1. 在服务器对已有数据库执行迁移（`docker-entrypoint-initdb.d` 只在空数据卷时执行）：
     `docker compose -f docker-compose.prod.yml exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < app/db/migrations/006_document_sharing.sql`
  2. 部署新镜像后，**立即重建索引**。旧 `meta.json` 没有归属字段，新代码会把这些向量全部视为不可见：
     `docker compose -f docker-compose.prod.yml run --rm -v "$PWD/scripts:/app/scripts:ro" backend python scripts/build_index.py --verify`，然后 `restart backend`。重建时语料文档自动标记为共享（`is_shared = TRUE`）。
  3. 验证：用两个账号登录，A 上传的文档 B 不可见、检索不到、引用定位 404；语料对两者都可检索。
  - 已知限制：`SearchDocsTool`（LangGraph 内部 Agent 与 MCP Server）不做用户过滤，MCP Server 是本地 stdio 进程，等同于运行它的操作者拥有数据库访问权限。

- **单用户登录上线清单**（上线顺序很重要，否则会锁死自己）：
  1. 服务器 `.env` 增加 `AUTH_SECRET_KEY=<随机长串，如 openssl rand -hex 32>`；本机开发 `.env` 增加 `AUTH_COOKIE_SECURE=False`（http 调试时 Secure cookie 不会被发送）。
  2. 在服务器上设置登录密码（交互输入，不要把密码发到聊天里）：
     `docker compose -f docker-compose.prod.yml run --rm -it -v "$PWD/scripts:/app/scripts:ro" backend python scripts/set_password.py`
  3. 手动运行 Build and deploy。部署后 basic auth 仍在，先用浏览器经 basic auth 进入，确认可以登录、问答、上传、会话功能正常。
  4. 确认无误后，从 `deploy/nginx/rag.conf` 删除 `auth_basic` 两行，服务器上 `nginx -t && systemctl reload nginx`。
  5. 验证：未登录 `curl https://suming.work/api/v1/sessions` 应为 401；登录页可用；退出后回到登录页。
  6. 验证 Next 的 rewrite 会透传 `Set-Cookie`：登录成功后，浏览器开发者工具里应能看到 `rag_session` cookie 且为 HttpOnly。
- **找回密码与注销账号上线清单**（未合并，依赖注册功能已部署）：
  1. 对已有数据库执行迁移 008（新增 `email_codes` 表）：
     `docker compose -f docker-compose.prod.yml exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < app/db/migrations/008_email_codes.sql`
  2. 邮件配置与注册功能相同（`MAIL_BACKEND=directmail` 等）。验证码邮件发送失败时：找回密码对外仍返回相同提示，日志中有 `验证码邮件发送失败`；注销会返回 503 并提示重试。
  3. 验证：用真实邮箱走完「忘记密码 → 收码 → 重置 → 用新密码登录」；同一验证码错误 5 次后拒绝；用测试账号走完「登录 → 注销 → 再次登录失败」。`demo_user` 持有共享语料，注销返回 409 是预期行为。
  4. 已知限制：改密码或注销后，其他设备上的旧 cookie 在 7 天内仍可通过签名校验（无服务端吊销）。注销后这些 cookie 调用会话、上传接口会返回 401。
- 向量索引文件在 `.gitignore` 中（`data/index/`），不随仓库部署。新增语料或新环境需在服务器上手动构建：
  ```bash
  cd /opt/rag-kb
  export IMAGE_PREFIX=<ACR_VPC_REGISTRY>/<NAMESPACE> IMAGE_TAG=<当前部署的 sha-xxxxxxx>
  docker compose -f docker-compose.prod.yml run --rm \
    -v "$PWD/scripts:/app/scripts:ro" \
    backend python scripts/build_index.py --verify
  docker compose -f docker-compose.prod.yml restart backend
  ```
- `build_index.py` 只入库 `.md` / `.txt` 语料；PDF 等需通过页面上传，由上传接口解析并写入索引。
- 手动执行 `docker compose` 时必须先导出 `IMAGE_PREFIX` / `IMAGE_TAG`，否则镜像名为空。
- 部署改为手动触发，推送 master 不会自动上线。线上版本与 master 可能不一致，以 Actions 最近一次成功的 `deploy` 为准。
- ACR 个人版不支持 OCI attestation manifest，build 中已关闭 `provenance` 与 `sbom`。
- 镜像推送到国内 ACR 的上传较慢（首次约 22 分钟），依赖 GitHub Runner 到 ACR 公网的带宽。
- 登录、会话历史接口未实现，前端对应页面未做。

## 六、部署踩坑记录

| 现象 | 原因 | 处理 |
|---|---|---|
| SSH 部署 `dial tcp :22: i/o timeout` | 安全组只对个人 IP 放行 22，GitHub 托管 Runner 出口 IP 不固定 | 改为 ECS 上的自托管 Runner，本机部署，22 不再对外开放 |
| `docker compose pull` 访问 Docker Hub 超时 | 国内 ECS 访问 `registry-1.docker.io` 不稳定 | 配置阿里云镜像加速器 |
| 问答拒答 `index_not_ready` | `data/index/` 被 git 忽略；`seed.sql` 只插入了无 chunk 的占位文档 | 服务器上运行 `build_index.py` 入库语料并建索引，删除占位文档 |
| certbot HTTP-01 续期模拟返回 403 | 本机与 CA 各视角请求均到达 nginx 并返回 200，根因未查明 | 改用 acme.sh + 阿里云 DNS（DNS-01），续期不依赖 80 端口 |
| 部署 `failed to copy: connection reset by peer` | ECS 到 GHCR 的大层下载被对端重置 | 加 pull 重试，仍不稳定 |
| GHCR 镜像 `Downloading` 长时间停滞，ECS 上 `git fetch github.com` 也超时 | ECS 到 GitHub/GHCR 公网链路不稳定，大数据块传输停滞（ICMP 被过滤，无法用 ping 判断 MTU） | 取消 push 自动部署改为手动；镜像仓库迁移到阿里云 ACR，ECS 走 VPC 内网拉取 |
| 推送 master 时部署每次都失败、占用 `rag-ecs` 约 30 分钟 | deploy 与推送绑定，网络问题每次都会触发 | `on:` 改为 `workflow_dispatch` |
| 测试失败（CI 上 5 个 error + 2 个 failed） | 本地依赖 `.env` 中的 DashScope key 与 PostgreSQL，CI 上没有 | 测试注入假 key，未找到文档用例注入假 lifespan；部署前增加 `test` 门禁 |
| 部署没有等测试通过 | `ci.yml` 与 `deploy.yml` 是两个独立 workflow，deploy 不依赖测试结果 | `deploy.yml` 增加 `test` job，`build` 依赖它 |
| `build` 报 `Username and password required` | ACR Secret 配置在 `production` 环境中，只有声明该环境的 job 能读取，`build` 未声明 | `build` job 增加 `environment: production` |
| ACR 推送 `no such host` | 主机名少写 / 多写 `crpi-` 前缀（`crpi-crpi-…`） | 按控制台给出的实际主机名修正 Secret |
| ACR 推送 `unknown manifest class for application/vnd.oci.empty.v1+json` | buildx 默认推送 provenance/SBOM 的 attestation manifest，ACR 个人版不支持 | `provenance: false`、`sbom: false` |
| `npm run build` 报 `SecurityFatalError` | Next.js 16.4.0 存在 critical 漏洞（16.0.0–16.4.0） | 升级到 16.4.3（`next` 与 `eslint-config-next` 精确锁定），`npm audit` 清零 |
| 注册点「注册」返回「服务器内部错误」（密码合规） | 两个可能：① 未执行迁移 007，`users.email_verified_at` / `email_tokens` 不存在，原先是通用 500；② 密码超过 72 字节时 bcrypt>=5 抛 `ValueError`（校验曾允许 128 字符） | 密码改为按 UTF-8 字节限制 72；结构缺失改为 503 并提示执行迁移 007；邮件异常不再影响已提交的注册 |
| 注册页眼睛按钮在提交后消失 | 只用了浏览器原生的密码图标，提交后表单重绘、图标随之消失 | 新增 `PasswordInput` 组件，按钮始终渲染；隐藏原生图标；登录页同步使用 |
| 线上 ACR 密码明文出现在聊天中 | 凭据在对话中暴露 | 立即重置，只在 GitHub Secrets 中保存新值 |

## 七、风险与降级方案

- 若 Next.js 前端在周三前仍未完成主要页面：先上线现有 `static/index.html`，Next.js 版本作为第 23 周前的增量迭代，并在简历中如实描述。
- 若云服务器部署受阻：本地 `docker-compose up` 录屏 + 公网隧道作为临时演示，同时保留部署问题记录。
- 若演示视频时间不足：先录 2 分钟版本，细节放进 README 的 Trace 截图。

### 线上端到端验证（2026-10-27）

- 镜像 tag：<实际 tag>
- basic auth：首页不带凭据 401，带凭据 200
- POST /api/v1/sessions：200，返回 data.id
- 带 session_id 提问：refused=false，citations 非空
- 会话详情：
  - title：什么是 chunk 切分？
  - messages：['user','assistant','user','assistant']
  - assistant[1] citations：03_chunking_parsing.md / a5fd64b5 / 1055
  - assistant[3] citations：02_embedding_vector.md / e1da38b8 / 1013
- 负面用例：
  - 不存在会话：404
  - 非法 ID：404（待补）
- 备注：basic auth 未映射 user_id，用户隔离待单用户登录后复测