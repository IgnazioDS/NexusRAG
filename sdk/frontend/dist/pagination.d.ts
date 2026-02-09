export interface PaginationPage<T> {
    items: T[];
    page: {
        next_cursor?: string | null;
        has_more: boolean;
    };
}
export declare function buildQuery(params: Record<string, string | number | undefined | null>): string;
export declare function paginate<T>(fetchPage: (cursor?: string | null) => Promise<PaginationPage<T>>): AsyncGenerator<T[], void, void>;
