"""
登录功能测试

1. 令牌：签名、篡改、过期、密钥不一致
2. 密码：bcrypt 校验，非法哈希不抛异常
3. 限流：失败计数、窗口过期、成功后清零
4. HTTP：未登录被拒、登录/登出/me、只允许唯一账号、限流返回 429、业务路由需要登录
"""
import time

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth import tokens
from app.auth.login_limiter import LoginLimiter, login_limiter
from app.auth.passwords import hash_password, verify_password
from app.config import settings

DEMO_ID = "13ec9ba4-eb65-42b5-9653-9ebb2410709c"
PASSWORD = "correct-horse-battery"
PASSWORD_HASH = hash_password(PASSWORD)


@pytest.fixture(autouse=True)
def _auth_settings(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(settings, "AUTH_COOKIE_SECURE", False)  # 测试走 http://test
    monkeypatch.setattr(settings, "AUTH_TOKEN_TTL_HOURS", 1)
    monkeypatch.setattr(settings, "AUTH_LOGIN_MAX_FAILURES", 3)
    monkeypatch.setattr(settings, "AUTH_LOGIN_WINDOW_SECONDS", 60)
    login_limiter._failures.clear()
    yield
    login_limiter._failures.clear()


# ═══════════════════════════════════════════════════════════════
# 1. 令牌
# ═══════════════════════════════════════════════════════════════

class TestTokens:

    def test_issued_token_verifies(self):
        token = tokens.issue(DEMO_ID, "demo_user")
        session = tokens.verify(token)
        assert session is not None
        assert session.username == "demo_user"
        assert session.user_id == DEMO_ID

    def test_tampered_payload_is_rejected(self):
        token = tokens.issue(DEMO_ID, "demo_user")
        body, sig = token.rsplit(".", 1)
        import base64
        forged = base64.urlsafe_b64encode(b"admin|9999999999").decode().rstrip("=")
        assert tokens.verify(f"{forged}.{sig}") is None

    def test_wrong_secret_is_rejected(self, monkeypatch):
        token = tokens.issue(DEMO_ID, "demo_user")
        monkeypatch.setattr(settings, "AUTH_SECRET_KEY", "another-secret")
        assert tokens.verify(token) is None

    def test_expired_token_is_rejected(self):
        token = tokens.issue(DEMO_ID, "demo_user", now=time.time() - 2 * 3600)  # TTL 1 小时，已过期
        assert tokens.verify(token) is None

    @pytest.mark.parametrize("garbage", [None, "", "no-dot", "a.b.c", "....", "%%%.abc"])
    def test_garbage_is_rejected_without_exception(self, garbage):
        assert tokens.verify(garbage) is None


# ═══════════════════════════════════════════════════════════════
# 2. 密码
# ═══════════════════════════════════════════════════════════════

class TestPasswords:

    def test_hash_and_verify(self):
        assert verify_password(PASSWORD, PASSWORD_HASH) is True
        assert verify_password("wrong", PASSWORD_HASH) is False

    def test_hash_format_is_bcrypt_compatible_with_seed(self):
        # 与 users.password_hash 的既有格式一致（$2b$ 前缀）
        assert PASSWORD_HASH.startswith("$2b$")

    def test_malformed_hash_does_not_raise(self):
        assert verify_password(PASSWORD, "plain-text-not-a-hash") is False
        assert verify_password(PASSWORD, None) is False


# ═══════════════════════════════════════════════════════════════
# 3. 限流
# ═══════════════════════════════════════════════════════════════

class TestLoginLimiter:

    def test_blocks_after_max_failures(self):
        limiter = LoginLimiter()
        now = 1000.0
        for _ in range(3):
            assert limiter.is_blocked("ip", now=now) is False
            limiter.record_failure("ip", now=now)
        assert limiter.is_blocked("ip", now=now) is True

    def test_window_expiry_unblocks(self):
        limiter = LoginLimiter()
        for _ in range(3):
            limiter.record_failure("ip", now=1000.0)
        assert limiter.is_blocked("ip", now=1000.0 + 61) is False

    def test_reset_clears_failures(self):
        limiter = LoginLimiter()
        for _ in range(3):
            limiter.record_failure("ip", now=1000.0)
        limiter.reset("ip")
        assert limiter.is_blocked("ip", now=1000.0) is False

    def test_keys_are_independent(self):
        limiter = LoginLimiter()
        for _ in range(3):
            limiter.record_failure("1.1.1.1", now=1000.0)
        assert limiter.is_blocked("2.2.2.2", now=1000.0) is False


# ═══════════════════════════════════════════════════════════════
# 4. HTTP
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
async def client():
    from app.dependencies.auth import get_account_service
    from app.main import app
    from tests.test_accounts import build_service, seeded_user

    h = build_service(users=[
        seeded_user(DEMO_ID, "demo_user", "demo@example.com", PASSWORD_HASH),
    ])
    app.dependency_overrides[get_account_service] = lambda: h.service
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_account_service, None)


