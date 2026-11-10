import { ChatView } from "@/components/chat-view";

/** 新会话：第一次提问时自动创建并保存 */
export default function HomePage() {
  return <ChatView initialSessionId={null} />;
}
