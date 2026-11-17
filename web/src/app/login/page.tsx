"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { HttpError, login, resendVerification } from "@/lib/api";
import { PasswordInput } from "@/components/password-input";
import { AuthLayout } from "@/components/auth-layout";

export default function LoginPage() {
  const router = useRouter();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [needsVerification, setNeedsVerification] = useState(false);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    setNotice(null);
    setNeedsVerification(false);
    try {
      await login(identifier.trim(), password);
      // 密码只在本次提交中使用，提交后立即清空
      setPassword("");
      router.replace("/");
      router.refresh();
    } catch (err) {
      // 403 表示密码正确但邮箱未验证：提供重新发送入口
      if (err instanceof HttpError && err.status === 403) setNeedsVerification(true);
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleResend() {
    setSubmitting(true);
    setError(null);
    try {
      await resendVerification(identifier.trim());
      setNotice("若该邮箱尚未验证，已重新发送验证邮件，请查收（24 小时内有效）。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "发送失败");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthLayout title="欢迎回来" subtitle="登录知序，继续整理知识与探索答案。">
      <form
        onSubmit={handleSubmit}
        className="auth-form"
        style={{ display: "grid", gap: 20 }}
      >
        <label className="field">
          邮箱或用户名
          <input
            value={identifier}
            onChange={(e) => setIdentifier(e.target.value)}
            autoComplete="username"
            required
            placeholder="输入邮箱或用户名"
          />
        </label>

        <div className="field">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
            <label htmlFor="login-password">密码</label>
            <Link href="/forgot" className="text-button">忘记密码？</Link>
          </div>
          <PasswordInput
            id="login-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
            placeholder="输入密码"
          />
        </div>

        {error && (
          <p role="alert" className="error-message">
            {error}
          </p>
        )}
        {notice && <p role="status" className="success-message">{notice}</p>}

        <button
          type="submit"
          disabled={submitting || !identifier || !password}
          className="primary-button"
        >
          {submitting ? "登录中…" : "登录"}
        </button>

        {needsVerification && (
          <button
            type="button"
            onClick={handleResend}
            disabled={submitting || !identifier}
            className="secondary-button"
          >
            重新发送验证邮件
          </button>
        )}

        <p className="auth-links muted">
          还没有账号？ <Link href="/register" className="text-button">创建账号</Link>
        </p>
      </form>
    </AuthLayout>
  );
}
