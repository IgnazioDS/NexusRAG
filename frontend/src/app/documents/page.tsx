import { TopBar } from "@/components/layout/TopBar";
import { DocumentsTable } from "@/components/documents/DocumentsTable";

export default function DocumentsPage() {
  return (
    <>
      <TopBar title="Documents" />
      <div className="dot-grid flex-1 overflow-y-auto">
        <div className="mx-auto max-w-6xl p-6">
          <DocumentsTable />
        </div>
      </div>
    </>
  );
}
