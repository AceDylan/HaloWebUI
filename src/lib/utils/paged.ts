// Long histories (精答, 讨论, 协作, the image studio's gallery and history) come a page at a time,
// newest first, and read on as you scroll. Lists whose items move on their own (a run being
// answered) refresh their first page only: these helpers fold that page into what is shown,
// without dropping the pages already scrolled to.

/** Where an item sits in a list sorted newest first: its time, then its id (both descending). */
export type PageKey = [number, string];

/** "<time>:<id>": the cursor the server reads to give the page after this item. */
export const cursorAfter = (key: PageKey): string => `${Math.floor(key[0])}:${key[1]}`;

/** True when `a` comes after `b` in a list sorted newest first. */
export const isAfter = (a: PageKey, b: PageKey): boolean =>
	a[0] < b[0] || (a[0] === b[0] && a[1] < b[1]);

/** The next page appended, without an item twice (one that moved meanwhile is not repeated). */
export const appendPage = <T>(shown: T[], page: T[], idOf: (item: T) => string): T[] => {
	const seen = new Set(shown.map(idOf));
	return [...shown, ...page.filter((item) => !seen.has(idOf(item)))];
};

/**
 * A fresh first page folded into what is shown: the page as it is now, then the items already
 * loaded that come after its last one. `headMore` false: the first page is the whole list.
 * Returns the list and whether more may follow it.
 */
export const mergeHead = <T>(
	shown: T[],
	head: T[],
	headMore: boolean,
	shownMore: boolean,
	idOf: (item: T) => string,
	keyOf: (item: T) => PageKey
): { items: T[]; more: boolean } => {
	if (!headMore || !head.length) return { items: head, more: headMore };
	const ids = new Set(head.map(idOf));
	const last = keyOf(head[head.length - 1]);
	const rest = shown.filter((item) => !ids.has(idOf(item)) && isAfter(keyOf(item), last));
	// nothing loaded past the first page yet: what follows it is still to be read
	return { items: [...head, ...rest], more: rest.length ? shownMore : true };
};
