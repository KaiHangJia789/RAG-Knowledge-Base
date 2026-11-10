"use client";

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { ChunkContextView } from "@/components/chunk-context-view";
import { useSidebarRefresh } from "@/components/sidebar-refresh";
import {
  askQuestion,
  createSession,
  getSession,
  type RagAnswer,
  type SessionMessage,
} from "@/lib/api";
import { useChunkLocate } from "@/lib/use-chunk-locate";

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
  };
}

/**
 * 聊天区。
 * - initialSessionId 为空：新会话，第一次提问时自动创建会话并更新地址栏
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
  const locate = useChunkLocate();
  const bottomRef = useRef<HTMLDivElement | null>(null);
  // 组件卸载后（例如点了「新建会话」），进行中的请求返回时不再写入状态或改地址栏
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

  // 只在消息数量变化时滚动到底部；定位面板的滚动由 ChunkContextView 自己处理
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages.length]);

  async function send() {
    const q = input.trim();
    if (!q || asking || loading) return;

    const isFirstTurn = messages.length === 0;
    setAsking(true);
    setError(null);
    locate.clear();
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
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      <header style={{ padding: "12px 24px", borderBottom: "1px solid #eee", flexShrink: 0 }}>
        <strong style={{ fontSize: 16 }}>{sessionId ? title || "会话" : "新会话"}</strong>
      </header>

      <div style={{ flex: 1, overflowY: "auto", minHeight: 0, padding: "16px 24px" }}>
        {loading && <p style={{ color: "#666" }}>加载中…</p>}

        {!loading && messages.length === 0 && (
          <p style={{ color: "#666" }}>
            输入问题开始对话。第一次提问后会自动保存到左侧的会话历史；在同一会话里追问时，会参考前文（检索仍只用本轮问题）。
          </p>
        )}

        {messages.map((m, i) => (
          <MessageItem key={`${i}-${m.timestamp}`} message={m} onLocate={locate.locate} />
        ))}

        {locate.chunkError && <p role="alert">{locate.chunkError}</p>}
        {locate.activeChunk && <ChunkContextView ctx={locate.activeChunk} />}
        <div ref={bottomRef} />
      </div>

      <div style={{ borderTop: "1px solid #eee", padding: "12px 24px", flexShrink: 0 }}>
        {error && <p role="alert" style={{ marginBottom: 8 }}>{error}</p>}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            send();
          }}
          style={{ display: "flex", gap: 8, alignItems: "flex-end" }}
        >
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入问题，Enter 发送，Shift+Enter 换行"
            maxLength={2000}
            rows={2}
            disabled={loading}
            style={{
              flex: 1,
              resize: "none",
              padding: 8,
              border: "1px solid #d0d0d0",
              borderRadius: 6,
              font: "inherit",
            }}
          />
          <button
            type="submit"
            disabled={asking || loading || !input.trim()}
            style={{ padding: "8px 16px", cursor: "pointer" }}
          >
            {asking ? "生成中…" : "发送"}
          </button>
        </form>
      </div>
    </div>
  );
}

function MessageItem({
  message,
  onLocate,
}: {
  message: SessionMessage;
  onLocate: (chunkId: string) => void;
}) {
  const isUser = message.role === "user";
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: isUser ? "flex-end" : "flex-start",
        marginBottom: 16,
      }}
    >
      <div
        style={{
          maxWidth: "80%",
          padding: "10px 14px",
          borderRadius: 8,
          background: isUser ? "#f0f0f0" : "#fff",
          border: isUser ? "none" : "1px solid #e5e5e5",
          whiteSpace: "pre-wrap",
        }}
      >
        {!isUser && message.refused && (
          <div style={{ color: "#8a6d00", fontSize: 13, marginBottom: 4 }}>（拒答）</div>
        )}
        {message.content}
      </div>

      {message.citations.length > 0 && (
        <ol style={{ maxWidth: "80%", marginTop: 6, paddingLeft: 20, fontSize: 13 }}>
          {message.citations.map((c, j) => (
            <li key={`${c.chunk_id}-${j}`} style={{ marginBottom: 2 }}>
              <button
                type="button"
                onClick={() => onLocate(c.chunk_id)}
                style={{
                  background: "none",
                  border: "none",
                  padding: 0,
                  color: "#0366d6",
                  cursor: "pointer",
                  textAlign: "left",
                  font: "inherit",
                }}
              >
                [{c.index}] {c.filename}
                {c.page_number != null && `（第 ${c.page_number} 页）`}：{c.text.slice(0, 80)}
              </button>
            </li>
          ))}
        </ol>
      )}

      {message.trace_url && (
        <a
          href={message.trace_url}
          target="_blank"
          rel="noreferrer"
          style={{ fontSize: 12, color: "#666", marginTop: 4 }}
        >
          查看 LangFuse Trace
        </a>
      )}
    </div>
  );
}
