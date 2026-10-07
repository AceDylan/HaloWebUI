import { describe, expect, it } from 'vitest';
import { hasRenderableChatHistory } from './chat-history-state';

describe('hasRenderableChatHistory', () => {
	it('requires the current message to still exist', () => {
		expect(hasRenderableChatHistory({ currentId: 'answer', messages: { answer: {} } })).toBe(true);
		expect(hasRenderableChatHistory({ currentId: 'answer', messages: {} })).toBe(false);
		expect(hasRenderableChatHistory({ currentId: null, messages: { answer: {} } })).toBe(false);
		expect(hasRenderableChatHistory(null)).toBe(false);
	});
});
