"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { verifyEmail } from "@/lib/api";

type State =
  | { status: "pending" }
  | { status: "ok" }
  | { status: "error"; message: string };

export default function VerifyPage() {
  const [state, setState] = useState<State>({ status: "pending" });
  const started = useRef(false);

  useEffect(() => {
    // 开发模式下 effect 会执行两次；验证令牌只能使用一次，这里保证只请求一次
    if (started.current) return;
    started.current = true;
    const token = new URLSearchParams(window.location.search).get("token") ?? "";
    verifyEmail(token).then(
      () => setState({ status: "ok" }),
      (err: unknown) =>
        setState({ status: "error", message: err instanceof Error ? err.message : "验证失败" }),
    );
  }, []);

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
      <div
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
        <h1 style={{ fontSize: 20 }}>邮箱验证</h1>

        {state.status === "pending" && <p>正在验证…</p>}

        {state.status === "ok" && (
          <>
            <p style={{ color: "#1a7f37" }}>邮箱验证成功，现在可以登录了。</p>
            <Link href="/login">前往登录</Link>
          </>
        )}

        {state.status === "error" && (
          <>
            <p role="alert" style={{ color: "#b00020" }}>
              {state.message}
            </p>
            <p style={{ fontSize: 14 }}>
              链接可能已过期或已使用。可以到 <Link href="/login">登录页</Link> 重新发送验证邮件。
            </p>
          </>
        )}
      </div>
    </main>
  );
}
