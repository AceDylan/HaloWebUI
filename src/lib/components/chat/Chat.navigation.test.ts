import { readFileSync } from 'node:fs';
import { parse, preprocess } from 'svelte/compiler';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import { beforeAll, describe, expect, it, vi } from 'vitest';

// Exercise Chat's navigation with the API, stores and browser replaced. The
// observable boundary is the displayed history / route and the IDs sent to APIs.
let sourceOf: (name: string) => string;
beforeAll(async () => {
	const filename = process.env.HALO_CHAT_COMPONENT_SOURCE ?? 'src/lib/components/chat/Chat.svelte';
	const { code } = await preprocess(readFileSync(filename, 'utf8'), vitePreprocess(), { filename });
	const declarations = parse(code).instance!.content.body.flatMap(
		(node: any) => node.declarations ?? []
	);
	sourceOf = (name) => {
		const node = declarations.find((node: any) => node.id.name === name);
		if (!node) throw new Error(`Missing Chat declaration: ${name}`);
		return code.slice(node.init.start, node.init.end);
	};
});

const fixture = (overrides: Record<string, any> = {}) => {
	const state: Record<string, any> = {
		chatIdProp: 'target',
		$chatId: 'target',
		activeChatLoadToken: 0,
		composerStateSyncReady: false,
		webSearchSelectionSyncReady: false,
		localStorage: { token: 'test-only' },
		document: { getElementById: () => null },
		console: { error: vi.fn() },
		$temporaryChatEnabled: false,
		$models: [{ id: 'model' }],
		modelsMap: new Map(),
		history: { messages: {}, currentId: null },
		chat: null,
		persistedChatSnapshot: null,
		$i18n: { t: (text: string) => text },
		toast: { error: vi.fn() },
		goto: vi.fn(async () => undefined),
		tick: vi.fn(async () => undefined),
		getChatById: vi.fn(),
		getChatContextById: vi.fn(async () => ({ tags: [], task_ids: [] })),
		loadChat: vi.fn(async () => null),
		initNewChat: vi.fn(async () => undefined),
		getPreferredDefaultWebSearchMode: () => 'off',
		composerStatePersister: { cancel: vi.fn(), schedule: vi.fn(), markPersisted: vi.fn() },
		buildComposerStatePayload: () => ({ web_search_mode: 'off' }),
		persistChatSessionState: vi.fn(),
		liveChatSync: { requestMissed: vi.fn() },
		clearingChatIdForNewChat: false,
		...overrides
	};
	state.chatId = {
		set: vi.fn((id: string) => {
			state.$chatId = id;
		})
	};
	state.chatTitle = { set: vi.fn() };
	state.selectedAssistantScene = { set: vi.fn() };
	state.expandedSelectionThreadId = { set: vi.fn() };
	const noops: Record<string, any> = {};
	const context = new Proxy(state, {
		has: (target, key) => typeof key === 'string' && (key in target || !(key in globalThis)),
		get: (target, key) =>
			typeof key === 'string'
				? key in target
					? target[key]
					: (noops[key] ??= vi.fn())
				: undefined,
		set: (target, key, value) => {
			target[key as string] = value;
			return true;
		}
	});
	const build = (name: string) =>
		new Function('context', `with (context) { return ${sourceOf(name)}; }`)(context);
	return { state, build };
};

const history = {
	currentId: 'answer',
	messages: {
		question: {
			id: 'question',
			role: 'user',
			content: 'Question',
			parentId: null,
			childrenIds: ['answer']
		},
		answer: {
			id: 'answer',
			role: 'assistant',
			content: 'Existing answer / team conclusion',
			parentId: 'question',
			childrenIds: [],
			done: true
		}
	}
};

describe('opening a chat from another mode', () => {
	it.each(['answerDesk', 'team'])(
		'loads the existing %s history before allowing composer saves',
		async (kind) => {
			const { state, build } = fixture();
			state.getChatById.mockResolvedValue({
				id: 'target',
				chat: {
					title: 'Existing',
					models: ['model'],
					history,
					...(kind === 'answerDesk' ? { answerDesk: { messageId: 'answer' } } : {})
				}
			});
			state.loadChat = build('loadChat');
			build('requestChatLoad')('target');
			await vi.waitFor(() => expect(state.composerStateSyncReady).toBe(true));
			expect(state.history).toEqual(history);
			expect(state.$chatId).toBe('target');
			expect(state.goto).not.toHaveBeenCalled();
			expect(state.console.error).not.toHaveBeenCalled();
		}
	);

	it.each(['missing', 'exception'])(
		'clears the failed chat on %s and returns to an initialized home',
		async (failure) => {
			const { state, build } = fixture({ composerStateSyncReady: true });
			if (failure === 'exception')
				state.loadChat.mockRejectedValue(new Error('invalid saved history'));
			build('requestChatLoad')('target');
			await vi.waitFor(() => expect(state.goto).toHaveBeenCalledWith('/'));
			expect(state.$chatId).toBe('');
			expect(state.composerStateSyncReady).toBe(false);
			expect(state.composerStatePersister.schedule).not.toHaveBeenCalled();
			expect(state.composerStatePersister.cancel).toHaveBeenCalledWith('target');
			expect(state.toast.error).toHaveBeenCalledTimes(1);
		}
	);

	it('does not clear a newer chat when an old request fails', async () => {
		let finish!: (value: null) => void;
		const { state, build } = fixture({
			loadChat: vi.fn(
				() =>
					new Promise((resolve) => {
						finish = resolve;
					})
			)
		});
		build('requestChatLoad')('target');
		state.activeChatLoadToken++;
		state.chatIdProp = state.$chatId = 'newer';
		finish(null);
		await new Promise((resolve) => setTimeout(resolve, 0));
		expect(state.$chatId).toBe('newer');
		expect(state.goto).not.toHaveBeenCalled();
	});

	it('does not save a composer for a chat that was never loaded', () => {
		const { state, build } = fixture({ composerStateSyncReady: true });
		build('persistChatComposerState')();
		expect(state.composerStatePersister.schedule).not.toHaveBeenCalled();
		state.chat = { id: 'target' };
		build('persistChatComposerState')();
		expect(state.composerStatePersister.schedule).toHaveBeenCalledWith('target', {
			web_search_mode: 'off'
		});
	});

	it.each(['route', 'store', 'unmount'])(
		'ignores a queued new-chat reset after %s changes',
		async (change) => {
			let finish!: () => void;
			const { state, build } = fixture({
				chatIdProp: '',
				$chatId: '',
				tick: () =>
					new Promise<void>((resolve) => {
						finish = resolve;
					})
			});
			const reset = build('onChatIdCleared')('');
			if (change === 'route') state.chatIdProp = 'target';
			if (change === 'store') state.$chatId = 'target';
			if (change === 'unmount') state.activeChatLoadToken++;
			finish();
			await reset;
			expect(state.initNewChat).not.toHaveBeenCalled();
		}
	);
});
