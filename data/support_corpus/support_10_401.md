# 未登录接口 401 与页面跳转

示范产品：RAG Knowledge Base
资料类型：技术支持示范资料草稿
适用范围：基础代码快照 b89d2a2；本期新增行为另有注明，不作为商业版本承诺
整理日期：2026-11-13
代码来源：app/dependencies/login.py; web/src/proxy.ts

受保护 API 依赖 require_user 校验签名 cookie，缺少有效登录态返回 401。网页 proxy.ts 根据是否有 rag_session cookie 做页面跳转，前端跳转不代替后端鉴权。
未登录访问首页可能收到重定向到登录页；访问受保护 API 返回 401 是预期。看到页面 307 不能直接认定 nginx 配置错误。
请通过正式登录流程重试；不要关闭鉴权来消除 401。此代码快照未实现统一的密码重置后旧 cookie 版本撤销机制，不能声称所有旧 cookie 都立即失效。
