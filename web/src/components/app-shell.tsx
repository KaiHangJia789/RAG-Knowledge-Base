"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Sidebar } from "@/components/sidebar";
import { SidebarRefreshContext } from "@/components/sidebar-refresh";
import { HttpError, logout, me } from "@/lib/api";

/** 无需登录即可访问的页面：不显示侧边栏，也不调用 /auth/me */
const PUBLIC_PAGES = ["/login", "/register", "/verify", "/forgot"];

/**
 * 整体布局：左侧栏（新建会话、会话历史、文档、用户信息）+ 右侧聊天区。
 *
 * 登录：
 * - /login 页面不显示侧边栏。
 * - 其他页面挂载时调用 /auth/me；返回 401（cookie 过期或无效）则跳转登录页。
 *   proxy.ts 只检查 cookie 是否存在，这里才是对失效登录的处理。
 *
 * 「新建会话」只做两件事，且都是 Next 能正确处理的操作：
 * 1. router.push("/") —— 真正的路由导航。在历史会话页时会换掉页面组件；
 * 2. chatKey 递增 —— 让页面内容整体重新挂载，清空聊天区状态。
 *
 * 不使用 window.history.replaceState 改地址栏：它绕过 Next 的路由，
 * 与同时进行的 router.push 相互竞争，会导致导航被取消（历史会话页点新建会话无效）。
 */
export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [collapsed, setCollapsed] = useState(false);
  const [sessionsVersion, setSessionsVersion] = useState(0);
  const [chatKey, setChatKey] = useState(0);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  // undefined = 还在检查登录；null = 未登录（已跳转）；字符串 = 当前用户名
  const [username, setUsername] = useState<string | null | undefined>(undefined);
  const isPublicPage = PUBLIC_PAGES.includes(pathname);

  useEffect(() => {
    if (isPublicPage) return;
    let cancelled = false;
    me().then(
      (u) => {
        if (!cancelled) setUsername(u.username);
      },
      (e) => {
        if (cancelled) return;
        if (e instanceof HttpError && e.status === 401) {
          setUsername(null);
          router.replace("/login");
        } else {
          // 网络等其他错误：仍显示页面，由各区域自己报错
          setUsername("");
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [isPublicPage, router]);

  const notifySessionsChanged = useCallback(() => setSessionsVersion((v) => v + 1), []);

  const requestNewChat = useCallback(() => {
    setActiveSessionId(null);
    setChatKey((k) => k + 1);
    router.push("/");
  }, [router]);

  const handleLogout = useCallback(async () => {
    try {
      await logout();
    } finally {
      // 无论请求是否成功，都回到登录页；cookie 若仍在，proxy 会在下次访问时处理
      router.replace("/login");
      router.refresh();
    }
  }, [router]);

  if (isPublicPage) {
    return <>{children}</>;
  }

  if (username === undefined || username === null) {
    return <div style={{ padding: 24, color: "#666" }}>{username === null ? "正在跳转到登录页…" : "加载中…"}</div>;
  }

  return (
    <SidebarRefreshContext.Provider
      value={{
        sessionsVersion,
        notifySessionsChanged,
        requestNewChat,
        activeSessionId,
        setActiveSessionId,
      }}
    >
      <div
        style={{
          display: "flex",
          height: "100vh",
          overflow: "hidden",
          background: "#fff",
          color: "#171717",
        }}
      >
        <Sidebar
          collapsed={collapsed}
          onToggle={() => setCollapsed((c) => !c)}
          username={username || null}
          onLogout={handleLogout}
        />
        <main
          style={{
            flex: 1,
            minWidth: 0,
            height: "100vh",
            display: "flex",
            flexDirection: "column",
          }}
        >
          <div key={chatKey} style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>
            {children}
          </div>
        </main>
      </div>
    </SidebarRefreshContext.Provider>
  );
}
