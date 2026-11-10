export type ApiResponse<T> = {
  code: number;
  message: string;
  data: T;
};

export type Paginated<T> = {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
};

export type Document = {
  id: string;
  filename: string;
  file_type: string;
  file_size: number;
  status: string;
  created_at: string;
};

export type Citation = {
  index: number;
  chunk_id: string;
  document_id: string;
  filename: string;
  chunk_index: number;
  score: number;
  text: string;
  page_number: number | null;
};

export type ChunkItem = {
  chunk_id: string;
  chunk_index: number;
  text: string;
  page_number: number | null;
  is_target: boolean;
};

export type ChunkContext = {
  document_id: string;
  filename: string;
  chunk_strategy: string;
  items: ChunkItem[];
};

export type RagAnswer = {
  question: string;
  answer: string;
  citations: Citation[];
  refused: boolean;
  refusal_reason: string | null;
  latency_ms: number;
  trace_url: string | null;
};

export type SessionMessage = {
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  citations: Citation[];
  refused: boolean;
  refusal_reason: string | null;
  trace_url: string | null;
};

export type SessionSummary = {
  id: string;
  title: string;
  message_count: number;
  created_at: string;
  updated_at: string;
};

export type SessionDetail = SessionSummary & {
  messages: SessionMessage[];
};

/** 带 HTTP 状态码的错误，便于区分「未登录」等需要特殊处理的情况 */
export class HttpError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/v1${path}`, init);
  if (!res.ok) {
    // 优先展示后端给出的业务消息（如「会话不存在」），取不到再回退到状态码
    let message = `请求失败：${res.status}`;
    try {
      const err = (await res.json()) as { message?: string };
      if (err.message) message = err.message;
    } catch {
      // 非 JSON 响应（如网关错误页）保留状态码信息
    }
    throw new HttpError(message, res.status);
  }
  const body = (await res.json()) as ApiResponse<T>;
  return body.data;
}

export function listDocuments(page = 1, pageSize = 20) {
  return request<Paginated<Document>>(
    `/documents?page=${page}&page_size=${pageSize}`,
  );
}

// 上传文档：由后端解析切分，PDF/MD/TXT 会自动入索引。不设置 Content-Type，由浏览器补上 multipart 边界
export function uploadDocument(file: File) {
  const form = new FormData();
  form.append("file", file);
  return request<Document>("/upload", { method: "POST", body: form });
}

export function deleteDocument(id: string) {
  return request<unknown>(`/documents/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

// 引用定位：取被引用的 chunk 及前后相邻块，目标块由 is_target 标出
export function getChunkContext(chunkId: string) {
  return request<ChunkContext>(
    `/qa/chunks/${encodeURIComponent(chunkId)}?before=2&after=2`,
  );
}

export function askQuestion(question: string, sessionId?: string) {
  return request<RagAnswer>("/qa/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(
      sessionId ? { question, session_id: sessionId } : { question },
    ),
  });
}

export function listSessions(page = 1, pageSize = 20) {
  return request<Paginated<SessionSummary>>(
    `/sessions?page=${page}&page_size=${pageSize}`,
  );
}

export function createSession() {
  return request<SessionSummary>("/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
}

export function getSession(id: string) {
  return request<SessionDetail>(`/sessions/${encodeURIComponent(id)}`);
}

export function deleteSession(id: string) {
  return request<unknown>(`/sessions/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export type AuthUser = { username: string };

export function login(username: string, password: string) {
  return request<AuthUser>("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
}

export function logout() {
  return request<unknown>("/auth/logout", { method: "POST" });
}

/** 当前登录用户；未登录时抛出 status 为 401 的 HttpError */
export function me() {
  return request<AuthUser>("/auth/me");
}

export function register(email: string, password: string) {
  return request<unknown>("/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
}

export function verifyEmail(token: string) {
  if (!token) {
    return Promise.reject(new Error("验证链接不完整，请使用邮件中的完整链接"));
  }
  return request<unknown>("/auth/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
}

export function resendVerification(email: string) {
  return request<unknown>("/auth/resend-verification", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
}

/** 找回密码第一步：向注册邮箱发送验证码（对外不区分邮箱是否存在） */
export function forgotPassword(email: string) {
  return request<unknown>("/auth/password/forgot", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
}

/** 找回密码第二步：验证码 + 新密码 */
export function resetPassword(email: string, code: string, newPassword: string) {
  return request<unknown>("/auth/password/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, code, new_password: newPassword }),
  });
}

/** 注销账号第一步：向本人邮箱发送验证码（需登录） */
export function requestDeleteCode() {
  return request<unknown>("/auth/account/delete-code", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
}

/** 注销账号第二步：验证码确认。成功后服务端会清除登录 cookie */
export function deleteAccount(code: string) {
  return request<unknown>("/auth/account/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
}
