"""
邮件发送。

MAIL_BACKEND:
- "log"（默认，开发用）：不真正发送，把收件人与内容写入日志。日志含一次性验证链接，只能在本机使用。
- "directmail"：阿里云邮件推送（DirectMail）SingleSendMail 接口。

直接用标准库按阿里云 RPC 签名规则调用，避免为一个接口引入整个 SDK。
凭据只从环境变量读取，不写入日志。
"""
import asyncio
import base64
import hashlib
import hmac
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from app.config import settings

logger = logging.getLogger("rag_api.mail")


@dataclass(frozen=True)
class MailMessage:
    to: str
    subject: str
    html: str


class MailSendError(Exception):
    """发送失败：网络、凭据缺失、发信地址未验证等"""


class MailSender(Protocol):
    async def send(self, message: MailMessage) -> None: ...


class LogMailSender:
    async def send(self, message: MailMessage) -> None:
        logger.warning(
            "[LOG 模式，邮件未真实发送] to=%s subject=%s body=%s",
            message.to, message.subject, message.html,
        )


def _pct(value: str) -> str:
    """阿里云要求的 RFC 3986 编码：空格为 %20，* 必须编码，~ 保留"""
    return urllib.parse.quote(str(value), safe="~")


def _parse_json(raw: bytes) -> dict:
    try:
        return json.loads(raw.decode() or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}


class DirectMailSender:
    VERSION = "2015-11-23"

    def __init__(
        self,
        *,
        access_key_id: str,
        access_key_secret: str,
        account_name: str,
        endpoint: str,
        from_alias: str,
        timeout: float = 10,
        opener=urllib.request.urlopen,
    ) -> None:
        self._ak = access_key_id
        self._secret = access_key_secret
        self._account = account_name
        self._endpoint = endpoint.rstrip("/") + "/"
        self._from_alias = from_alias
        self._timeout = timeout
        self._opener = opener

    def build_params(
        self, message: MailMessage, *, nonce: str | None = None, timestamp: str | None = None
    ) -> dict[str, str]:
        return {
            "Format": "JSON",
            "Version": self.VERSION,
            "AccessKeyId": self._ak,
            "SignatureMethod": "HMAC-SHA1",
            "SignatureVersion": "1.0",
            "SignatureNonce": nonce or uuid.uuid4().hex,
            "Timestamp": timestamp or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "Action": "SingleSendMail",
            "AccountName": self._account,
            "ReplyToAddress": "false",
            "AddressType": "1",
            "ToAddress": message.to,
            "Subject": message.subject,
            "HtmlBody": message.html,
            "FromAlias": self._from_alias,
        }

    def sign(self, params: dict[str, str]) -> str:
        """params 为签名前的参数，不得包含 Signature 本身"""
        canonical = "&".join(f"{_pct(k)}={_pct(v)}" for k, v in sorted(params.items()))
        string_to_sign = f"POST&{_pct('/')}&{_pct(canonical)}"
        digest = hmac.new(f"{self._secret}&".encode(), string_to_sign.encode(), hashlib.sha1).digest()
        return base64.b64encode(digest).decode()

    async def send(self, message: MailMessage) -> None:
        if not (self._ak and self._secret and self._account):
            raise MailSendError("DirectMail 凭据或发信地址未配置")
        await asyncio.to_thread(self._send_sync, message)

    def _send_sync(self, message: MailMessage) -> None:
        params = self.build_params(message)
        params["Signature"] = self.sign(params)
        body = urllib.parse.urlencode(params).encode()
        req = urllib.request.Request(
            self._endpoint, data=body, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with self._opener(req, timeout=self._timeout) as resp:
                data = _parse_json(resp.read())
        except urllib.error.HTTPError as e:
            data = _parse_json(e.read())
            raise MailSendError(
                f"DirectMail 拒绝请求: {data.get('Code', e.code)} {data.get('Message', '')}"
            ) from e
        except urllib.error.URLError as e:
            raise MailSendError(f"无法连接 DirectMail: {e.reason}") from e
        except OSError as e:
            # 读取响应时的超时（socket.timeout）不会被 URLError 包住
            raise MailSendError(f"DirectMail 请求失败: {e}") from e

        if "Code" in data:
            raise MailSendError(f"DirectMail 返回错误: {data.get('Code')} {data.get('Message', '')}")
        logger.info("验证邮件已提交 DirectMail（RequestId=%s）", data.get("RequestId"))


def build_mailer() -> MailSender:
    if settings.MAIL_BACKEND == "directmail":
        if not (settings.ALIYUN_ACCESS_KEY_ID and settings.ALIYUN_ACCESS_KEY_SECRET and settings.ALIYUN_DM_ACCOUNT_NAME):
            logger.error(
                "MAIL_BACKEND=directmail，但 ALIYUN_ACCESS_KEY_ID / ALIYUN_ACCESS_KEY_SECRET / "
                "ALIYUN_DM_ACCOUNT_NAME 未全部配置：验证邮件将无法发送"
            )
        return DirectMailSender(
            access_key_id=settings.ALIYUN_ACCESS_KEY_ID,
            access_key_secret=settings.ALIYUN_ACCESS_KEY_SECRET,
            account_name=settings.ALIYUN_DM_ACCOUNT_NAME,
            endpoint=settings.ALIYUN_DM_ENDPOINT,
            from_alias=settings.ALIYUN_DM_FROM_ALIAS,
        )
    logger.warning("邮件后端为 log：验证邮件不会真实发送（仅开发环境使用）")
    return LogMailSender()
