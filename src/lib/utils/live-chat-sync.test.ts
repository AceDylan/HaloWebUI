import { afterEach, describe, expect, it, vi } from 'vitest';
import { EventEmitter } from 'node:events';
import { writable } from 'svelte/store';
import {
	createChatSync,
	createEventDeduplicator,
	reconcileChatHistory,
	subscribeChatSync
} from './live-chat-sync';

const history = (content = '', done = false) => ({
	currentId: 'answer',
	messages: {
		question: { id: 'question', role: 'user', childrenIds: ['answer'], content: 'hello' },
		answer: {
			id: 'answer',
			parentId: 'question',
			childrenIds: [],
			role: 'assistant',
			content,
			done
		}
	} as Record<string, any>
});

describe('live history reconciliation', () => {
	it('adds a remote turn once and follows the appended branch', () => {
		const local = history('first answer', true);
		const remote = structuredClone(local);
		remote.messages.answer.childrenIds = ['follow-up'];
		remote.messages['follow-up'] = {
			id: 'follow-up',
			parentId: 'answer',
			content: '[后台任务完成通知]'
		};
		remote.currentId = 'follow-up';
		const result = reconcileChatHistory(local, remote, local);
		expect(result.currentId).toBe('follow-up');
		expect(Object.keys(result.messages)).toHaveLength(3);
		expect(reconcileChatHistory(result, remote, result)).toEqual(result);
	});

	it('does not switch away from a branch selected on this device', () => {
		const local = history('branch A');
		const remote = history('branch A');
		remote.messages.b = { id: 'b', parentId: 'question', content: 'branch B' };
		remote.currentId = 'b';
		expect(reconcileChatHistory(local, remote, local).currentId).toBe('answer');
	});

	it('renders persisted image files and final content without a page reload', () => {
		const before = history();
		const remote = history('![image](/image.png)', true);
		remote.messages.answer.files = [{ type: 'image', url: '/image.png' }];
		const result = reconcileChatHistory(before, remote, before);
		expect(result.messages.answer.content).toBe('![image](/image.png)');
		expect(result.messages.answer.files).toEqual(remote.messages.answer.files);
		expect(result.messages.answer.done).toBe(true);
	});

	it('keeps a live update and image that arrived while the GET was pending', () => {
		const before = history('start');
		const live = history('start and new tokens');
		live.messages.answer.files = [{ id: 'file-1', url: '/one.png' }];
		const remote = history('start');
		remote.messages.answer.files = [{ id: 'file-1', url: '/one.png' }, { url: '/two.png' }];
		const result = reconcileChatHistory(live, remote, before);
		expect(result.messages.answer.content).toBe('start and new tokens');
		expect(result.messages.answer.files).toHaveLength(2);
	});

	it('does not rewind a stream when persistence trails the socket', () => {
		const live = history('several tokens');
		const result = reconcileChatHistory(live, history(''), live);
		expect(result.messages.answer.content).toBe('several tokens');
		expect(result.messages.answer.done).toBe(false);
	});

	it('repairs a placeholder classified as done before its task was registered', () => {
		const local = history('', true);
		expect(reconcileChatHistory(local, history('', false), local).messages.answer.done).toBe(false);
	});

	it('accepts an authoritative shorter final response and empty replacement', () => {
		const live = history('MEDIA:/temporary/image');
		expect(reconcileChatHistory(live, history('final', true), live).messages.answer.content).toBe(
			'final'
		);
		expect(reconcileChatHistory(live, history('', true), live).messages.answer.content).toBe('');
	});

	it('preserves unsaved new messages and removes remotely deleted messages', () => {
		const previous = history('old', true);
		const local = structuredClone(previous);
		local.messages.draft = { id: 'draft', content: 'local new turn' };
		const remote = structuredClone(previous);
		delete remote.messages.answer;
		remote.currentId = 'question';
		const result = reconcileChatHistory(local, remote, local, previous);
		expect(result.messages.answer).toBeUndefined();
		expect(result.messages.draft.content).toBe('local new turn');
		expect(result.currentId).toBe('question');
	});

	it('uses fresh message objects so streaming callbacks cannot keep detached snapshots', () => {
		const local = history('old');
		const result = reconcileChatHistory(local, history('new', true), local);
		expect(result.messages.answer).not.toBe(local.messages.answer);
		expect(local.messages.answer.content).toBe('old');
	});
});

