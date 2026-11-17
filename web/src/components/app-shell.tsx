"use client";

import { useCallback, useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Sidebar } from "@/components/sidebar";
import { SidebarRefreshContext } from "@/components/sidebar-refresh";
import { WorkspaceContext, type PreviewContent, type PreviewSelection } from "@/components/workspace-context";
import { DocumentPreview } from "@/components/document-preview";
import { SettingsDialog } from "@/components/settings-dialog";
import { Icon } from "@/components/icon";
import { getChunkContext, getDocumentContent, HttpError, logout, me } from "@/lib/api";

const PUBLIC_PAGES = ["/login", "/register", "/verify", "/forgot"];
const subscribeViewport = (callback: () => void) => {
  const media = window.matchMedia("(max-width: 760px)");
  media.addEventListener("change", callback);
  return () => media.removeEventListener("change", callback);
};

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  if (PUBLIC_PAGES.includes(pathname)) return <>{children}</>;
  return <WorkspaceShell>{children}</WorkspaceShell>;
}

function WorkspaceShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const narrow = useSyncExternalStore(subscribeViewport, () => window.matchMedia("(max-width: 760px)").matches, () => false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean | null>(null);
  const collapsed = sidebarCollapsed ?? narrow;
  const [sessionsVersion, setSessionsVersion] = useState(0);
  const [chatKey, setChatKey] = useState(0);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [username, setUsername] = useState<string | null | undefined>(undefined);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [chatCollapsed, setChatCollapsed] = useState(false);
  const [previewCollapsed, setPreviewCollapsed] = useState(false);
  const [selection, setSelection] = useState<PreviewSelection | null>(null);
  const [content, setContent] = useState<PreviewContent | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const previewRequest = useRef(0);
  const isPublicPage = PUBLIC_PAGES.includes(pathname);
  const chatPage = pathname === "/" || pathname.startsWith("/sessions/");

  useEffect(() => {
    if (isPublicPage) return;
    let cancelled = false;
    me().then(
      (u) => { if (!cancelled) setUsername(u.username); },
      (e) => {
        if (cancelled) return;
        if (e instanceof HttpError && e.status === 401) {
          setUsername(null);
          router.replace("/login");
        } else setUsername("");
      },
    );
    return () => { cancelled = true; };
  }, [isPublicPage, router]);
  useEffect(() => () => { previewRequest.current++; }, []);

  const notifySessionsChanged = useCallback(() => setSessionsVersion((v) => v + 1), []);
  const requestNewChat = useCallback(() => {
    setActiveSessionId(null);
    setChatKey((k) => k + 1);
    setChatCollapsed(false);
    setSelection(null);
    setContent(null);
    previewRequest.current++;
    if (window.matchMedia("(max-width: 760px)").matches) setSidebarCollapsed(true);
    router.push("/");
  }, [router]);
  const handleLogout = useCallback(async () => {
    await logout();
    previewRequest.current++;
    setSelection(null);
    setContent(null);
    setSettingsOpen(false);
    router.replace("/login");
    router.refresh();
  }, [router]);
  const openDocument = useCallback(async (next: PreviewSelection) => {
    const requestId = ++previewRequest.current;
    setSelection(next);
    setContent(null);
    setPreviewError(null);
    setPreviewLoading(true);
    setPreviewCollapsed(false);
    if (window.matchMedia("(max-width: 760px)").matches) setSidebarCollapsed(true);
    try {
      let result = await getDocumentContent(next.id);
      if (next.chunkId && !result.items.some((item) => item.chunk_id === next.chunkId)) result = await getChunkContext(next.chunkId);
      if (previewRequest.current !== requestId) return;
      setContent({ ...result, items: result.items.map((item) => ({ ...item, is_target: next.chunkIds?.includes(item.chunk_id) || item.chunk_id === next.chunkId })) });
    } catch (e) {
      if (previewRequest.current === requestId) setPreviewError(e instanceof Error ? e.message : "文档加载失败");
    } finally {
      if (previewRequest.current === requestId) setPreviewLoading(false);
    }
  }, []);
  const closeDocument = useCallback((id: string) => {
    setSelection((current) => {
      if (current?.id !== id) return current;
      previewRequest.current++;
      return null;
    });
  }, []);

  if (isPublicPage) return <>{children}</>;
  if (username === undefined || username === null) return <div className="app-loading">{username === null ? "正在跳转到登录页…" : "正在打开知识空间…"}</div>;
  const hiddenChat = chatPage && chatCollapsed;
  return <SidebarRefreshContext.Provider value={{ sessionsVersion, notifySessionsChanged, requestNewChat, activeSessionId, setActiveSessionId }}>
    <WorkspaceContext.Provider value={{ openDocument, closeDocument }}>
      <div className={`app-workspace ${selection && !previewCollapsed ? "has-document" : ""} ${hiddenChat ? "chat-is-collapsed" : ""}`}>
        <Sidebar collapsed={collapsed} onToggle={() => setSidebarCollapsed(!collapsed)} username={username || null} onSettings={() => setSettingsOpen(true)} onNavigate={() => { setChatCollapsed(false); if (narrow) setSidebarCollapsed(true); }} />
        {narrow && !collapsed && <button type="button" className="sidebar-backdrop" aria-label="关闭侧边栏" onClick={() => setSidebarCollapsed(true)} />}
        <main className={`conversation-pane ${hiddenChat ? "is-collapsed" : ""}`} aria-label="对话区域">
          {chatPage && <div className="workspace-toolbar"><span className="workspace-label"><span className="online-dot" />知识工作空间</span><div className="toolbar-actions">{selection && <button type="button" className="text-button mobile-chat-return" onClick={() => setPreviewCollapsed(true)}>返回对话</button>}<button className="icon-button" type="button" aria-expanded={!hiddenChat} aria-label={hiddenChat ? "展开对话" : "收起对话"} title={hiddenChat ? "展开对话" : "收起对话"} onClick={() => setChatCollapsed((v) => !v)}><Icon name="chat" /></button></div></div>}
          <div key={chatKey} className="conversation-content" hidden={hiddenChat}>{children}</div>
          {hiddenChat && <button type="button" className="collapsed-chat" onClick={() => setChatCollapsed(false)}><Icon name="chat" /><span>展开对话</span></button>}
        </main>
        {selection && <DocumentPreview selection={selection} content={content} loading={previewLoading} error={previewError} collapsed={previewCollapsed} onToggle={() => setPreviewCollapsed((v) => !v)} onRetry={() => openDocument(selection)} />}
      </div>
      {settingsOpen && <SettingsDialog username={username || null} onClose={() => setSettingsOpen(false)} onLogout={handleLogout} />}
    </WorkspaceContext.Provider>
  </SidebarRefreshContext.Provider>;
}
