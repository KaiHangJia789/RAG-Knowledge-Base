"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useSidebarRefresh } from "@/components/sidebar-refresh";
import {
  deleteDocument,
  deleteSession,
  listDocuments,
  listSessions,
  uploadDocument,
  type Document,
  type SessionSummary,
} from "@/lib/api";

// 与后端 settings.ALLOWED_EXTENSIONS 保持一致，选择文件时先过滤一遍
const ACCEPT = ".pdf,.txt,.md,.docx,.csv,.json,.xml";

export const SIDEBAR_WIDTH = 280;
export const SIDEBAR_COLLAPSED_WIDTH = 56;

const sectionTitle: React.CSSProperties = {
  fontSize: 12,
  color: "#888",
  padding: "12px 16px 6px",
};

export function Sidebar({
  collapsed,
  onToggle,
  username,
  onLogout,
}: {
  collapsed: boolean;
  onToggle: () => void;
  /** 当前登录用户名；null 表示未获取到（网络错误等） */
  username: string | null;
  onLogout: () => void;
}) {
  const pathname = usePathname();
  const { sessionsVersion, requestNewChat, activeSessionId } = useSidebarRefresh();
  // 历史会话页以地址中的 id 为准；在 "/" 首次提问后则以上下文中的 activeSessionId 为准
  const currentId = pathname.startsWith("/sessions/")
    ? pathname.slice("/sessions/".length)
    : activeSessionId;
  const [sessions, setSessions] = useState<SessionSummary[] | null>(null);
  const [docs, setDocs] = useState<Document[] | null>(null);
  const [docsVersion, setDocsVersion] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // 收起时不拉取数据，展开时重新拉取
  useEffect(() => {
    if (collapsed) return;
    let cancelled = false;
    listSessions(1, 50).then(
      (d) => {
        if (!cancelled) setSessions(d.items);
      },
      (e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "会话加载失败");
      },
    );
    return () => {
      cancelled = true;
    };
  }, [sessionsVersion, collapsed]);

  useEffect(() => {
    if (collapsed) return;
    let cancelled = false;
    listDocuments().then(
      (d) => {
        if (!cancelled) setDocs(d.items);
      },
      (e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "文档加载失败");
      },
    );
    return () => {
      cancelled = true;
    };
  }, [docsVersion, collapsed]);

  async function removeSession(id: string) {
    if (!window.confirm("确认删除该会话？删除后历史无法恢复。")) return;
    try {
      await deleteSession(id);
      setSessions((list) => list?.filter((s) => s.id !== id) ?? list);
      // 正在查看被删除的会话时，回到新会话页
      // 正在查看被删除的会话时，回到新会话
      if (currentId === id) requestNewChat();
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除失败");
    }
  }

  async function removeDocument(id: string) {
    if (!window.confirm("确认删除该文档？")) return;
    try {
      await deleteDocument(id);
      setDocsVersion((v) => v + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除失败");
    }
  }

  async function handleUpload(file: File) {
    setError(null);
    setUploading(true);
    try {
      await uploadDocument(file);
      setDocsVersion((v) => v + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : "上传失败");
    } finally {
      setUploading(false);
      // 清空 input，允许再次选择同一个文件
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  return (
    <aside
      style={{
        width: collapsed ? SIDEBAR_COLLAPSED_WIDTH : SIDEBAR_WIDTH,
        flexShrink: 0,
        height: "100vh",
        display: "flex",
        flexDirection: "column",
        borderRight: "1px solid #e5e5e5",
        background: "#fafafa",
        color: "#171717",
        transition: "width 0.2s",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: collapsed ? "center" : "space-between",
          padding: 12,
          gap: 8,
        }}
      >
        {!collapsed && <strong style={{ whiteSpace: "nowrap" }}>RAG 知识库</strong>}
        <button
          type="button"
          onClick={onToggle}
          aria-label={collapsed ? "展开侧边栏" : "收起侧边栏"}
          title={collapsed ? "展开侧边栏" : "收起侧边栏"}
          style={{ cursor: "pointer", padding: "2px 8px" }}
        >
          {collapsed ? "»" : "«"}
        </button>
      </div>

      <div style={{ padding: collapsed ? "0 8px" : "0 12px 8px" }}>
        {/* 用按钮而非 <Link href="/">：见 sidebar-refresh.tsx 中的说明 */}
        <button
          type="button"
          onClick={requestNewChat}
          title="新建会话"
          style={{
            width: "100%",
            padding: "8px 0",
            border: "1px solid #d0d0d0",
            borderRadius: 6,
            background: "#fff",
            color: "#171717",
            cursor: "pointer",
            whiteSpace: "nowrap",
          }}
        >
          {collapsed ? "＋" : "＋ 新建会话"}
        </button>
      </div>

      {!collapsed && (
        <div style={{ flex: 1, overflowY: "auto", minHeight: 0 }}>
          {error && (
            <p role="alert" style={{ color: "#b00020", padding: "0 16px", fontSize: 13 }}>
              {error}
            </p>
          )}

          <div style={sectionTitle}>会话历史</div>
          {sessions && sessions.length === 0 && (
            <p style={{ padding: "0 16px", fontSize: 13, color: "#888" }}>暂无会话</p>
          )}
          <ul style={{ listStyle: "none" }}>
            {sessions?.map((s) => {
              const active = currentId === s.id;
              return (
                <li
                  key={s.id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 4,
                    padding: "0 8px 0 12px",
                    background: active ? "#e8e8e8" : "transparent",
                  }}
                >
                  <Link
                    href={`/sessions/${s.id}`}
                    title={s.title}
                    style={{
                      flex: 1,
                      minWidth: 0,
                      padding: "6px 0",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                      color: "#171717",
                      textDecoration: "none",
                      fontSize: 14,
                    }}
                  >
                    {s.title}
                  </Link>
                  <button
                    type="button"
                    onClick={() => removeSession(s.id)}
                    aria-label={`删除会话 ${s.title}`}
                    title="删除"
                    style={{ border: "none", background: "none", cursor: "pointer", color: "#888" }}
                  >
                    ×
                  </button>
                </li>
              );
            })}
          </ul>

          <div style={{ ...sectionTitle, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span>文档</span>
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              style={{ fontSize: 12, padding: "2px 8px", cursor: uploading ? "wait" : "pointer" }}
            >
              {uploading ? "上传中…" : "＋ 上传"}
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept={ACCEPT}
              hidden
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleUpload(file);
              }}
            />
          </div>
          {docs && docs.length === 0 && (
            <p style={{ padding: "0 16px", fontSize: 13, color: "#888" }}>暂无文档</p>
          )}
          <ul style={{ listStyle: "none", padding: "0 12px" }}>
            {docs?.map((d) => (
              <li
                key={d.id}
                style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 0", fontSize: 13 }}
              >
                <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {d.filename}
                </span>
                <small style={{ color: "#888" }}>{d.status}</small>
                <button
                  type="button"
                  onClick={() => removeDocument(d.id)}
                  aria-label={`删除文档 ${d.filename}`}
                  title="删除"
                  style={{ border: "none", background: "none", cursor: "pointer", color: "#888" }}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 当前用户与退出登录 */}
      <div
        style={{
          borderTop: "1px solid #e5e5e5",
          padding: collapsed ? "12px 0" : "10px 16px",
          display: "flex",
          alignItems: "center",
          justifyContent: collapsed ? "center" : "space-between",
          gap: 8,
          fontSize: 13,
          color: "#555",
        }}
      >
        {collapsed ? (
          <button
            type="button"
            onClick={onLogout}
            title={`${username ?? "用户"} · 退出登录`}
            aria-label="退出登录"
            style={{ border: "none", background: "none", cursor: "pointer" }}
          >
            👤
          </button>
        ) : (
          <>
            <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {username ?? "未获取到用户信息"}
            </span>
            <button
              type="button"
              onClick={onLogout}
              style={{ fontSize: 12, padding: "2px 8px", cursor: "pointer", flexShrink: 0 }}
            >
              退出
            </button>
            <Link href="/account" style={{ fontSize: 12, color: "#888", flexShrink: 0 }}>
              注销
            </Link>
          </>
        )}
      </div>
    </aside>
  );
}
