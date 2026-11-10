import { ChatView } from "@/components/chat-view";

/** 历史会话：加载已有消息，可以接着继续提问。key 保证切换会话时状态不串 */
export default async function SessionPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <ChatView key={id} initialSessionId={id} />;
}
