import { readFileSync } from 'node:fs';
import { parse, preprocess } from 'svelte/compiler';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import { beforeAll, describe, expect, it, vi } from 'vitest';
import {
	createEventDeduplicator,
	mergeLiveFiles,
	reconcileChatHistory
} from '$lib/utils/live-chat-sync';

// Exercise the actual socket listener with browser/API boundaries replaced.
// This keeps regression checks independent of the app's large DOM/import tree.
let createHandler: (context: Record<string, any>) => (event: any) => Promise<void>;
let createCompletionHandler: (
	context: Record<string, any>
) => (data: any, message: any, chatId: string) => Promise<void>;
let createSaveHandler: (
	context: Record<string, any>
) => (id: string, history: any) => Promise<void>;
beforeAll(async () => {
	const filename = process.env.HALO_CHAT_COMPONENT_SOURCE ?? 'src/lib/components/chat/Chat.svelte';
	const { code } = await preprocess(readFileSync(filename, 'utf8'), vitePreprocess(), { filename });
	const ast = parse(code);
	const declarations = ast.instance!.content.body.flatMap((node: any) => node.declarations ?? []);
	const declaration = declarations.find((node: any) => node.id.name === 'chatEventHandler');
	createHandler = new Function(
		'context',
		`with (context) { return ${code.slice(declaration.init.start, declaration.init.end)}; }`
	) as typeof createHandler;
	const completion = declarations.find(
		(node: any) => node.id.name === 'chatCompletionEventHandler'
	);
	createCompletionHandler = new Function(
		'context',
		`with (context) { return ${code.slice(completion.init.start, completion.init.end)}; }`
	) as typeof createCompletionHandler;
	const save = declarations.find((node: any) => node.id.name === 'saveChatHandler');
	createSaveHandler = new Function(
		'context',
		`with (context) { return ${code.slice(save.init.start, save.init.end)}; }`
	) as typeof createSaveHandler;
});

const fixture = () => {
	const context: Record<string, any> = {
		$chatId: 'current-chat',
		chatIdProp: '', // New chats use shallow routing and retain empty/old params.
		activeChatLoadToken: 1,
		tick: vi.fn().mockResolvedValue(undefined),
		acceptChatEvent: createEventDeduplicator(),
		history: { messages: {} },
		liveChatSync: { request: vi.fn() },
		loadChat: vi.fn(),
		isResponseStopped: () => false,
		stoppedResponseMessageIds: new Set(),
		shouldAutoScrollOnStreaming: () => false,
		mergeMessageFiles: mergeLiveFiles,
		commitHistoryMessage: vi.fn()
	};
	return { context, handler: createHandler(context) };
};

