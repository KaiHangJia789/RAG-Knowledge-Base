"""邮件模板。链接与验证码经 html.escape 转义"""
import html

from app.config import settings
from app.mail.sender import MailMessage

_CODE_MAIL_TITLES = {
    "reset": ("找回密码", "找回密码验证码 — RAG 知识库"),
    "delete": ("注销账号", "注销账号验证码 — RAG 知识库"),
}


def verification_mail(to: str, link: str) -> MailMessage:
    safe_link = html.escape(link, quote=True)
    body = (
        "<p>你好，</p>"
        "<p>请点击下面的链接完成邮箱验证：</p>"
        f'<p><a href="{safe_link}">{safe_link}</a></p>'
        f"<p>链接 {settings.EMAIL_VERIFY_TTL_HOURS} 小时内有效，且只能使用一次。</p>"
        "<p>如果这不是你本人的操作，请忽略本邮件。</p>"
    )
    return MailMessage(to=to, subject="请验证你的邮箱 — RAG 知识库", html=body)


def code_mail(to: str, *, purpose: str, code: str) -> MailMessage:
    action, subject = _CODE_MAIL_TITLES[purpose]
    body = (
        "<p>你好，</p>"
        f"<p>你正在进行「{action}」操作，验证码为：</p>"
        f'<p style="font-size:24px;font-weight:bold;letter-spacing:4px">{html.escape(code)}</p>'
        f"<p>验证码 {settings.EMAIL_CODE_TTL_MINUTES} 分钟内有效，只能使用一次。</p>"
        "<p>如果这不是你本人的操作，请忽略本邮件，你的账号不会有任何变化。</p>"
    )
    return MailMessage(to=to, subject=subject, html=body)
