"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { useSidebarRefresh } from "@/components/sidebar-refresh";
import { useWorkspace } from "@/components/workspace-context";
import { Icon } from "@/components/icon";
import { UploadDialog } from "@/components/upload-dialog";
import { deleteDocument, deleteSession, listDocuments, listSessions, type Document, type SessionSummary } from "@/lib/api";

const STATUS: Record<string, string> = { ready: "已就绪", uploaded: "已上传", parsing: "解析中", chunking: "处理中", failed: "处理失败" };

export function Sidebar({ collapsed, onToggle, username, onSettings, onNavigate }: {
  collapsed: boolean; onToggle: () => void; username: string | null; onSettings: () => void; onNavigate: () => void;
}) {
  const pathname = usePathname();
  const { sessionsVersion, requestNewChat, activeSessionId } = useSidebarRefresh();
  const { openDocument, closeDocument } = useWorkspace();
  const currentId = pathname.startsWith("/sessions/") ? pathname.slice("/sessions/".length) : activeSessionId;
  const [sessions, setSessions] = useState<SessionSummary[] | null>(null);
  const [docs, setDocs] = useState<Document[] | null>(null);
  const [sessionsOpen, setSessionsOpen] = useState(true);
  const [docsOpen, setDocsOpen] = useState(true);
  const [docsVersion, setDocsVersion] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    listSessions(1, 50).then((d) => { if (!cancelled) setSessions(d.items); }, (e) => { if (!cancelled) setError(e instanceof Error ? e.message : "会话加载失败"); });
    return () => { cancelled = true; };
  }, [sessionsVersion]);
  useEffect(() => {
    let cancelled = false;
    listDocuments(1, 100).then((d) => { if (!cancelled) setDocs(d.items); }, (e) => { if (!cancelled) setError(e instanceof Error ? e.message : "文档加载失败"); });
    return () => { cancelled = true; };
  }, [docsVersion]);
  async function removeSession(id: string) {
    if (!window.confirm("确认删除该会话？删除后历史无法恢复。")) return;
    try {
      await deleteSession(id);
      setSessions((list) => list?.filter((s) => s.id !== id) ?? list);
      if (currentId === id) requestNewChat();
    } catch (e) { setError(e instanceof Error ? e.message : "删除失败"); }
  }
  async function removeDocument(id: string) {
    if (!window.confirm("确认删除该文档？")) return;
    try { await deleteDocument(id); closeDocument(id); setDocsVersion((v) => v + 1); }
    catch (e) { setError(e instanceof Error ? e.message : "删除失败"); }
  }

  return <aside className={`sidebar ${collapsed ? "is-collapsed" : ""}`} aria-label="知识库导航">
    <header className="sidebar-brand"><Link href="/" className="brand-name" onClick={onNavigate}><span className="brand-symbol"><Icon name="book" size={19} /></span>{!collapsed && <span>知序 <small>RAG</small></span>}</Link><button className="icon-button" type="button" onClick={onToggle} aria-label={collapsed ? "展开侧边栏" : "收起侧边栏"} aria-expanded={!collapsed} title={collapsed ? "展开侧边栏" : "收起侧边栏"}><Icon name="panel" size={17} /></button></header>
    <div className="new-chat-wrap"><button className="new-chat-button" type="button" onClick={requestNewChat} title="新建会话"><Icon name="plus" />{!collapsed && <span>新建会话</span>}</button></div>
    {uploadOpen && <UploadDialog onClose={() => setUploadOpen(false)} onUploaded={() => { setDocsOpen(true); setDocsVersion((value) => value + 1); }} />}
    <div className="sidebar-scroll" hidden={collapsed}>
      {error && <p role="alert" className="sidebar-error error-message">{error}</p>}
      <section className="nav-section"><div className="nav-section-heading"><button type="button" className="section-toggle" onClick={() => setSessionsOpen((v) => !v)} aria-expanded={sessionsOpen} aria-controls="session-list"><Icon name="chat" size={15} /><span>会话历史</span><small>{sessions?.length ?? ""}</small><Icon name="chevron" size={13} style={{ transform: sessionsOpen ? "rotate(90deg)" : undefined }} /></button></div>
        <ul id="session-list" className="nav-list" hidden={!sessionsOpen}>
          {sessions === null ? <li className="nav-empty">正在加载…</li> : sessions.length === 0 ? <li className="nav-empty">从一个问题开始吧</li> : sessions.map((s) => <li key={s.id} className={`nav-row ${currentId === s.id ? "is-active" : ""}`}><Link className="nav-item" href={`/sessions/${s.id}`} title={s.title} onClick={onNavigate}>{s.title || "新会话"}</Link><button type="button" className="nav-delete" aria-label={`删除会话 ${s.title}`} title="删除会话" onClick={() => void removeSession(s.id)}><Icon name="close" size={13} /></button></li>)}
        </ul>
      </section>
      <section className="nav-section"><div className="nav-section-heading"><button type="button" className="section-toggle" onClick={() => setDocsOpen((v) => !v)} aria-expanded={docsOpen} aria-controls="document-list"><Icon name="file" size={15} /><span>文档</span><small>{docs?.length ?? ""}</small><Icon name="chevron" size={13} style={{ transform: docsOpen ? "rotate(90deg)" : undefined }} /></button><button className="icon-button upload-button" type="button" onClick={() => setUploadOpen(true)} aria-label="上传文档" title="上传文档（支持批量）"><Icon name="upload" size={15} /></button></div>
        <ul id="document-list" className="nav-list" hidden={!docsOpen}>
          {docs === null ? <li className="nav-empty">正在加载…</li> : docs.length === 0 ? <li className="nav-empty">上传资料，让答案有据可依</li> : docs.map((d) => <li className="nav-row document-row" key={d.id}><button type="button" className="nav-item document-link" title={`查看 ${d.filename}`} onClick={() => openDocument({ id: d.id, filename: d.filename })}><Icon name="file" size={15} /><span>{d.filename}<small>{STATUS[d.status] ?? d.status}</small></span></button><button className="nav-delete" type="button" aria-label={`删除文档 ${d.filename}`} title="删除文档" onClick={() => void removeDocument(d.id)}><Icon name="close" size={13} /></button></li>)}
        </ul>
      </section>
    </div>
    {collapsed && <div className="sidebar-rail"><button type="button" className="icon-button" aria-label="查看会话历史" title="会话历史" onClick={onToggle}><Icon name="chat" /></button><button type="button" className="icon-button" aria-label="查看文档列表" title="文档" onClick={onToggle}><Icon name="file" /></button><button type="button" className="icon-button" aria-label="上传文档" title="上传文档（支持批量）" onClick={() => setUploadOpen(true)}><Icon name="upload" /></button></div>}
    <footer className="sidebar-footer"><button type="button" className="user-settings" onClick={onSettings} aria-label="设置" title="设置"><span className="avatar">{username?.slice(0, 1).toUpperCase() || "U"}</span>{!collapsed && <><span className="user-details"><strong>{username || "当前用户"}</strong><small>个人空间</small></span><Icon name="settings" size={18} /></>}</button></footer>
  </aside>;
}
