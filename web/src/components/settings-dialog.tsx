"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Icon } from "@/components/icon";
import { useTheme } from "@/components/theme-provider";

export function SettingsDialog({ username, onClose, onLogout }: { username: string | null; onClose: () => void; onLogout: () => Promise<void> }) {
  const ref = useRef<HTMLDialogElement>(null);
  const { theme, setTheme } = useTheme();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    return () => dialog?.close();
  }, []);
  return <dialog ref={ref} className="settings-dialog" onCancel={onClose} onClick={(event) => { if (event.target === event.currentTarget) onClose(); }} aria-labelledby="settings-title">
    <div className="settings-content">
      <header className="settings-header"><div><span className="eyebrow">你的工作空间</span><h2 id="settings-title">设置</h2></div><button className="icon-button" type="button" aria-label="关闭设置" onClick={onClose}><Icon name="close" /></button></header>
      <div className="settings-user"><span className="avatar">{username?.slice(0, 1).toUpperCase() || "U"}</span><div><strong>{username || "当前用户"}</strong><p className="muted">个人知识空间</p></div></div>
      <section className="settings-section"><h3>外观</h3><p className="muted">选择让你阅读更舒适的界面。</p><div className="theme-options">
        <button type="button" aria-pressed={theme === "dark"} className={`theme-option ${theme === "dark" ? "is-active" : ""}`} onClick={() => setTheme("dark")}><Icon name="moon" /><strong>深色</strong><span>黑底白字</span></button>
        <button type="button" aria-pressed={theme === "light"} className={`theme-option ${theme === "light" ? "is-active" : ""}`} onClick={() => setTheme("light")}><Icon name="sun" /><strong>浅色</strong><span>白底黑字</span></button>
      </div></section>
      <section className="settings-section"><h3>账号</h3>{error && <p role="alert" className="error-message">{error}</p>}<button className="settings-action" type="button" disabled={busy} onClick={async () => { setBusy(true); setError(null); try { await onLogout(); } catch (e) { setError(e instanceof Error ? e.message : "退出失败，请重试"); setBusy(false); } }}><Icon name="logout" /><span>{busy ? "正在退出…" : "退出登录"}</span></button><Link href="/account" className="settings-action danger-text" onClick={onClose}><Icon name="close" /><span>注销账号</span><small>需邮箱验证码确认</small></Link></section>
    </div>
  </dialog>;
}
