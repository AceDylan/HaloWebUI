import { describe, expect, it } from 'vitest';

import { commonPrefixLength, splitStreamText } from './stream-text';

describe('splitStreamText', () => {
	it('keeps the settled head as plain text and keys each fading character by position', () => {
		expect(splitStreamText('你好，世界', 3)).toEqual({
			settledText: '你好，',
			tail: [
				{ index: 3, char: '世' },
				{ index: 4, char: '界' }
			]
		});
	});

	it('clamps the settled length to the text', () => {
		expect(splitStreamText('abc', 10)).toEqual({ settledText: 'abc', tail: [] });
		expect(splitStreamText('abc', -1).tail.map((item) => item.char)).toEqual(['a', 'b', 'c']);
	});

	it('does not split an emoji across the head and the tail', () => {
		const { settledText, tail } = splitStreamText('a😀b', 2);
		expect(settledText).toBe('a');
		expect(tail).toEqual([
			{ index: 1, char: '😀' },
			{ index: 3, char: 'b' }
		]);
	});
});

describe('commonPrefixLength', () => {
	it('is the whole previous text when the new text only appends', () => {
		expect(commonPrefixLength('docker compose', 'docker compose logs')).toBe(14);
	});

	it('stops where the text was rewritten', () => {
		expect(commonPrefixLength('run **a', 'run a')).toBe(4);
		expect(commonPrefixLength('', 'abc')).toBe(0);
	});

	it('stops before a surrogate pair whose second half changed', () => {
		expect(commonPrefixLength('x😀', 'x😁')).toBe(1);
	});
});
