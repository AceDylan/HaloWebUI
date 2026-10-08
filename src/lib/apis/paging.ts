// The query of a list that comes a page at a time (精答, 讨论台): see utils/paged.ts.

export type PageQuery = {
	archived?: boolean;
	limit?: number;
	before?: string | null;
	/** Searches the title, the question, the answer and the assistant. */
	q?: string;
	/** `live`: the runs being answered (what the sidebar badge reads); `ended`: the others. */
	status?: 'live' | 'ended';
	/** false: no `total` (a refresh of the first page: the count was read with it already). */
	count?: boolean;
};

export const pageQuery = (opts: PageQuery = {}): string => {
	const params = new URLSearchParams();
	if (opts.archived) params.set('archived', 'true');
	if (opts.limit) params.set('limit', String(opts.limit));
	if (opts.before) params.set('before', opts.before);
	if (opts.q?.trim()) params.set('q', opts.q.trim());
	if (opts.status) params.set('status', opts.status);
	if (opts.count === false) params.set('count', 'false');
	const query = params.toString();
	return query ? `/?${query}` : '/';
};
