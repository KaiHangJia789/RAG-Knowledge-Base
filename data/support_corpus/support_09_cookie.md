# 本机 HTTP 登录与 cookie

示范产品：RAG Knowledge Base
资料类型：技术支持示范资料草稿
适用范围：基础代码快照 b89d2a2；本期新增行为另有注明，不作为商业版本承诺
整理日期：2026-11-13
代码来源：app/config.py; app/api/v1/auth.py; app/dependencies/login.py

AUTH_COOKIE_SECURE 默认 True，面向 HTTPS。仅在本机 HTTP 开发时设置 False，避免浏览器无法按预期携带 Secure cookie。修改服务配置后需使 backend 重新读取环境。
登录后仍显示 401，应查看登录请求是否成功、响应是否设置 cookie、后续同源 API 请求是否发送 cookie。不要把该问题简单归因于密码错误。
生产使用 HTTPS 并保留 Secure 和 HttpOnly。不要在排障中发送 cookie 或 AUTH_SECRET_KEY。
