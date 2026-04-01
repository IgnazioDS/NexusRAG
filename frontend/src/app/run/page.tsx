import { TopBar } from "@/components/layout/TopBar";
import { ChatInterface } from "@/components/run/ChatInterface";

export default function RunPage() {
  return (
    <>
      <TopBar title="Try It — Live RAG" />
      <div className="flex flex-1 flex-col overflow-hidden">
        <ChatInterface />
      </div>
    </>
  );
}
