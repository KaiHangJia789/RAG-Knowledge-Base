"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { deleteAccount, requestDeleteCode } from "@/lib/api";

/**
 * 注销账号（需登录）。两步确认：
 * 1. 向本人注册邮箱发送验证码；
 * 2. 输入验证码，服务端删除账号及其全部文档与会话，并清除登录 cookie。
 */
export default function AccountPage() {
  const router = useRouter();
  const [codeSent, setCodeSent] = useState(false);
  const [code, setCode] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function sendCode() {
    setSubmitting(true);
    setError(null);
    setNotice(null);
    try {
      await requestDeleteCode();
      setCodeSent(true);
      setNotice("验证码已发送到你的注册邮箱，10 分钟内有效。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "发送失败");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setNotice(null);
    if (!/^\d{6}$/.test(code)) {
      setError("验证码为 6 位数字");
      return;
    }
    setSubmitting(true);
    try {
      await deleteAccount(code);
      router.replace("/login");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "注销失败");
      setSubmitting(false);
    }
  }

  return (
    <section className="account-page" aria-labelledby="account-title" style={{ display: "grid", gap: 24 }}>
      <header style={{ display: "grid", gap: 8 }}>
        <p className="eyebrow">账号管理</p>
        <h1 id="account-title" className="page-heading">注销账号</h1>
        <p className="muted">请先通过邮箱验证身份，再确认注销。</p>
      </header>

      <div
        role="note"
        className="danger-note"
      >
        注销后将<strong>永久删除</strong>以下内容，且无法恢复：你的账号、你上传的全部文档及其向量索引、
        全部会话记录。
      </div>

      <form onSubmit={handleDelete} className="auth-form" style={{ display: "grid", gap: 20 }}>
        {!codeSent ? (
          <button
            type="button"
            onClick={() => void sendCode()}
            disabled={submitting}
            className="secondary-button"
            style={{ justifySelf: "start" }}
          >
            {submitting ? "发送中…" : "发送验证码到我的邮箱"}
          </button>
        ) : (
          <>
            <label className="field">
              邮箱验证码
              <input
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                inputMode="numeric"
                autoComplete="one-time-code"
                required
                placeholder="6 位数字"
                style={{ letterSpacing: 4, maxWidth: 220, width: "100%" }}
              />
            </label>

            <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center" }}>
              <button
                type="submit"
                disabled={submitting || code.length !== 6}
                className="danger-button"
              >
                {submitting ? "注销中…" : "确认注销账号"}
              </button>
              <button
                type="button"
                onClick={() => void sendCode()}
                disabled={submitting}
                className="text-button"
              >
                重新发送验证码
              </button>
            </div>
          </>
        )}

        {error && (
          <p role="alert" className="error-message">
            {error}
          </p>
        )}
        {notice && <p role="status" className="success-message">{notice}</p>}
      </form>

      <p>
        <Link href="/" className="text-button">
          返回工作台
        </Link>
      </p>
    </section>
  );
}
