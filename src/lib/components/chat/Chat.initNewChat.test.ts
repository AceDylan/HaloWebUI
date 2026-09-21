import { readFileSync } from 'node:fs';
import { parse, preprocess } from 'svelte/compiler';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import { beforeAll, describe, expect, it, vi } from 'vitest';

import { takeLandingPrompt } from '$lib/utils/chat-landing';
import { resolveAvailableChatModelSelectionValues } from '$lib/utils/chat-model-recovery';
import { getTemporaryChatNavigationPath } from '$lib/utils/temporary-chat';

// Runs the real initNewChat() and the real chatId subscriber (onChatIdCleared) out of
// Chat.svelte against a fake page: the address bar, the stores and the API boundaries
// are replaced, nothing else. Same technique as Chat.events.test.ts.
//
// The scenario is the Bookmark Hub's "send to AI chat": the page lands on
// /?q=<question>&models=<model>, sends the question, and the first message turns the
// address into /c/<id> through shallow routing — which leaves SvelteKit's $page.url
// untouched. Every later initNewChat() in that page instance used to read the same
// ?q= again and send the same question again (two POST /api/v1/chats/new 70 ms apart
// in the production log, one of them an orphan).

let code: string;
let sourceOf: (name: string) => string;

beforeAll(async () => {
	// HALO_CHAT_COMPONENT_SOURCE lets the same test run against an older Chat.svelte, to
	// see it fail where it should (git show <rev>:src/lib/components/chat/Chat.svelte > /tmp/old.svelte).
	const filename = process.env.HALO_CHAT_COMPONENT_SOURCE ?? 'src/lib/components/chat/Chat.svelte';
	({ code } = await preprocess(readFileSync(filename, 'utf8'), vitePreprocess(), { filename }));
	const ast = parse(code);
	const declarations = ast.instance!.content.body.flatMap((node: any) => node.declarations ?? []);
	sourceOf = (name) => {
		const declaration = declarations.find((node: any) => node.id.name === name);
		if (!declaration) {
			throw new Error(`Chat.svelte no longer declares ${name}`);
		}
		return code.slice(declaration.init.start, declaration.init.end);
	};
});

const GPT_CHAT = {
	id: 'modelref::openai::personal::id:13c104eb::gpt-chat',
	name: 'gpt-chat',
	model_id: 'gpt-chat',
	model_ref: { provider: 'openai', source: 'personal', connection_id: '13c104eb' }
};
const HERMES_AGENT = {
	id: 'modelref::openai::personal::id:ee5e02db::hermes-agent',
	name: 'hermes-agent',
	model_id: 'hermes-agent',
	model_ref: { provider: 'openai', source: 'personal', connection_id: 'ee5e02db' }
};

const noopStore = () => ({ set: vi.fn(async () => undefined), update: vi.fn() });

// Everything initNewChat touches, with the page landing on `href`. Unknown identifiers
// resolve to a shared no-op so the test is about the flow, not the whole component.
const page = (href: string, overrides: Record<string, any> = {}) => {
	const location = { href: new URL(href).href };
	const chatIdSubscribers: Array<(value: string) => unknown> = [];
	const chatId = {
		value: '',
		set: vi.fn((value: string) => {
			if (value === chatId.value) return;
			chatId.value = value;
			for (const fn of chatIdSubscribers) fn(value);
		}),
		subscribe: (fn: (value: string) => unknown) => {
			chatIdSubscribers.push(fn);
			fn(chatId.value);
		}
	};
	const store: Record<string, any> = {
		window: {
			get location() {
				return new URL(location.href);
			}
		},
		document: { getElementById: () => null },
		localStorage: { token: 'token' },
		sessionStorage: { getItem: () => null, removeItem: vi.fn(), setItem: vi.fn() },
		$page: { url: new URL(href), state: {} }, // never changes: SvelteKit only updates it on a real navigation
		replaceState: vi.fn((path: string) => {
			location.href = new URL(path, location.href).href;
		}),
		chatId,
		chatTitle: noopStore(),
		showControls: noopStore(),
		showCallOverlay: noopStore(),
		showOverview: noopStore(),
		showArtifacts: noopStore(),
		expandedSelectionThreadId: noopStore(),
		selectedAssistantScene: noopStore(),
		settings: noopStore(),
		$models: [GPT_CHAT, HERMES_AGENT],
		modelsMap: new Map([GPT_CHAT, HERMES_AGENT].map((m) => [m.id, m])),
		$settings: { models: [HERMES_AGENT.id] },
		$selectedAssistantScene: null,
		get: () => ({}),
		getModelById: (id: string) => [GPT_CHAT, HERMES_AGENT].find((m) => m.id === id) ?? null,
		getCanonicalModelId: (id: string) => id,
		getModelSelectionId: (m: any) => m.id,
		resolveAvailableChatModelSelectionValues,
		getTemporaryChatNavigationPath,
		takeLandingPrompt,
		getNewChatStateInheritanceEnabled: () => false,
		syncTemporaryChatState: () => ({
			enabled: false,
			defaultEnabled: false,
			enforced: false,
			allowed: true
		}),
		getPreferredDefaultWebSearchMode: () => 'off',
		createEmptySelectionThreads: () => ({}),
		safeParseStoredJson: (_v: unknown, fallback: unknown) => fallback,
		toChatAssistantSnapshot: () => null,
		PENDING_ASSISTANT_STORAGE_KEY: 'pending-assistant',
		ensureModels: vi.fn(async () => undefined),
		getUserSettings: vi.fn(async () => ({ ui: {} })),
		submitPrompt: vi.fn(),
		tick: vi.fn(async () => undefined),
		clearingChatIdForNewChat: false,
		activeChatLoadToken: 0,
		loading: false,
		freshChatActive: false,
		selectedModels: [''],
		messageQueue: [],
		history: { messages: {}, currentId: null },
		prompt: '',
		files: [],
		chatFiles: [],
		params: {},
		selectedToolIds: [],
		selectedSkillIds: [],
		...overrides
	};
	const stubs: Record<string, any> = {};
	const context = new Proxy(store, {
		has: (target, key) => typeof key === 'string' && (key in target || !(key in globalThis)),
		get: (target, key) => {
			if (typeof key !== 'string') return undefined;
			if (key in target) return target[key];
			return (stubs[key] ??= vi.fn());
		},
		set: (target, key, value) => {
			target[key as string] = value;
			return true;
		}
	});
	const build = (name: string) =>
		new Function('context', `with (context) { return ${sourceOf(name)}; }`)(context);
	store.initNewChat = vi.fn(build('initNewChat'));
	// what onMount does on the "/" route (the inline fallback is the pre-fix subscriber)
	let onChatIdCleared: (value: string) => unknown;
	try {
		onChatIdCleared = build('onChatIdCleared');
	} catch {
		onChatIdCleared = async (value: string) => {
			if (!value) {
				await store.tick();
				await store.initNewChat();
			}
		};
	}
	chatId.subscribe(onChatIdCleared);
	return { store, location, chatId, runs: () => store.initNewChat.mock.calls.length };
};

