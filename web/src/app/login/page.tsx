"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { HttpError, login, resendVerification } from "@/lib/api";
import { PasswordInput } from "@/components/password-input";

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
    <main
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "#fafafa",
        color: "#171717",
        padding: 24,
      }}
    >
      <form
        onSubmit={handleSubmit}
        style={{
          width: 320,
          padding: 24,
          background: "#fff",
          border: "1px solid #e5e5e5",
          borderRadius: 8,
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        <h1 style={{ fontSize: 20 }}>RAG 知识库</h1>

        <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 14 }}>
          邮箱或用户名
          <input
            value={identifier}
            onChange={(e) => setIdentifier(e.target.value)}
            autoComplete="username"
            required
            style={{ padding: 8, border: "1px solid #d0d0d0", borderRadius: 6, font: "inherit" }}
          />
        </label>

        <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 14 }}>
          密码
          <PasswordInput
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
            style={{ padding: 8, border: "1px solid #d0d0d0", borderRadius: 6, font: "inherit" }}
          />
        </label>

        {error && (
          <p role="alert" style={{ color: "#b00020", fontSize: 14 }}>
            {error}
          </p>
        )}
        {notice && <p style={{ color: "#1a7f37", fontSize: 14 }}>{notice}</p>}

        <button
          type="submit"
          disabled={submitting || !identifier || !password}
          style={{ padding: "8px 0", cursor: "pointer" }}
        >
          {submitting ? "登录中…" : "登录"}
        </button>

        {needsVerification && (
          <button
            type="button"
            onClick={handleResend}
            disabled={submitting || !identifier}
            style={{ padding: "6px 0", cursor: "pointer", fontSize: 14 }}
          >
            重新发送验证邮件
          </button>
        )}

        <p style={{ fontSize: 14, textAlign: "center" }}>
          没有账号？<Link href="/register">注册</Link>
        </p>
        <p style={{ fontSize: 14, textAlign: "center" }}>
          <Link href="/forgot">忘记密码？</Link>
        </p>
      </form>
    </main>
  );
}