describe('chat socket listener', () => {
	it('absorbs the merged save without treating unchanged local settings as a remote overwrite', async () => {
		const { context } = fixture();
		const local = {
			currentId: 'answer',
			messages: { answer: { id: 'answer', content: 'local edit', done: true } }
		};
		const remote = structuredClone(local);
		remote.messages.answer.content = 'newer server edit';
		const baseline = {
			history: {
				currentId: 'answer',
				messages: { answer: { id: 'answer', content: 'old', done: true } }
			},
			params: { system: 'local preference' }
		};
		Object.assign(context, {
			history: local,
			chat: null,
			$temporaryChatEnabled: false,
			persistedChatSnapshot: baseline,
			pendingHistorySaves: 0,
			chatSyncRevision: 0,
			selectionThreads: {},
			normalizeHistoryForPersistence: async (history) => ({ history, changed: false }),
			createMessagesList: () => [],
			buildPersistedChatData: (history) => ({ history, params: { system: 'local preference' } }),
			pendingChatSave: Promise.resolve(),
			updateChatById: vi
				.fn()
				.mockResolvedValue({
					chat: { history: remote, params: { system: 'other device preference' } }
				}),
			localStorage: { token: 'test-only' },
			currentChatPage: { set: vi.fn() },
			$currentChatPage: 1,
			chats: { set: vi.fn() },
			getChatList: async () => [],
			clearResponseAnimationControllers: vi.fn(),
			reconcileChatHistory
		});
		await createSaveHandler(context)('current-chat', local);
		expect(context.updateChatById.mock.calls[0][3]).toEqual(baseline);
		expect(context.history.messages.answer.content).toBe('newer server edit');
		expect(context.persistedChatSnapshot.history).toEqual(remote);
		expect(context.persistedChatSnapshot.params.system).toBe('local preference');
		expect(context.pendingHistorySaves).toBe(0);
	});
	it.each(['', 'previous-chat'])(
		'refreshes the displayed chat without loading stale route params (%s)',
		async (prop) => {
			const { context, handler } = fixture();
			context.chatIdProp = prop;
			await handler({ chat_id: 'current-chat', data: { type: 'chat:reload' } });
			expect(context.liveChatSync.request).toHaveBeenCalledTimes(1);
			expect(context.loadChat).not.toHaveBeenCalled();
			expect(context.$chatId).toBe('current-chat');
		}
	);

	it('ignores notifications for another chat', async () => {
		const { context, handler } = fixture();
		await handler({ chat_id: 'other-chat', data: { type: 'chat:reload' } });
		expect(context.loadChat).not.toHaveBeenCalled();
		expect(context.liveChatSync.request).not.toHaveBeenCalled();
	});

	it('requests missing messages created by another device', async () => {
		const { context, handler } = fixture();
		await handler({
			chat_id: 'current-chat',
			message_id: 'new-on-phone',
			data: { type: 'chat:completion', data: { content: 'hello' } }
		});
		expect(context.liveChatSync.request).toHaveBeenCalledTimes(1);
	});

	it('discards a notification if the reader navigates while awaiting DOM updates', async () => {
		const { context, handler } = fixture();
		context.tick.mockImplementation(async () => {
			context.$chatId = 'next-chat';
			context.activeChatLoadToken++;
		});
		await handler({ chat_id: 'current-chat', data: { type: 'chat:reload' } });
		expect(context.loadChat).not.toHaveBeenCalled();
		expect(context.liveChatSync.request).not.toHaveBeenCalled();
	});

	it('commits arriving images immediately and ignores duplicate event delivery', async () => {
		const { context, handler } = fixture();
		context.history.messages.answer = { id: 'answer', files: [] };
		const event = {
			event_id: 'image-event',
			chat_id: 'current-chat',
			message_id: 'answer',
			data: { type: 'files', data: { files: [{ url: '/image.png', type: 'image' }] } }
		};
		await handler(event);
		await handler(event);
		expect(context.history.messages.answer.files).toHaveLength(1);
		expect(context.commitHistoryMessage).toHaveBeenCalledTimes(1);
	});

	it.each([false, true])('only the initiating device finalizes once (owner=%s)', async (owner) => {
		const { context } = fixture();
		const message = { id: 'answer', model: 'model', content: '', done: false };
		context.history.messages.answer = message;
		Object.assign(context, {
			ownedResponseMessageIds: new Set(owner ? ['answer'] : []),
			releaseResponseAnimationController: vi.fn().mockResolvedValue(undefined),
			clearPendingGeminiImages: vi.fn(),
			navigator: {},
			emitLatestMessageSentence: vi.fn(),
			$settings: {},
			$showCallOverlay: false,
			eventTarget: { dispatchEvent: vi.fn() },
			CustomEvent: class {
				constructor(
					public type: string,
					public options: unknown
				) {}
			},
			activeChatIds: { update: (fn) => fn(new Set(['current-chat'])) },
			createMessagesList: () => [message],
			chatCompletedHandler: vi.fn().mockResolvedValue(undefined)
		});
		const handler = createCompletionHandler(context);
		const data = { done: true, content: 'final', files: [{ type: 'image', url: '/image.png' }] };
		await handler(data, message, 'current-chat');
		await handler(data, message, 'current-chat');
		expect(message.content).toBe('final');
		expect(message.done).toBe(true);
		expect(context.history.messages.answer.files).toHaveLength(1);
		expect(context.chatCompletedHandler).toHaveBeenCalledTimes(owner ? 1 : 0);
	});
});
