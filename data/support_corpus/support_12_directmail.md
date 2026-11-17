# 注册后收不到邮件

示范产品：RAG Knowledge Base
资料类型：技术支持示范资料草稿
适用范围：基础代码快照 b89d2a2；本期新增行为另有注明，不作为商业版本承诺
整理日期：2026-11-13
代码来源：app/mail/sender.py; app/services/account_service.py; app/config.py

先检查 MAIL_BACKEND。log 仅将邮件写到本机日志；directmail 才调用阿里云 DirectMail。相关配置包括 ALIYUN_ACCESS_KEY_ID、ALIYUN_ACCESS_KEY_SECRET、ALIYUN_DM_ACCOUNT_NAME 与 PUBLIC_BASE_URL。
从应用日志确认是否有发送错误，再由账户管理人员核对服务端凭据与发信账户配置，并在邮箱中查看垃圾邮件、收信规则与地址拼写。不要粘贴 AccessKey 或验证码到会话。
注册提交成功与邮件最终到达是两个步骤；当前注册服务会隔离邮件发送异常，避免已提交账号因邮件错误变为注册事务失败。已发送也不能由应用单独证明最终进入收件箱。
