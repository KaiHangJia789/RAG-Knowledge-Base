-- ============================================================
-- 007_email_verification.sql
-- 邮箱验证：users.email_verified_at + 一次性邮件令牌表（验证、后续找回密码共用）
-- 幂等：可安全重复执行
-- ============================================================

ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS email_tokens (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    purpose     VARCHAR(16) NOT NULL CHECK (purpose IN ('verify', 'reset')),
    -- 只保存令牌的 SHA-256，数据库泄露时不能直接用于验证
    token_hash  CHAR(64)    NOT NULL UNIQUE,
    expires_at  TIMESTAMPTZ NOT NULL,
    used_at     TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_email_tokens_user_purpose
    ON email_tokens (user_id, purpose);

-- 上线前已存在的 demo_user 视为已验证，否则它会被「邮箱未验证」拦在门外
UPDATE users SET email_verified_at = NOW()
WHERE username = 'demo_user' AND email_verified_at IS NULL;
