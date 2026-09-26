import { get } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$lib/apis/hermes', () => ({
	getHermesActivity: vi.fn(async () => ({ runs: [], background: [], unread: [] })),
	markHermesChatRead: vi.fn(async () => ({})),
	HermesSessionExpiredError: class extends Error {}
}));

import { getHermesActivity, markHermesChatRead } from '$lib/apis/hermes';
import { chatId, hermesActiveRuns, hermesUnreadChatIds } from '$lib/stores';
import {
	__resetHermesActivityForTests,
	applyHermesChatEvent,
	refreshHermesActivity,
	startHermesActivityPolling
} from './hermes-activity';

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
	vi.unstubAllGlobals();
	vi.mocked(markHermesChatRead).mockClear();
});

const stubPage = (visibilityState: 'visible' | 'hidden') => {
	const listeners: Record<string, () => void> = {};
	const page = {
		visibilityState,
		addEventListener: (name: string, listener: () => void) => (listeners[name] = listener),
		removeEventListener: (name: string) => delete listeners[name]
	};
	vi.stubGlobal('document', page);
	vi.stubGlobal('localStorage', { token: 't' });
	return {
		show: async () => {
			page.visibilityState = 'visible';
			listeners.visibilitychange?.();
			await refreshHermesActivity();
		}
	};
};

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

describe('the chat on screen', () => {
	it('is marked read by a visible tab', async () => {
		stubPage('visible');
		chatId.set('a');
		vi.mocked(getHermesActivity).mockResolvedValue({ runs: [], background: [], unread: ['a', 'b'] });
		startHermesActivityPolling();
		await refreshHermesActivity();
		expect(markHermesChatRead).toHaveBeenCalledWith('t', 'a');
		expect([...get(hermesUnreadChatIds)]).toEqual(['b']);
	});

	it('stays unread while the tab is hidden, and is read once the tab is shown', async () => {
		const page = stubPage('hidden');
		chatId.set('a');
		vi.mocked(getHermesActivity).mockResolvedValue({ runs: [], background: [], unread: ['a'] });
		startHermesActivityPolling();
		await refreshHermesActivity();
		expect(markHermesChatRead).not.toHaveBeenCalled();
		expect(get(hermesUnreadChatIds).has('a')).toBe(true);

		await page.show();
		expect(markHermesChatRead).toHaveBeenCalledWith('t', 'a');
		expect(get(hermesUnreadChatIds).has('a')).toBe(false);
	});

	it('is marked unread when its run ends in a hidden tab', () => {
		stubPage('hidden');
		hermesActiveRuns.set([run('a')]);
		chatId.set('a');
		applyHermesChatEvent({
			chat_id: 'a',
			data: { type: 'chat:completion', data: { hermes_run: { active: false, run_id: 'run-a' } } }
		});
		expect(get(hermesUnreadChatIds).has('a')).toBe(true);
	});
});
