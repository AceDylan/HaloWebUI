import { describe, expect, it } from 'vitest';
import { appendPage, cursorAfter, isAfter, mergeHead, type PageKey } from './paged';

type Row = { id: string; at: number };
const row = (id: string, at: number): Row => ({ id, at });
const idOf = (r: Row) => r.id;
const keyOf = (r: Row): PageKey => [r.at, r.id];

describe('paged lists', () => {
	it('orders newest first, then by id, and spells the cursor the server reads', () => {
		expect(isAfter([5, 'a'], [6, 'a'])).toBe(true);
		expect(isAfter([6, 'a'], [6, 'b'])).toBe(true);
		expect(isAfter([6, 'b'], [6, 'a'])).toBe(false);
		expect(cursorAfter([1790000000.7, 'x-1'])).toBe('1790000000:x-1');
	});

	it('appends the next page without an item twice', () => {
		expect(
			appendPage([row('a', 3), row('b', 2)], [row('b', 2), row('c', 1)], idOf).map(idOf)
		).toEqual(['a', 'b', 'c']);
	});

	it('a fresh first page keeps the pages already read below it', () => {
		const shown = [row('a', 9), row('b', 8), row('c', 7), row('d', 6), row('e', 5)];
		// 'd' was answered meanwhile and moved to the top; 'a' is gone
		const head = [row('d', 10), row('b', 8)];
		const merged = mergeHead(shown, head, true, true, idOf, keyOf);
		expect(merged.items.map(idOf)).toEqual(['d', 'b', 'c', 'e']);
		expect(merged.more).toBe(true);
	});

	it('a first page that is the whole list replaces it', () => {
		const merged = mergeHead([row('a', 9), row('b', 8)], [row('b', 8)], false, true, idOf, keyOf);
		expect(merged).toEqual({ items: [row('b', 8)], more: false });
	});

	it('only the first page read so far: what follows it is still to come', () => {
		const merged = mergeHead(
			[row('a', 9), row('b', 8)],
			[row('a', 9), row('b', 8)],
			true,
			false,
			idOf,
			keyOf
		);
		expect(merged).toEqual({ items: [row('a', 9), row('b', 8)], more: true });
	});
});