const HUB_LANDING = `https://halo.example/?q=${encodeURIComponent('你能做什么')}&models=${encodeURIComponent(GPT_CHAT.id)}`;

describe('a question landing in the address (?q=, what the Bookmark Hub sends)', () => {
	it('is sent once, on the model the address names, and taken out of the address', async () => {
		const { store, location } = page(HUB_LANDING);
		// mounting on "/" ran initNewChat through the chatId subscriber
		await vi.waitFor(() => expect(store.submitPrompt).toHaveBeenCalledTimes(1));

		expect(store.submitPrompt).toHaveBeenCalledWith('你能做什么');
		expect(store.selectedModels).toEqual([GPT_CHAT.id]);
		expect(new URL(location.href).searchParams.get('q')).toBeNull();
		expect(new URL(location.href).searchParams.get('models')).toBe(GPT_CHAT.id);
		// the premise of the bug: SvelteKit's $page.url still carries the question
		expect(store.$page.url.searchParams.get('q')).toBe('你能做什么');
	});

	it('is not sent again by the next new chat in the same page instance', async () => {
		const { store, location, chatId } = page(HUB_LANDING);
		await vi.waitFor(() => expect(store.submitPrompt).toHaveBeenCalledTimes(1));

		// what initChatHandler does once the first message created the chat
		chatId.set('chat-1');
		store.replaceState('/c/chat-1');

		// the sidebar's "New chat" (requestNewChat → initNewChat)
		await store.initNewChat({ fresh: false });

		expect(store.submitPrompt).toHaveBeenCalledTimes(1);
		expect(store.chatId.value).toBe('');
		// the account default is back, not the model the Hub pinned to its one question
		expect(store.selectedModels).toEqual([HERMES_AGENT.id]);
		// and the address left the old chat behind
		expect(new URL(location.href).pathname).toBe('/');
	});

	it('waits for the model list when the page opens with none', async () => {
		const order: string[] = [];
		const { store } = page(HUB_LANDING, {
			$models: [],
			modelsMap: new Map(),
			ensureModels: vi.fn(async () => {
				order.push('models');
				store.$models = [GPT_CHAT, HERMES_AGENT];
			}),
			submitPrompt: vi.fn(() => order.push('submit'))
		});
		await vi.waitFor(() => expect(store.submitPrompt).toHaveBeenCalledTimes(1));

		expect(order).toEqual(['models', 'submit']);
	});

	it('sends nothing when the address has no question', async () => {
		const { store } = page('https://halo.example/');
		await vi.waitFor(() => expect(store.getUserSettings).toHaveBeenCalled());

		expect(store.submitPrompt).not.toHaveBeenCalled();
	});
});

describe('starting a new chat while one is open', () => {
	it('runs initNewChat once, not again through its own clearing of $chatId', async () => {
		const { store, chatId, runs } = page('https://halo.example/');
		await vi.waitFor(() => expect(store.getUserSettings).toHaveBeenCalledTimes(1));
		chatId.set('chat-1');
		const before = runs();

		// the navbar's "New chat" asks for a fresh one
		await store.initNewChat({ fresh: true });
		await new Promise((r) => setTimeout(r, 0)); // a re-entrant run would queue behind a tick

		expect(runs()).toBe(before + 1);
		expect(store.chatId.value).toBe('');
		expect(store.freshChatActive).toBe(true);
		expect(store.clearingChatIdForNewChat).toBe(false);
	});

	it('still opens a new chat when something else clears $chatId (delete, archive, assistant scene)', async () => {
		const { store, chatId, runs } = page('https://halo.example/');
		await vi.waitFor(() => expect(store.getUserSettings).toHaveBeenCalledTimes(1));
		chatId.set('chat-1');
		const before = runs();

		chatId.set('');
		await vi.waitFor(() => expect(runs()).toBe(before + 1));
	});
});
