export interface PaginationPage<T> {
  items: T[];
  page: { next_cursor?: string | null; has_more: boolean };
}

export function buildQuery(params: Record<string, string | number | undefined | null>): string {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") {
      return;
    }
    query.set(key, String(value));
  });
  const qs = query.toString();
  return qs ? `?${qs}` : "";
}

export async function* paginate<T>(
  fetchPage: (cursor?: string | null) => Promise<PaginationPage<T>>,
): AsyncGenerator<T[], void, void> {
  let cursor: string | null | undefined = null;
  while (true) {
    const page = await fetchPage(cursor);
    yield page.items;
    if (!page.page.has_more || !page.page.next_cursor) {
      return;
    }
    cursor = page.page.next_cursor;
  }
}
