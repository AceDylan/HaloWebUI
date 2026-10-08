import { describe, expect, it } from 'vitest';

import {
	computeContextUsage,
	estimateTokens,
	formatTokenCount,
	resolveContextWindow
} from './context-usage';

const msg = (id: string, parentId: string | null, role: string, content: string, extra = {}) => ({
	id,
	parentId,
	childrenIds: [],
	role,
	content,
	...extra
});

describe('resolveContextWindow', () => {
	it('prefers a size the model declares', () => {
		expect(resolveContextWindow({ id: 'claude-x', info: { params: { num_ctx: 32768 } } })).toEqual({
			tokens: 32768,
			source: 'model'
		});
	});

	it('falls back to the family, a workspace assistant by its base model', () => {
		expect(resolveContextWindow({ id: 'claude-sonnet-4-5' })).toEqual({ tokens: 200_000, source: 'family' });
		expect(resolveContextWindow({ id: 'claude-chat' }).tokens).toBe(1_000_000);
		expect(resolveContextWindow({ id: 'my-helper', info: { base_model_id: 'gemini-2.5-pro' } }).tokens).toBe(
			1_000_000
		);
		expect(resolveContextWindow({ id: 'o3-mini' }).tokens).toBe(200_000);
		expect(resolveContextWindow({ id: 'gpt-4o-mini' }).tokens).toBe(128_000);
	});

	it('uses a default for an unknown model', () => {
		expect(resolveContextWindow({ id: 'gpt-chat' })).toEqual({ tokens: 128_000, source: 'default' });
		expect(resolveContextWindow(null).source).toBe('default');
	});
});

describe('computeContextUsage', () => {
	it('counts the newest reply usage plus what was sent after it, without its reasoning', () => {
		const history = {
			currentId: 'u2',
			messages: {
				u1: msg('u1', null, 'user', 'hi'),
				a1: msg('a1', 'u1', 'assistant', 'old', {
					usage: { prompt_tokens: 999, completion_tokens: 1 }
				}),
				a2: msg('a2', 'u1', 'assistant', 'answer', {
					usage: {
						prompt_tokens: 1000,
						cache_read_input_tokens: 4000,
						completion_tokens: 600,
						completion_tokens_details: { reasoning_tokens: 500 }
					}
				}),
				u2: msg('u2', 'a2', 'user', 'abcdefgh')
			}
		};

		const usage = computeContextUsage(history, 10_000, 'family');

		expect(usage).toEqual({
			tokens: 1000 + 4000 + 100 + 2,
			window: 10_000,
			ratio: 5102 / 10_000,
			estimated: false,
			windowSource: 'family'
		});
	});

	it('estimates from characters when no reply has usage', () => {
		const history = {
			currentId: 'a1',
			messages: {
				u1: msg('u1', null, 'user', '你好'),
				a1: msg('a1', 'u1', 'assistant', '<details type="reasoning">long thoughts</details>abcd')
			}
		};
		const usage = computeContextUsage(history, 100);
		expect(usage?.tokens).toBe(3);
		expect(usage?.estimated).toBe(true);
	});

	it('has nothing to say about an empty chat', () => {
		expect(computeContextUsage({ currentId: null, messages: {} }, 1000)).toBeNull();
	});
});

describe('formatting', () => {
	it('keeps counts short', () => {
		expect(formatTokenCount(950)).toBe('950');
		expect(formatTokenCount(45_300)).toBe('45.3k');
		expect(formatTokenCount(200_000)).toBe('200k');
		expect(formatTokenCount(1_000_000)).toBe('1M');
		expect(estimateTokens('你好abcd')).toBe(3);
	});
});
