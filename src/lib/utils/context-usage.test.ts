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
		expect(resolveContextWindow({ id: 'gpt-chat', info: { meta: { context_window: 500_000 } } })).toEqual({
			tokens: 500_000,
			source: 'model'
		});
	});

	it('uses the unified 300k default whenever no size is declared', () => {
		for (const model of [
			{ id: 'gpt-chat' },
			{ id: 'claude-chat' },
			{ id: 'claude-sonnet-4-5' },
			{ id: 'gemini-chat' },
			{ id: 'my-helper', info: { base_model_id: 'gemini-2.5-pro' } },
			{ id: 'deepseek-chat' },
			{ id: 'glm-chat' },
			{ id: 'grok-chat' },
			{ id: 'kimi-chat' },
			{ id: 'o3-mini' },
			{ id: 'gpt-4o-mini' },
			null
		]) {
			expect(resolveContextWindow(model)).toEqual({ tokens: 300_000, source: 'default' });
		}
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

		const usage = computeContextUsage(history, 10_000, 'default');

		expect(usage).toEqual({
			tokens: 1000 + 4000 + 100 + 2,
			window: 10_000,
			ratio: 5102 / 10_000,
			estimated: false,
			windowSource: 'default'
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
		expect(formatTokenCount(300_000)).toBe('300k');
		expect(formatTokenCount(1_000_000)).toBe('1M');
		expect(estimateTokens('你好abcd')).toBe(3);
	});
});
