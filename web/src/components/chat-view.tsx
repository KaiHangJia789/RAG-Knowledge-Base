"use client";

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Icon } from "@/components/icon";
import { useWorkspace } from "@/components/workspace-context";
import { useSidebarRefresh } from "@/components/sidebar-refresh";
import {
  askQuestion,
  createSession,
  getSession,
  type RagAnswer,
  type SessionMessage,
} from "@/lib/api";

const SUPPORT_EXAMPLES = [
  "PDF 上传后无法检索，应该检查哪些环节？",
  "Docker 部署后出现 502，如何逐步排查？",
  "本机 HTTP 登录后仍提示未登录，如何检查 cookie 配置？",
];

const STATUS_LABELS = {
  answered: "已回答",
  partial: "部分可答",
  needs_clarification: "待补充信息",
  insufficient_evidence: "资料不足",
  conflicting_evidence: "资料存在冲突",
};

const TITLE_MAX_LEN = 30;
const SESSION_GONE_HINT = "该会话已不存在（可能已被删除），请重新发送以新建会话";

function userMessage(content: string): SessionMessage {
  return {
    role: "user",
    content,
    timestamp: new Date().toISOString(),
    citations: [],
    refused: false,
    refusal_reason: null,
    trace_url: null,
  };
}

function answerMessage(a: RagAnswer): SessionMessage {
  return {
    role: "assistant",
    content: a.answer,
    timestamp: new Date().toISOString(),
    citations: a.citations,
    refused: a.refused,
    refusal_reason: a.refusal_reason,
    trace_url: a.trace_url,
    answer_status: a.answer_status,
    clarifying_questions: a.clarifying_questions,
  };
}

/**
 * 聊天区。
 * - initialSessionId 为空：新会话，第一次提问时自动创建会话并高亮侧边栏
 * - initialSessionId 有值：加载该会话的历史，之后可继续提问
 * 页面切换会话时由外层用 key 重新挂载，状态不会串到另一个会话里。
 */
