import { describe, expect, it } from 'vitest';
import { chatPromptKey, movePrompt, orderPrompts } from './prompt-order';

const key = (id: string) => id;

describe('personal prompt order', () => {
	it('preserves source order for old settings, empty lists and malformed values', () => {
		for (const saved of [undefined, null, {}, 'bad', [null, 4, '']]) {
			expect(orderPrompts(['b', 'a'], saved, key)).toEqual(['b', 'a']);
			expect(orderPrompts([], saved, key)).toEqual([]);
		}
	});

	it('ignores stale/duplicate IDs and appends new items without mutating input', () => {
		const items = ['a', 'b', 'c', 'd'];
		expect(orderPrompts(items, ['deleted', 'c', 'c', 'a'], key)).toEqual(['c', 'a', 'b', 'd']);
		expect(items).toEqual(['a', 'b', 'c', 'd']);
	});

	it('supports moving to top, up and down, including boundaries', () => {
		const ids = ['a', 'b', 'c'];
		expect(movePrompt(ids, 'c', 0)).toEqual(['c', 'a', 'b']);
		expect(movePrompt(ids, 'c', 1)).toEqual(['a', 'c', 'b']);
		expect(movePrompt(ids, 'a', 1)).toEqual(['b', 'a', 'c']);
		for (const [id, target] of [
			['a', -1],
			['c', 3],
			['missing', 0]
		] as const) {
			expect(movePrompt(ids, id, target)).toEqual(ids);
		}
		expect(movePrompt([], 'a', 0)).toEqual([]);
		expect(ids).toEqual(['a', 'b', 'c']);
	});

	it('survives prompt renames and supports slash-prefixed legacy commands', () => {
		expect(chatPromptKey({ id: 'stable', command: 'renamed' })).toBe('id:stable');
		expect(chatPromptKey({ command: '/legacy' })).toBe(chatPromptKey({ command: 'legacy' }));
		expect(chatPromptKey({ id: 'legacy' })).not.toBe(chatPromptKey({ command: 'legacy' }));
	});
});
