-- ============================================================
-- 008_email_codes.sql
-- 邮箱验证码表：找回密码、注销账号共用
-- 只保存验证码的 HMAC 摘要；attempts 记录错误尝试次数
-- 幂等：可安全重复执行
-- ============================================================

CREATE TABLE IF NOT EXISTS email_codes (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    purpose     VARCHAR(16) NOT NULL CHECK (purpose IN ('reset', 'delete')),
    code_hash   CHAR(64)    NOT NULL,
    attempts    INT         NOT NULL DEFAULT 0,
    expires_at  TIMESTAMPTZ NOT NULL,
    used_at     TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_email_codes_user_purpose
    ON email_codes (user_id, purpose, created_at DESC);
