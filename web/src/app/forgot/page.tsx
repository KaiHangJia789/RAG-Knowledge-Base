"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { forgotPassword, resetPassword } from "@/lib/api";
import { PasswordInput } from "@/components/password-input";
import { AuthLayout } from "@/components/auth-layout";

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
    <AuthLayout
      title={done ? "密码已更新" : step === "email" ? "找回密码" : "设置新密码"}
      subtitle={done ? "使用新密码登录，继续你的知识探索。" : step === "email" ? "通过注册邮箱验证身份，重新设置密码。" : "输入邮箱验证码，为账号设置新密码。"}
    >
      <form
        onSubmit={handleSubmit}
        className="auth-form"
        style={{ display: "grid", gap: 20 }}
      >
        {done ? (
          <>
            <p role="status" className="success-message">密码已重置，请使用新密码登录。</p>
            <Link href="/login" className="primary-button">
              前往登录
            </Link>
          </>
        ) : (
          <>
            {step === "email" && (
              <label className="field">
                注册邮箱
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoComplete="email"
                  required
                  placeholder="输入注册时使用的邮箱"
                />
              </label>
            )}

            {step === "reset" && (
              <>
                <p className="muted" style={{ overflowWrap: "anywhere" }}>
                  验证邮箱：<strong>{email.trim()}</strong>
                </p>

                <label className="field">
                  邮箱验证码
                  <input
                    value={code}
                    onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    required
                    placeholder="6 位数字"
                    style={{ letterSpacing: 4 }}
                  />
                </label>

                <div className="field">
                  <label htmlFor="reset-password">新密码</label>
                  <PasswordInput
                    id="reset-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    autoComplete="new-password"
                    required
                    placeholder="设置新密码"
                    aria-describedby="reset-password-help"
                  />
                  <p id="reset-password-help" className="muted" style={{ fontSize: 12 }}>至少 10 位，需同时包含字母和数字。</p>
                </div>

                <div className="field">
                  <label htmlFor="reset-confirm">确认新密码</label>
                  <PasswordInput
                    id="reset-confirm"
                    value={confirm}
                    onChange={(e) => setConfirm(e.target.value)}
                    autoComplete="new-password"
                    required
                    placeholder="再次输入新密码"
                  />
                </div>
              </>
            )}

            {error && (
              <p role="alert" className="error-message">
                {error}
              </p>
            )}
            {notice && <p role="status" className="success-message">{notice}</p>}

            <button
              type="submit"
              disabled={
                submitting ||
                (step === "email" && !email) ||
                (step === "reset" && (!code || !password || !confirm))
              }
              className="primary-button"
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
                className="secondary-button"
              >
                重新发送验证码
              </button>
            )}

            <p className="auth-links muted">
              想起密码了？ <Link href="/login" className="text-button">返回登录</Link>
            </p>
          </>
        )}
      </form>
    </AuthLayout>
  );
}
