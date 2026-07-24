import { describe, expect, it } from 'vitest';

import {
	countUserTurns,
	isTitleGenerationMilestone,
	shouldRequestTitleGeneration
} from './chat-title-generation';

const conversationAtTurn = (turn: number) =>
	Array.from({ length: turn }, (_, index) => [
		{ role: 'user', content: `question ${index + 1}` },
		{ role: 'assistant', content: `answer ${index + 1}` }
	]).flat();

describe('chat title generation schedule', () => {
	it('requests turns 1, 3, 6, 9 and every third turn thereafter', () => {
		expect(Array.from({ length: 13 }, (_, index) => isTitleGenerationMilestone(index))).toEqual([
			false,
			true,
			false,
			true,
			false,
			false,
			true,
			false,
			false,
			true,
			false,
			false,
			true
		]);
	});

	it('counts only user messages', () => {
		expect(
			countUserTurns([
				{ role: 'system' },
				{ role: 'user' },
				{ role: 'assistant' },
				null,
				{ role: 'user' }
			])
		).toBe(2);
	});

	it('requires a persisted chat and the primary model', () => {
		const messages = conversationAtTurn(3);

		expect(
			shouldRequestTitleGeneration({ messages, isPrimaryModel: true, isTemporaryChat: false })
		).toBe(true);
		expect(
			shouldRequestTitleGeneration({ messages, isPrimaryModel: false, isTemporaryChat: false })
		).toBe(false);
		expect(
			shouldRequestTitleGeneration({ messages, isPrimaryModel: true, isTemporaryChat: true })
		).toBe(false);
	});
});
