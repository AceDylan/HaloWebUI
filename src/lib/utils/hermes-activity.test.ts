import { get } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$lib/apis/hermes', () => ({
	getHermesActivity: vi.fn(async () => ({ runs: [], background: [], unread: [] })),
	markHermesChatRead: vi.fn(async () => ({})),
	HermesSessionExpiredError: class extends Error {}
}));

import { getHermesActivity, markHermesChatRead } from '$lib/apis/hermes';
import { chatId, hermesActiveRuns, hermesBackgroundRuns, hermesUnreadChatIds, workActivity } from '$lib/stores';
import {
	__resetHermesActivityForTests,
	applyHermesChatEvent,
	hermesActivityRows,
	refreshHermesActivity,
	selectHermesActivityRows,
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
	hermesBackgroundRuns.set([]);
	workActivity.set([]);
	hermesUnreadChatIds.set(new Set());
	chatId.set('');
});

describe('one running row per chat', () => {
	const background = (chat: string, updated = 10) => ({
		chat_id: chat,
		run_id: `runner-${chat}-${updated}`,
		agent: 'codex',
		status: 'running',
		started_at: 2,
		updated_at: updated,
		step: 3,
		last_activity: '渲染中',
		title: '视频任务'
	});
	const work = (chat: string | null, kind: 'video' | 'chat' | 'team' = 'video', id = chat ?? kind) => ({
		kind, id, chat_id: chat, title: '视频任务', href: `/c/${chat}`, started_at: 1,
		state: 'running' as const
	});

	it('selects the latest runner over Hermes, work and unread without changing the sources', () => {
		const activity = {
			runs: [run('a'), run('b')],
			background: [background('a'), background('a', 20)],
			work: [work('a'), work('b'), work('c')],
			unread: ['a', 'b', 'c', 'd', 'd']
		};
		const before = structuredClone(activity);
		const selected = selectHermesActivityRows(activity);
		expect(selected.runs).toEqual([activity.runs[1]]);
		expect(selected.background).toEqual([activity.background[1]]);
		expect(selected.work).toEqual([activity.work[2]]);
		expect(selected.unread).toEqual(['d']);
		expect(activity).toEqual(before);
	});

	it('keeps approvals ahead of newer runs and runners, and unrelated work without a chat', () => {
		const approval = run('a', { awaiting_approval: true, approval: { request_id: 'q1' } });
		const waiting = { ...work('b', 'team'), state: 'waiting' as const };
		const selected = selectHermesActivityRows({
			runs: [run('a', { started_at: 30 }), approval, run('c'), run('c', { started_at: 20 })],
			background: [background('a'), background('b')],
			work: [work('a'), work('b'), waiting, work(null, 'team'), work(null, 'video'), work(null, 'video')],
			unread: ['a', 'b']
		});
		expect(selected.runs).toEqual([approval, run('c', { started_at: 20 })]);
		expect(selected.background).toEqual([]);
		expect(selected.work).toEqual([waiting, work(null, 'team'), work(null, 'video')]);
		expect(selected.unread).toEqual([]);
	});

	it('handles local approval insertion and resolution while keeping runner stop data', () => {
		const runner = background('a');
		hermesBackgroundRuns.set([runner]);
		workActivity.set([work('a')]);
		hermesUnreadChatIds.set(new Set(['a']));
		expect(get(hermesActivityRows).background).toEqual([runner]);
		const event = {
			chat_id: 'a', message_id: 'm-a',
			data: { type: 'hermes:approval', data: { request_id: 'q1', run_id: 'run-a', command: 'render' } }
		};
		applyHermesChatEvent(event);
		applyHermesChatEvent(event);
		expect(get(hermesActiveRuns)).toHaveLength(1);
		expect(get(hermesActivityRows).runs[0].approval?.request_id).toBe('q1');
		expect(get(hermesActivityRows).background).toEqual([]);
		expect(get(hermesActivityRows).work).toEqual([]);
		expect(get(hermesActivityRows).unread).toEqual([]);
		expect(get(hermesBackgroundRuns)).toEqual([runner]);
		applyHermesChatEvent({
			chat_id: 'a', data: { type: 'hermes:approval:resolved', data: { request_id: 'q1' } }
		});
		expect(get(hermesActivityRows).runs).toEqual([]);
		expect(get(hermesActivityRows).background[0].run_id).toBe(runner.run_id);
		expect(get(hermesActiveRuns)).toHaveLength(1);
		// Progress expiry reveals the pending video task after the Hermes turn ends.
		applyHermesChatEvent({
			chat_id: 'a', data: { type: 'chat:completion', data: { hermes_run: { active: false } } }
		});
		hermesBackgroundRuns.set([]);
		expect(get(hermesActivityRows).work).toEqual([work('a')]);
	});
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

describe('other modes at work', () => {
	const work = (over: Record<string, unknown> = {}) => ({
		kind: 'chat' as const,
		id: 'c1',
		chat_id: 'c1',
		title: '周报',
		href: '/c/c1',
		started_at: 1,
		state: 'running' as const,
		...over
	});

	it('come with the poll', async () => {
		stubPage('visible');
		vi.mocked(getHermesActivity).mockResolvedValue({
			runs: [],
			background: [],
			unread: [],
			work: [work(), work({ kind: 'team', id: 't1', chat_id: null, state: 'waiting', note: '等你批准' })]
		});
		startHermesActivityPolling();
		await refreshHermesActivity();
		expect(get(workActivity).map((row) => `${row.kind}:${row.id}`)).toEqual(['chat:c1', 'team:t1']);
	});

	it('a chat reply leaves the list the moment it is done; other modes wait for the poll', () => {
		workActivity.set([work(), work({ kind: 'answer', id: 'a1', chat_id: 'c1', href: '/answer/a1' })]);
		applyHermesChatEvent({ chat_id: 'c1', data: { type: 'chat:completion', data: { content: 'x' } } });
		expect(get(workActivity)).toHaveLength(2);
		applyHermesChatEvent({ chat_id: 'c1', data: { type: 'chat:completion', data: { done: true } } });
		expect(get(workActivity).map((row) => row.kind)).toEqual(['answer']);
		// a 精答 is done (its picture drawn) when its own "reply ready" comes
		applyHermesChatEvent({ chat_id: 'c1', data: { type: 'chat:completion', data: { done: true, answer_desk: true } } });
		expect(get(workActivity)).toEqual([]);
	});
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