async def _login(client, password=PASSWORD, username="demo_user"):
    return await client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )


class TestLoginHttp:

    async def test_business_route_without_cookie_is_401(self, client):
        assert (await client.get("/api/v1/sessions")).status_code == 401
        assert (await client.get("/api/v1/documents")).status_code == 401

    async def test_health_stays_public(self, client):
        assert (await client.get("/api/v1/health")).status_code != 401

    async def test_me_without_cookie_is_401(self, client):
        assert (await client.get("/api/v1/auth/me")).status_code == 401

    async def test_wrong_password_is_401_and_sets_no_cookie(self, client):
        resp = await _login(client, password="wrong-password-here")
        assert resp.status_code == 401
        assert settings.AUTH_COOKIE_NAME not in resp.cookies

    async def test_other_username_gets_same_error_as_wrong_password(self, client):
        wrong_pw = await _login(client, password="wrong-password-here")
        other_user = await _login(client, username="someone_else")
        assert wrong_pw.json()["message"] == other_user.json()["message"]
        assert other_user.status_code == 401

    async def test_login_sets_httponly_cookie_and_me_works(self, client):
        resp = await _login(client)
        assert resp.status_code == 200
        cookie_header = resp.headers["set-cookie"].lower()
        assert "httponly" in cookie_header
        assert "samesite=lax" in cookie_header
        assert "path=/" in cookie_header

        # httpx 客户端会保存 cookie，随后请求自动携带
        me = await client.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["data"]["username"] == "demo_user"

    async def test_logout_clears_access(self, client):
        await _login(client)
        assert (await client.get("/api/v1/auth/me")).status_code == 200

        resp = await client.post("/api/v1/auth/logout")
        assert resp.status_code == 200
        assert "max-age=0" in resp.headers["set-cookie"].lower()
        client.cookies.clear()
        assert (await client.get("/api/v1/auth/me")).status_code == 401

    async def test_tampered_cookie_is_401(self, client):
        client.cookies.set(settings.AUTH_COOKIE_NAME, "bogus.token")
        assert (await client.get("/api/v1/auth/me")).status_code == 401

    async def test_rate_limit_blocks_even_correct_password(self, client):
        for _ in range(settings.AUTH_LOGIN_MAX_FAILURES):
            assert (await _login(client, password="wrong-password-here")).status_code == 401
        blocked = await _login(client)  # 密码正确也应被挡住
        assert blocked.status_code == 429

    async def test_successful_login_resets_failures(self, client):
        for _ in range(settings.AUTH_LOGIN_MAX_FAILURES - 1):
            await _login(client, password="wrong-password-here")
        assert (await _login(client)).status_code == 200
        # 成功后计数清零，又可以再失败 N-1 次而不被挡
        for _ in range(settings.AUTH_LOGIN_MAX_FAILURES - 1):
            assert (await _login(client, password="wrong-password-here")).status_code == 401