export function ChatView({ initialSessionId }: { initialSessionId: string | null }) {
  const { notifySessionsChanged, setActiveSessionId } = useSidebarRefresh();
  const [sessionId, setSessionId] = useState<string | null>(initialSessionId);
  const [title, setTitle] = useState<string>(initialSessionId ? "" : "新会话");
  const [messages, setMessages] = useState<SessionMessage[]>([]);
  const [loading, setLoading] = useState(initialSessionId !== null);
  const [input, setInput] = useState("");
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { openDocument } = useWorkspace();
  const bottomRef = useRef<HTMLDivElement | null>(null);
  // 组件卸载后（例如点了「新建会话」），进行中的请求返回时不再写入状态
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  useEffect(() => {
    if (!initialSessionId) return;
    let cancelled = false;
    getSession(initialSessionId).then(
      (d) => {
        if (cancelled) return;
        setTitle(d.title);
        setMessages(d.messages);
        setLoading(false);
      },
      (e) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "会话加载失败");
        setLoading(false);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [initialSessionId]);

  // 新消息和等待状态出现时滚动到底部，文档定位由右侧预览处理。
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages.length, asking]);

  async function send() {
    const q = input.trim();
    if (!q || asking || loading) return;

    const isFirstTurn = messages.length === 0;
    setAsking(true);
    setError(null);
    setInput("");
    setMessages((m) => [...m, userMessage(q)]);

    try {
      let sid = sessionId;
      if (!sid) {
        const created = await createSession();
        sid = created.id;
        if (!alive.current) {
          // 已点了「新建会话」：这个会话仍然保存了（侧边栏会看到），但不再显示在当前页面
          notifySessionsChanged();
          return;
        }
        setSessionId(sid);
        // 不改地址栏（改了会与 Next 路由冲突）；侧边栏通过 activeSessionId 高亮当前会话
        setActiveSessionId(sid);
      }
      const answer = await askQuestion(q, sid);
      if (!alive.current) {
        notifySessionsChanged();
        return;
      }
      setMessages((m) => [...m, answerMessage(answer)]);
      if (isFirstTurn) setTitle(q.slice(0, TITLE_MAX_LEN));
      notifySessionsChanged();
    } catch (e) {
      if (!alive.current) return;
      // 失败时撤回刚加的问题气泡，把内容放回输入框，方便重发
      setMessages((m) => m.slice(0, -1));
      setInput(q);
      const msg = e instanceof Error ? e.message : "问答失败";
      if (msg.includes("会话不存在")) {
        setSessionId(null);
        setError(SESSION_GONE_HINT);
      } else {
        setError(msg);
      }
    } finally {
      if (alive.current) setAsking(false);
    }
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    // 中文输入法组合期间的回车是选词，不应发送
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send();
    }
  }

  return (
    <div className="chat-view">
      <header className="chat-heading"><span>{sessionId ? title || "会话" : "新会话"}</span><span className="chat-mode">基于你的知识库</span></header>

      <div className="chat-scroll"><div className="chat-inner">
        {loading && <p className="muted">加载中…</p>}

        {!loading && messages.length === 0 && (
          <section className="chat-welcome" aria-label="技术支持知识助手">
            <span className="welcome-emblem"><Icon name="book" size={29} /></span>
            <span className="eyebrow">从资料到答案</span>
            <h1>让知识，回应你的问题。</h1>
            <p className="welcome-description">
              基于产品文档解答使用、部署和排障问题，提供可定位的引用。同一会话中可以继续追问。
            </p>
            <p className="welcome-hint">
              请说明产品、版本、部署方式和脱敏错误信息。示例需先导入 RAG Knowledge Base 示范资料；助手无法直接查看或操作服务器。
            </p>
            <div className="example-list" aria-label="示例问题">
              {SUPPORT_EXAMPLES.map((question, index) => (
                <button className="example-button" key={question} type="button" onClick={() => setInput(question)}>
                  <span className="example-number">0{index + 1}</span><span><strong>{["文档与检索", "部署与排障", "账号与登录"][index]}</strong><span>{question}</span></span><Icon name="chevron" size={16} />
                </button>
              ))}
            </div>
          </section>
        )}

        {messages.map((m, i) => (
          <MessageItem key={`${i}-${m.timestamp}`} message={m} onLocate={(citation) => openDocument({ id: citation.document_id, filename: citation.filename, chunkId: citation.chunk_id, chunkIds: m.citations.filter((item) => item.document_id === citation.document_id).map((item) => item.chunk_id) })} />
        ))}

        {asking && <div className="message is-assistant" role="status" aria-live="polite">
          <div className="message-author"><span className="assistant-mark"><Icon name="book" size={14} /></span>知序</div>
          <div className="thinking-indicator"><span className="thinking-spinner" aria-hidden="true" /><span>正在思考…</span></div>
        </div>}

        <div ref={bottomRef} />
      </div></div>

      <div className="composer-wrap">
        {error && <p role="alert" className="error-message composer-error">{error}</p>}
        <form className="composer" onSubmit={(e) => { e.preventDefault(); void send(); }}>
          <textarea value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={handleKeyDown}
            aria-label="技术支持问题" placeholder="描述你的问题，或选择上方示例开始…" maxLength={2000} rows={2} disabled={loading} />
          <button className="send-button" type="submit" disabled={asking || loading || !input.trim()} aria-label={asking ? "生成中" : "发送问题"} title="发送问题"><Icon name="arrow" size={20} /></button>
        </form>
        <p className="composer-hint">{asking ? "正在查阅资料并生成回答…" : "Enter 发送 · Shift + Enter 换行 · 回答请结合原文核对"}</p>
      </div>
    </div>
  );
}

function MessageItem({ message, onLocate }: {
  message: SessionMessage;
  onLocate: (citation: SessionMessage["citations"][number]) => void;
}) {
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const isUser = message.role === "user";
  const sources = message.citations.filter((citation, index, all) => all.findIndex((item) => item.document_id === citation.document_id) === index);
  return <article className={`message ${isUser ? "is-user" : "is-assistant"}`}>
    <div className="message-author">{isUser ? "你" : <><span className="assistant-mark"><Icon name="book" size={14} /></span>知序</>}</div>
    <div className="message-bubble">
      {!isUser && (message.answer_status || message.refused) && <span className="answer-status">{message.answer_status ? STATUS_LABELS[message.answer_status] : "资料不足"}</span>}
      <div className="message-text">{message.content}</div>
      {!isUser && !!message.clarifying_questions?.length && <ol className="clarifying-questions" aria-label="需要补充的信息">{message.clarifying_questions.map((question, index) => <li key={index}>{question}</li>)}</ol>}
    </div>
    {sources.length > 0 && <div className="message-sources">
      <button className="source-toggle text-button" type="button" onClick={() => setSourcesOpen((v) => !v)} aria-expanded={sourcesOpen}><Icon name="file" size={14} />{sourcesOpen ? "收起原文定位" : "查看原文定位"}<span>{sources.length}</span><Icon name="chevron" size={12} style={{ transform: sourcesOpen ? "rotate(90deg)" : undefined }} /></button>
      {sourcesOpen && <ul className="source-files">{sources.map((citation) => <li key={citation.document_id}><button type="button" onClick={() => onLocate(citation)} title={`在右侧查看 ${citation.filename}`}><Icon name="file" size={14} /><span>{citation.filename}</span></button></li>)}</ul>}
    </div>}
    {message.trace_url && <a className="trace-link" href={message.trace_url} target="_blank" rel="noreferrer">查看 Langfuse Trace ↗</a>}
  </article>;
}
