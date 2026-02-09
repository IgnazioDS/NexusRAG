export function buildQuery(params) {
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
export async function* paginate(fetchPage) {
    let cursor = null;
    while (true) {
        const page = await fetchPage(cursor);
        yield page.items;
        if (!page.page.has_more || !page.page.next_cursor) {
            return;
        }
        cursor = page.page.next_cursor;
    }
}
