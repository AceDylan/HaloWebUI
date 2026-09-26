import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createComposerStatePersister } from './composer-state-persist';

const state = (webSearchMode: string, source = 'default') => ({
	selected_tool_ids: [] as string[],
	web_search_mode: webSearchMode,
	web_search_mode_source: source,
	image_generation_enabled: false
});

describe('composer state persister', () => {
	beforeEach(() => {
		vi.useFakeTimers();
	});
	afterEach(() => {
		vi.useRealTimers();
	});

	const setup = (result: unknown = { ok: true }) => {
		const save = vi.fn(async (_id: string, _payload: unknown) => result);
		const persister = createComposerStatePersister({ save, onError: () => {} });
		return { save, persister };
	};

	it('saves the state it was given for the chat it was given', async () => {
		const { save, persister } = setup();
		const payload = state('halo', 'user');
		persister.schedule('chat-a', payload);

		// The composer is reset for the next chat before the timer fires.
		payload.web_search_mode = 'off';
		payload.selected_tool_ids.push('late-tool');

		await vi.advanceTimersByTimeAsync(250);
		expect(save).toHaveBeenCalledTimes(1);
		expect(save).toHaveBeenCalledWith('chat-a', state('halo', 'user'));
	});

	it('does not write when a chat is opened or left unchanged', async () => {
		const { save, persister } = setup();
		persister.markPersisted('chat-a', state('auto'));

		persister.schedule('chat-a', state('auto'));
		await vi.advanceTimersByTimeAsync(1000);
		expect(save).not.toHaveBeenCalled();
	});

	it('debounces changes and sends only the last one', async () => {
		const { save, persister } = setup();
		persister.markPersisted('chat-a', state('auto'));

		persister.schedule('chat-a', state('off', 'user'));
		await vi.advanceTimersByTimeAsync(100);
		persister.schedule('chat-a', state('halo', 'user'));
		await vi.advanceTimersByTimeAsync(250);

		expect(save).toHaveBeenCalledTimes(1);
		expect(save).toHaveBeenCalledWith('chat-a', state('halo', 'user'));

		// Same state again: already stored.
		persister.schedule('chat-a', state('halo', 'user'));
		await vi.advanceTimersByTimeAsync(250);
		expect(save).toHaveBeenCalledTimes(1);
	});

	it('keeps a change made just before switching chats with the chat it was made in', async () => {
		const { save, persister } = setup();
		persister.markPersisted('chat-a', state('auto'));
		persister.markPersisted('chat-b', state('off', 'model'));

		persister.schedule('chat-a', state('halo', 'user'));
		// The next chat's first save attempt flushes chat A's pending change.
		persister.schedule('chat-b', state('off', 'model'));
		await vi.advanceTimersByTimeAsync(0);

		expect(save).toHaveBeenCalledTimes(1);
		expect(save).toHaveBeenCalledWith('chat-a', state('halo', 'user'));
		await vi.advanceTimersByTimeAsync(1000);
		expect(save).toHaveBeenCalledTimes(1);
	});

	it('retries a state whose save failed', async () => {
		const { save, persister } = setup(null);
		persister.markPersisted('chat-a', state('auto'));

		persister.schedule('chat-a', state('off', 'user'));
		await vi.advanceTimersByTimeAsync(250);
		expect(save).toHaveBeenCalledTimes(1);

		persister.schedule('chat-a', state('off', 'user'));
		await vi.advanceTimersByTimeAsync(250);
		expect(save).toHaveBeenCalledTimes(2);
	});

	it('flush sends a pending change immediately and cancel drops it', async () => {
		const { save, persister } = setup();
		persister.schedule('chat-a', state('off', 'user'));
		await persister.flush();
		expect(save).toHaveBeenCalledTimes(1);

		persister.schedule('chat-a', state('halo', 'user'));
		persister.cancel();
		await vi.advanceTimersByTimeAsync(1000);
		expect(save).toHaveBeenCalledTimes(1);
	});

	it('ignores chats without an id', async () => {
		const { save, persister } = setup();
		persister.schedule('', state('off'));
		persister.schedule(null, state('off'));
		await vi.advanceTimersByTimeAsync(1000);
		expect(save).not.toHaveBeenCalled();
	});
});