describe('background sync lifecycle', () => {
	afterEach(() => vi.useRealTimers());

	it('subscribes after socket creation, rebinds replacements, and recovers on browser lifecycle events', async () => {
		vi.useFakeTimers();
		const socketStore = writable<EventEmitter | null>(null);
		const window = new EventTarget();
		const document = Object.assign(new EventTarget(), { visibilityState: 'visible' });
		const refresh = vi.fn();
		const onEvent = vi.fn();
		const cleanup = subscribeChatSync({ socketStore, window, document, refresh, onEvent });
		const first = new EventEmitter();
		socketStore.set(first);
		first.emit('chat-events', { chat_id: 'same-account-chat' });
		expect(onEvent).toHaveBeenCalledTimes(1);
		refresh.mockClear();
		first.emit('connect');
		for (const type of ['focus', 'online', 'pageshow']) window.dispatchEvent(new Event(type));
		document.dispatchEvent(new Event('visibilitychange'));
		expect(refresh).toHaveBeenCalledTimes(5);
		document.visibilityState = 'hidden';
		await vi.advanceTimersByTimeAsync(15000);
		expect(refresh).toHaveBeenCalledTimes(5);
		document.visibilityState = 'visible';
		await vi.advanceTimersByTimeAsync(15000);
		expect(refresh).toHaveBeenCalledTimes(6);
		const second = new EventEmitter();
		socketStore.set(second);
		expect(first.listenerCount('chat-events')).toBe(0);
		expect(first.listenerCount('connect')).toBe(0);
		second.emit('chat-events', { chat_id: 'same-account-chat' });
		expect(onEvent).toHaveBeenCalledTimes(2);
		cleanup();
		expect(second.listenerCount('chat-events')).toBe(0);
		refresh.mockClear();
		window.dispatchEvent(new Event('focus'));
		document.dispatchEvent(new Event('visibilitychange'));
		await vi.advanceTimersByTimeAsync(15000);
		expect(refresh).not.toHaveBeenCalled();
	});

	it('aborts a hung network request so a later reconnect can retry', async () => {
		vi.useFakeTimers();
		const read = vi
			.fn()
			.mockImplementationOnce(
				(signal: AbortSignal) =>
					new Promise((_, reject) => {
						signal.addEventListener('abort', () => reject(new Error('aborted')));
					})
			)
			.mockResolvedValue('recovered');
		const apply = vi.fn();
		const sync = createChatSync({ getKey: () => 'chat-A', read, apply });
		sync.request();
		await vi.advanceTimersByTimeAsync(10100);
		expect(apply).not.toHaveBeenCalled();
		sync.request();
		await vi.advanceTimersByTimeAsync(100);
		expect(apply).toHaveBeenCalledWith('recovered');
		sync.dispose();
	});

	it('coalesces reloads and performs one follow-up if another event arrives during a read', async () => {
		vi.useFakeTimers();
		let resolve: (value: string) => void = () => {};
		const read = vi
			.fn()
			.mockImplementationOnce(
				() =>
					new Promise<string>((r) => {
						resolve = r;
					})
			)
			.mockResolvedValue('latest');
		const apply = vi.fn();
		const sync = createChatSync({ getKey: () => 'chat-A', read, apply });
		sync.request();
		sync.request();
		sync.request();
		await vi.advanceTimersByTimeAsync(100);
		expect(read).toHaveBeenCalledTimes(1);
		sync.request();
		sync.request();
		resolve('first');
		await vi.advanceTimersByTimeAsync(100);
		expect(read).toHaveBeenCalledTimes(2);
		expect(apply.mock.calls).toEqual([['first'], ['latest']]);
		sync.dispose();
	});

	it.each(['chat-B:2', 'chat-A:2', null])(
		'discards an old GET after navigation to %s',
		async (nextKey) => {
			vi.useFakeTimers();
			let key: string | null = 'chat-A:1';
			let resolve: (value: string) => void = () => {};
			const apply = vi.fn();
			const sync = createChatSync({
				getKey: () => key,
				read: () =>
					new Promise<string>((r) => {
						resolve = r;
					}),
				apply
			});
			sync.request();
			await vi.advanceTimersByTimeAsync(100);
			key = nextKey;
			resolve('old chat');
			await vi.advanceTimersByTimeAsync(100);
			expect(apply).not.toHaveBeenCalled();
			expect(key).toBe(nextKey);
			sync.dispose();
		}
	);

	it('recovers from a failed fetch on the next reconnect or foreground trigger', async () => {
		vi.useFakeTimers();
		const read = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValue('caught up');
		const apply = vi.fn();
		const sync = createChatSync({ getKey: () => 'chat-A', read, apply });
		sync.request();
		await vi.advanceTimersByTimeAsync(100);
		expect(apply).not.toHaveBeenCalled();
		sync.request();
		await vi.advanceTimersByTimeAsync(100);
		expect(apply).toHaveBeenCalledWith('caught up');
		sync.dispose();
	});

	it('does not apply an in-flight response after unmount', async () => {
		vi.useFakeTimers();
		let resolve: (value: string) => void = () => {};
		const apply = vi.fn();
		const sync = createChatSync({
			getKey: () => 'chat-A',
			read: () =>
				new Promise<string>((r) => {
					resolve = r;
				}),
			apply
		});
		sync.request();
		await vi.advanceTimersByTimeAsync(100);
		sync.dispose();
		resolve('late');
		await vi.advanceTimersByTimeAsync(100);
		expect(apply).not.toHaveBeenCalled();
	});
});

it('deduplicates fan-out events without sharing state between devices', () => {
	const deviceA = createEventDeduplicator();
	const deviceB = createEventDeduplicator();
	for (const device of [deviceA, deviceB]) {
		expect(device('same-event')).toBe(true);
		expect(device('same-event')).toBe(false);
		expect(device('another-event')).toBe(true);
	}
});
