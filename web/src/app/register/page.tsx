"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { register } from "@/lib/api";
import { PasswordInput } from "@/components/password-input";
import { AuthLayout } from "@/components/auth-layout";

export default function RegisterPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    if (password !== confirm) {
      setError("两次输入的密码不一致");
      return;
    }
    setSubmitting(true);
    try {
      await register(email.trim(), password);
      setMessage("验证邮件已发送。请打开邮箱，点击链接完成验证（24 小时内有效）。");
      setPassword("");
      setConfirm("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "注册失败");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthLayout
      title={message ? "查收验证邮件" : "创建账号"}
      subtitle={message ? "完成邮箱验证，即可开启你的知识空间。" : "让文档成为知识，让提问找到依据。"}
    >
      <form
        onSubmit={handleSubmit}
        className="auth-form"
        style={{ display: "grid", gap: 20 }}
      >
        {message ? (
          <>
            <p role="status" className="success-message">{message}</p>
            <Link href="/login" className="primary-button">返回登录</Link>
            <p className="auth-links muted">
              没收到邮件？可在 <Link href="/login" className="text-button">登录页</Link> 重新发送。
            </p>
          </>
        ) : (
          <>
            <label className="field">
              邮箱
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                required
                placeholder="输入常用邮箱"
              />
            </label>

            <div className="field">
              <label htmlFor="register-password">密码</label>
              <PasswordInput
                id="register-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
                required
                placeholder="设置登录密码"
                aria-describedby="register-password-help"
              />
              <p id="register-password-help" className="muted" style={{ fontSize: 12 }}>至少 10 位，需同时包含字母和数字。</p>
            </div>

            <div className="field">
              <label htmlFor="register-confirm">确认密码</label>
              <PasswordInput
                id="register-confirm"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                autoComplete="new-password"
                required
                placeholder="再次输入密码"
              />
            </div>

            {error && (
              <p role="alert" className="error-message">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={submitting || !email || !password || !confirm}
              className="primary-button"
            >
              {submitting ? "创建中…" : "创建账号"}
            </button>

            <p className="auth-links muted">
              已有账号？ <Link href="/login" className="text-button">登录</Link>
            </p>
          </>
        )}
      </form>
    </AuthLayout>
  );
}
