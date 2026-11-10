"use client";

import { createContext, useContext } from "react";

/**
 * 侧边栏与聊天区之间的共享状态。
 * - sessionsVersion / notifySessionsChanged：聊天区有变化（新建、提问）后，侧边栏重新拉取会话列表
 * - requestNewChat：「新建会话」，由 AppShell 实现（清空聊天区并导航到 "/"）
 * - activeSessionId / setActiveSessionId：在 "/" 页面首次提问后，当前会话的 id。
 *   地址栏不随之改变（不用 replaceState，见 app-shell.tsx），侧边栏靠它高亮当前会话。
 *
 * 单独成文件，避免 AppShell 与 Sidebar 循环导入。
 */
export type SidebarRefresh = {
  sessionsVersion: number;
  notifySessionsChanged: () => void;
  requestNewChat: () => void;
  activeSessionId: string | null;
  setActiveSessionId: (id: string | null) => void;
};

export const SidebarRefreshContext = createContext<SidebarRefresh>({
  sessionsVersion: 0,
  notifySessionsChanged: () => {},
  requestNewChat: () => {},
  activeSessionId: null,
  setActiveSessionId: () => {},
});

export function useSidebarRefresh() {
  return useContext(SidebarRefreshContext);
}
