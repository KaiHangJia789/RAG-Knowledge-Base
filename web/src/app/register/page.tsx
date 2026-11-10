"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { register } from "@/lib/api";
import { PasswordInput } from "@/components/password-input";

const PAGE_STYLE = {
  minHeight: "100vh",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  background: "#fafafa",
  color: "#171717",
  padding: 24,
} as const;

const INPUT_STYLE = { padding: 8, border: "1px solid #d0d0d0", borderRadius: 6, font: "inherit" } as const;

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
    <main style={PAGE_STYLE}>
      <form
        onSubmit={handleSubmit}
        style={{
          width: 340,
          padding: 24,
          background: "#fff",
          border: "1px solid #e5e5e5",
          borderRadius: 8,
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        <h1 style={{ fontSize: 20 }}>注册</h1>

        {message ? (
          <>
            <p style={{ color: "#1a7f37", fontSize: 14 }}>{message}</p>
            <p style={{ fontSize: 14 }}>
              没收到？回到 <Link href="/login">登录页</Link> 重新发送。
            </p>
          </>
        ) : (
          <>
            <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 14 }}>
              邮箱
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                required
                style={INPUT_STYLE}
              />
            </label>

            <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 14 }}>
              密码（至少 10 位，需同时包含字母和数字）
              <PasswordInput
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
                required
                style={INPUT_STYLE}
              />
            </label>

            <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 14 }}>
              确认密码
              <PasswordInput
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                autoComplete="new-password"
                required
                style={INPUT_STYLE}
              />
            </label>

            {error && (
              <p role="alert" style={{ color: "#b00020", fontSize: 14 }}>
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={submitting || !email || !password || !confirm}
              style={{ padding: "8px 0", cursor: "pointer" }}
            >
              {submitting ? "提交中…" : "注册"}
            </button>

            <p style={{ fontSize: 14, textAlign: "center" }}>
              已有账号？<Link href="/login">登录</Link>
            </p>
          </>
        )}
      </form>
    </main>
  );
}
