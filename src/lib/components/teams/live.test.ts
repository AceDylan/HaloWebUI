import { describe, expect, it } from 'vitest';

import { chatStatesOf, teamChatState } from './live';

const team = (status: string, phase: string | null = null, chat_id: string | null = 'c1') =>
	({ status, phase, chat_id, updated_at: 0 }) as any;

describe('team chat states', () => {
	it('says what a team is doing for its chat in the history', () => {
		expect(teamChatState(team('planning'))).toBe('running');
		expect(teamChatState(team('plan_ready'))).toBe('review');
		expect(teamChatState(team('running', 'running'))).toBe('running');
		expect(teamChatState(team('running', 'attention'))).toBe('attention');
		expect(teamChatState(team('running', 'paused'))).toBeNull();
		expect(teamChatState(team('running', 'completed'))).toBeNull();
		expect(teamChatState(team('cancelled'))).toBeNull();
		expect(teamChatState(team('plan_failed'))).toBeNull();
	});

	it('keys them by chat; what needs you wins a chat two teams share', () => {
		const states = chatStatesOf([
			team('running', 'running', 'c1'),
			team('running', 'attention', 'c1'),
			team('plan_ready', null, 'c2'),
			team('running', 'completed', 'c3'),
			team('running', 'running', null)
		]);
		expect([...states.entries()]).toEqual([
			['c1', 'attention'],
			['c2', 'review']
		]);
	});
});
