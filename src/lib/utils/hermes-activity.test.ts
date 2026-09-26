import { get } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$lib/apis/hermes', () => ({
	getHermesActivity: vi.fn(async () => ({ runs: [], background: [], unread: [] })),
	markHermesChatRead: vi.fn(async () => ({})),
	HermesSessionExpiredError: class extends Error {}
}));

import { chatId, hermesActiveRuns, hermesUnreadChatIds } from '$lib/stores';
import { __resetHermesActivityForTests, applyHermesChatEvent } from './hermes-activity';

const run = (chat: string, extra: Record<string, unknown> = {}) => ({
	chat_id: chat,
	message_id: `m-${chat}`,
	run_id: `run-${chat}`,
	started_at: 1,
	steers: 0,
	title: null,
	...extra
});

beforeEach(() => {
	__resetHermesActivityForTests();
	hermesActiveRuns.set([]);
	hermesUnreadChatIds.set(new Set());
	chatId.set('');
});

afterEach(() => {
	__resetHermesActivityForTests();
});

describe('applyHermesChatEvent', () => {
	it('drops a run the moment its reply ends and marks the chat unread when not on screen', () => {
		hermesActiveRuns.set([run('a'), run('b')]);
		chatId.set('b');
		applyHermesChatEvent({
			chat_id: 'a',
			data: { type: 'chat:completion', data: { hermes_run: { active: false, run_id: 'run-a' } } }
		});
		expect(get(hermesActiveRuns).map((item) => item.chat_id)).toEqual(['b']);
		expect(get(hermesUnreadChatIds).has('a')).toBe(true);
		// The chat on screen is not marked unread.
		applyHermesChatEvent({
			chat_id: 'b',
			data: { type: 'chat:completion', data: { hermes_run: { active: false } } }
		});
		expect(get(hermesActiveRuns)).toEqual([]);
		expect(get(hermesUnreadChatIds).has('b')).toBe(false);
	});

	it('ignores streaming updates that do not end a run', () => {
		hermesActiveRuns.set([run('a')]);
		applyHermesChatEvent({ chat_id: 'a', data: { type: 'chat:completion', data: { content: 'x' } } });
		expect(get(hermesActiveRuns)).toHaveLength(1);
	});

	it('shows an approval at once and clears it once answered', () => {
		applyHermesChatEvent({
			chat_id: 'a',
			message_id: 'm1',
			data: {
				type: 'hermes:approval',
				data: { request_id: 'q1', run_id: 'run-a', command: 'rm -rf x', requested_at: 5 }
			}
		});
		let runs = get(hermesActiveRuns);
		expect(runs).toHaveLength(1);
		expect(runs[0].awaiting_approval).toBe(true);
		expect(runs[0].approval?.command).toBe('rm -rf x');
		applyHermesChatEvent({
			chat_id: 'a',
			data: { type: 'hermes:approval:resolved', data: { request_id: 'q1', choice: 'once' } }
		});
		runs = get(hermesActiveRuns);
		expect(runs[0].awaiting_approval).toBe(false);
	});
});
