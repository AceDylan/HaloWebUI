import { describe, expect, it } from 'vitest';

import { mergeAdjacentReasoningDetails } from './reasoning-merge';

const block = (text: string, duration = '0.4') =>
	`<details type="reasoning" done="true" duration="${duration}">\n<summary>Thought for ${duration} seconds</summary>\n> ${text}\n</details>`;

const countReasoning = (content: string) =>
	(content.match(/type="reasoning"/g) ?? []).length;

describe('mergeAdjacentReasoningDetails', () => {
	it('leaves content without reasoning untouched', () => {
		const content = 'Just a plain answer.';
		expect(mergeAdjacentReasoningDetails(content)).toBe(content);
	});

	it('leaves a single reasoning block untouched', () => {
		const content = `${block('only thought')}\nFinal answer.`;
		expect(mergeAdjacentReasoningDetails(content)).toBe(content);
	});

	it('merges reasoning blocks separated only by whitespace', () => {
		const content = `${block('first')}\n\n${block('second')}\nFinal answer.`;
		const result = mergeAdjacentReasoningDetails(content);

		expect(countReasoning(result)).toBe(1);
		expect(result).toContain('first');
		expect(result).toContain('second');
		expect(result).toContain('Final answer.');
	});

	it('merges fragmented blocks whose gaps echo the reasoning text', () => {
		// Provider mirrors each thinking token into the answer stream.
		const content = [block('用户'), '用户', block('问了'), '问了', block('我')].join('\n');
		const result = mergeAdjacentReasoningDetails(content);

		expect(countReasoning(result)).toBe(1);
		expect(result).toContain('用户');
		expect(result).toContain('问了');
		expect(result).toContain('我');
		// The leaked echo text must not remain as visible content outside the block.
		expect(result.replace(/<details[\s\S]*?<\/details>/g, '').trim()).toBe('');
	});

	it('sums durations of merged blocks', () => {
		const content = `${block('a', '0.4')}\n${block('b', '0.3')}`;
		const result = mergeAdjacentReasoningDetails(content);

		expect(countReasoning(result)).toBe(1);
		expect(result).toContain('duration="0.7"');
	});

	it('keeps a real answer between two reasoning blocks (no merge)', () => {
		const content = `${block('think one')}\nHere is the actual answer paragraph.\n${block('think two')}`;
		const result = mergeAdjacentReasoningDetails(content);

		expect(countReasoning(result)).toBe(2);
		expect(result).toContain('Here is the actual answer paragraph.');
	});

	it('stays open (done="false") when an active block is merged in', () => {
		const active =
			'<details type="reasoning" done="false">\n<summary>Thinking…</summary>\n> tail\n</details>';
		const content = `${block('head')}\n${active}`;
		const result = mergeAdjacentReasoningDetails(content);

		expect(countReasoning(result)).toBe(1);
		expect(result).toContain('done="false"');
		expect(result).toContain('head');
		expect(result).toContain('tail');
	});

	it('never throws on malformed input', () => {
		const content = '<details type="reasoning">unterminated <details type="reasoning"> nested';
		expect(() => mergeAdjacentReasoningDetails(content)).not.toThrow();
	});
});
