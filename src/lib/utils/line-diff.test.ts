import { describe, expect, it } from 'vitest';

import { diffStats, lineDiff } from './line-diff';

const render = (before: string, after: string) =>
	lineDiff(before, after).map((line) => `${{ same: ' ', del: '-', add: '+' }[line.type]}${line.text}`);

describe('lineDiff', () => {
	it('keeps identical texts as they are', () => {
		expect(render('a\nb', 'a\nb')).toEqual([' a', ' b']);
	});

	it('handles empty sides', () => {
		expect(lineDiff('', '')).toEqual([]);
		expect(render('', 'a\nb')).toEqual(['+a', '+b']);
		expect(render('a', '')).toEqual(['-a']);
	});

	it('marks a changed line as removed then added, keeping the lines around it', () => {
		expect(render('role\nold rule\nformat', 'role\nnew rule\nformat')).toEqual([
			' role',
			'-old rule',
			'+new rule',
			' format'
		]);
	});

	it('finds the longest common subsequence in the middle', () => {
		expect(render('a\nb\nc\nd', 'a\nc\nx\nd')).toEqual([' a', '-b', ' c', '+x', ' d']);
		expect(render('x\na\ny', 'a\nz\na')).toEqual(['-x', ' a', '-y', '+z', '+a']);
	});

	it('treats CRLF like LF', () => {
		expect(render('a\r\nb', 'a\nb')).toEqual([' a', ' b']);
	});

	it('counts the changes', () => {
		expect(diffStats(lineDiff('a\nb\nc', 'a\nc\nd\ne'))).toEqual({ added: 2, removed: 1 });
	});
});
