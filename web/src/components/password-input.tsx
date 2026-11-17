"use client";

import { useState, type CSSProperties, type InputHTMLAttributes } from "react";

/**
 * 带「显示/隐藏」眼睛按钮的密码输入框。
 *
 * 按钮始终渲染，不随表单提交、校验或请求状态变化而消失。
 * 不依赖浏览器原生的密码图标（它会在表单重绘后消失，且各浏览器表现不一）；
 * 同时在 globals.css 中隐藏原生图标，避免出现两个眼睛。
 */
export function PasswordInput(
  props: Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & { style?: CSSProperties },
) {
  const [visible, setVisible] = useState(false);
  const { style, className, ...rest } = props;

  return (
    <div className="password-field" style={{ position: "relative", display: "flex", alignItems: "center", minWidth: 0 }}>
      <input
        {...rest}
        type={visible ? "text" : "password"}
        className={["password-input", className].filter(Boolean).join(" ")}
        style={{
          ...style,
          width: "100%",
          minWidth: 0,
          paddingRight: 48,
        }}
      />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        aria-label={visible ? "隐藏密码" : "显示密码"}
        aria-pressed={visible}
        title={visible ? "隐藏密码" : "显示密码"}
        className="password-toggle"
        style={{
          position: "absolute",
          right: 6,
          top: "50%",
          transform: "translateY(-50%)",
          width: 36,
          height: 36,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          border: "none",
          background: "transparent",
          color: "var(--muted, var(--foreground))",
          borderRadius: 6,
          cursor: "pointer",
          padding: 0,
        }}
      >
        {visible ? <EyeOffIcon /> : <EyeIcon />}
      </button>
    </div>
  );
}

function EyeIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function EyeOffIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 19c-7 0-11-7-11-7a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 7 11 7a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
      <line x1="1" y1="1" x2="23" y2="23" />
    </svg>
  );
}
