"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { verifyEmail } from "@/lib/api";
import { AuthLayout } from "@/components/auth-layout";

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
    <AuthLayout
      title={state.status === "ok" ? "邮箱验证成功" : state.status === "error" ? "验证未完成" : "验证你的邮箱"}
      subtitle="完成验证，让你的知识空间准备就绪。"
    >
      <div style={{ display: "grid", gap: 20 }}>
        {state.status === "pending" && <p role="status" className="muted">正在验证邮箱，请稍候…</p>}

        {state.status === "ok" && (
          <>
            <p role="status" className="success-message">邮箱已验证，现在可以登录了。</p>
            <Link href="/login" className="primary-button">前往登录</Link>
          </>
        )}

        {state.status === "error" && (
          <>
            <p role="alert" className="error-message">
              {state.message}
            </p>
            <p className="muted">
              链接可能已过期或已使用。请返回登录页，重新发送验证邮件。
            </p>
            <Link href="/login" className="secondary-button">返回登录</Link>
          </>
        )}
      </div>
    </AuthLayout>
  );
}
