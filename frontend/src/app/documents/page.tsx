import { TopBar } from "@/components/layout/TopBar";
import { DocumentsTable } from "@/components/documents/DocumentsTable";

export const metadata = { title: "Documents" };

export default function DocumentsPage() {
  return (
    <>
      <TopBar
        title="Documents"
        description="Indexed corpora, document statuses, reindex actions"
      />
      <div className="dot-grid flex-1 overflow-y-auto">
        <div className="page-enter mx-auto max-w-6xl p-6">
          <DocumentsTable />
        </div>
      </div>
    </>
  );
}
