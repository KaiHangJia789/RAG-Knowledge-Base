"use client";

import { useEffect, useRef } from "react";
import { Icon } from "@/components/icon";
import type { PreviewContent, PreviewSelection } from "@/components/workspace-context";

export function DocumentPreview({ selection, content, loading, error, collapsed, onToggle, onRetry }: {
  selection: PreviewSelection;
  content: PreviewContent | null;
  loading: boolean;
  error: string | null;
  collapsed: boolean;
  onToggle: () => void;
  onRetry: () => void;
}) {
  const targetRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!collapsed) targetRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [content, collapsed]);

  return <aside className={`document-pane ${collapsed ? "is-collapsed" : ""}`} aria-label="文档预览">
    <header className="pane-header">
      <div className="pane-title"><Icon name="file" /><div><span className="eyebrow">文档阅读</span><h2 title={selection.filename}>{selection.filename}</h2></div></div>
      <div className="toolbar-actions">{!collapsed && <button className="text-button preview-return" type="button" onClick={onToggle}>返回对话</button>}<button className="icon-button" type="button" onClick={onToggle} aria-label={collapsed ? "展开文档预览" : "收起文档预览"} aria-expanded={!collapsed} title={collapsed ? "展开文档预览" : "收起文档预览"}><Icon name="panel" /></button></div>
    </header>
    <div className="document-scroll" hidden={collapsed} aria-live="polite">
      {loading ? <div className="pane-notice">正在打开文档…</div> : error ? <div className="pane-notice"><p role="alert" className="error-message">{error}</p><button type="button" className="secondary-button" onClick={onRetry}>重试</button></div> : content?.items.length ? <>
        <p className="document-note">解析文本 · {content.items.length} 个片段{selection.chunkId ? " · 已定位引用片段" : ""}</p>
        {content.items.map((item) => <section className={`document-chunk ${item.is_target ? "is-target" : ""}`} key={item.chunk_id} ref={item.is_target ? targetRef : undefined}>
          <div className="chunk-meta">片段 {item.chunk_index + 1}{item.page_number != null ? ` · 第 ${item.page_number} 页` : ""}{item.is_target ? " · 当前引用" : ""}</div>
          <p>{item.text}</p>
        </section>)}
      </> : <div className="pane-notice"><Icon name="file" size={30} /><h3>暂时没有可预览的内容</h3><p className="muted">文档可能仍在解析，或该格式尚未生成可读文本。稍后重试。</p><button className="secondary-button" type="button" onClick={onRetry}>重新加载</button></div>}
    </div>
    {collapsed && <button type="button" className="collapsed-document" onClick={onToggle} title={selection.filename}><Icon name="file" /><span>展开文档</span></button>}
  </aside>;
}
