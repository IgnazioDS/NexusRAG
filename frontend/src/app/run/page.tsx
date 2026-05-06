import { TopBar } from "@/components/layout/TopBar";
import { ChatInterface } from "@/components/run/ChatInterface";

export const metadata = { title: "Try It" };

export default function RunPage() {
  return (
    <>
      <TopBar
        title="Try It"
        description="Live RAG query against /v1/run with token streaming"
      />
      <div className="flex flex-1 flex-col overflow-hidden">
        <ChatInterface />
      </div>
    </>
  );
}
