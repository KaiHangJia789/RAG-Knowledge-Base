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
    <div style={{ padding: 32, maxWidth: 560, display: "flex", flexDirection: "column", gap: 16 }}>
      <h1 style={{ fontSize: 20 }}>注销账号</h1>

      <div
        role="note"
        style={{
          border: "1px solid #f0c36d",
          background: "#fff8e6",
          borderRadius: 6,
          padding: 12,
          fontSize: 14,
          lineHeight: 1.6,
        }}
      >
        注销后将<strong>永久删除</strong>以下内容，且无法恢复：你的账号、你上传的全部文档及其向量索引、
        全部会话记录。
      </div>

      <form onSubmit={handleDelete} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {!codeSent ? (
          <button
            type="button"
            onClick={() => void sendCode()}
            disabled={submitting}
            style={{ padding: "8px 16px", alignSelf: "flex-start", cursor: "pointer" }}
          >
            {submitting ? "发送中…" : "发送验证码到我的邮箱"}
          </button>
        ) : (
          <>
            <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 14 }}>
              验证码（6 位数字）
              <input
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                inputMode="numeric"
                autoComplete="one-time-code"
                required
                style={{ padding: 8, border: "1px solid #d0d0d0", borderRadius: 6, font: "inherit", letterSpacing: 4, maxWidth: 220 }}
              />
            </label>

            <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
              <button
                type="submit"
                disabled={submitting || code.length !== 6}
                style={{
                  padding: "8px 16px",
                  cursor: "pointer",
                  background: "#b00020",
                  color: "#fff",
                  border: "none",
                  borderRadius: 6,
                }}
              >
                {submitting ? "注销中…" : "确认注销账号"}
              </button>
              <button
                type="button"
                onClick={() => void sendCode()}
                disabled={submitting}
                style={{ padding: "6px 0", cursor: "pointer", fontSize: 14, background: "none", border: "none", color: "#555" }}
              >
                重新发送验证码
              </button>
            </div>
          </>
        )}

        {error && (
          <p role="alert" style={{ color: "#b00020", fontSize: 14 }}>
            {error}
          </p>
        )}
        {notice && <p style={{ color: "#1a7f37", fontSize: 14 }}>{notice}</p>}
      </form>

      <p style={{ fontSize: 14 }}>
        <Link href="/" style={{ color: "#555", textDecoration: "underline" }}>
          返回首页
        </Link>
      </p>
    </div>
  );
}
