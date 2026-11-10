"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { forgotPassword, resetPassword } from "@/lib/api";
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

const FIELD_STYLE = { display: "flex", flexDirection: "column", gap: 4, fontSize: 14 } as const;

type Step = "email" | "reset";

/**
 * 找回密码：第一步输入注册邮箱，发送 6 位验证码；第二步输入验证码与新密码。
 * 发送成功与否的提示与账号是否存在无关，避免枚举。
 */
export default function ForgotPasswordPage() {
  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function requestCode() {
    setSubmitting(true);
    setError(null);
    setNotice(null);
    try {
      await forgotPassword(email.trim());
      setStep("reset");
      setNotice("若该邮箱已注册，验证码已发送，10 分钟内有效。没收到可稍后重新发送。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "发送失败");
    } finally {
      setSubmitting(false);
    }
  }

  async function resetWithCode() {
    setError(null);
    setNotice(null);
    if (!/^\d{6}$/.test(code)) {
      setError("验证码为 6 位数字");
      return;
    }
    if (password !== confirm) {
      setError("两次输入的密码不一致");
      return;
    }
    setSubmitting(true);
    try {
      await resetPassword(email.trim(), code, password);
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "重置失败");
    } finally {
      setSubmitting(false);
    }
  }

  function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (step === "email") {
      void requestCode();
    } else {
      void resetWithCode();
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
        <h1 style={{ fontSize: 20 }}>找回密码</h1>

        {done ? (
          <>
            <p style={{ color: "#1a7f37", fontSize: 14 }}>密码已重置，请使用新密码登录。</p>
            <Link href="/login" style={{ fontSize: 14, textAlign: "center" }}>
              前往登录
            </Link>
          </>
        ) : (
          <>
            {step === "email" && (
              <label style={FIELD_STYLE}>
                注册邮箱
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoComplete="email"
                  required
                  style={INPUT_STYLE}
                />
              </label>
            )}

            {step === "reset" && (
              <>
                <p style={{ fontSize: 14, color: "#555" }}>
                  验证码已发送至 <strong>{email.trim()}</strong>
                </p>

                <label style={FIELD_STYLE}>
                  验证码（6 位数字）
                  <input
                    value={code}
                    onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    required
                    style={{ ...INPUT_STYLE, letterSpacing: 4 }}
                  />
                </label>

                <label style={FIELD_STYLE}>
                  新密码（至少 10 位，需同时包含字母和数字）
                  <PasswordInput
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    autoComplete="new-password"
                    required
                    style={INPUT_STYLE}
                  />
                </label>

                <label style={FIELD_STYLE}>
                  确认新密码
                  <PasswordInput
                    value={confirm}
                    onChange={(e) => setConfirm(e.target.value)}
                    autoComplete="new-password"
                    required
                    style={INPUT_STYLE}
                  />
                </label>
              </>
            )}

            {error && (
              <p role="alert" style={{ color: "#b00020", fontSize: 14 }}>
                {error}
              </p>
            )}
            {notice && <p style={{ color: "#1a7f37", fontSize: 14 }}>{notice}</p>}

            <button
              type="submit"
              disabled={
                submitting ||
                (step === "email" && !email) ||
                (step === "reset" && (!code || !password || !confirm))
              }
              style={{ padding: "8px 0", cursor: "pointer" }}
            >
              {submitting
                ? "提交中…"
                : step === "email"
                  ? "发送验证码"
                  : "重置密码"}
            </button>

            {step === "reset" && (
              <button
                type="button"
                onClick={() => void requestCode()}
                disabled={submitting}
                style={{ padding: "6px 0", cursor: "pointer", fontSize: 14 }}
              >
                重新发送验证码
              </button>
            )}

            <p style={{ fontSize: 14, textAlign: "center" }}>
              想起密码了？<Link href="/login">返回登录</Link>
            </p>
          </>
        )}
      </form>
    </main>
  );
}
