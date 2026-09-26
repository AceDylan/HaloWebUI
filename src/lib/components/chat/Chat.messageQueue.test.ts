import { readFileSync } from 'node:fs';
import { parse, preprocess } from 'svelte/compiler';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { hermesDispatchToRestore } from '$lib/utils/hermes';

// Runs the real editQueuedMessage() out of Chat.svelte (same technique as
// Chat.initNewChat.test.ts). A message queued with 派发方式 = reclaude had the
// dispatch taken off the panel when it was queued; taking it back to edit used to
// return only the text, so the edited message went to Hermes directly.

let source: string;
let drainSource: string;

beforeAll(async () => {
	const filename = process.env.HALO_CHAT_COMPONENT_SOURCE ?? 'src/lib/components/chat/Chat.svelte';
	const { code } = await preprocess(readFileSync(filename, 'utf8'), vitePreprocess(), { filename });
	const declarations = parse(code).instance!.content.body.flatMap(
		(node: any) => node.declarations ?? []
	);
	const take = (name: string) => {
		const declaration = declarations.find((node: any) => node.id.name === name);
		if (!declaration) throw new Error(`Chat.svelte no longer declares ${name}`);
		return code.slice(declaration.init.start, declaration.init.end);
	};
	source = take('editQueuedMessage');
	drainSource = take('drainQueuedMessage');
});

const composer = (queued: Record<string, any>, input: Record<string, any> = {}) => {
	const store: Record<string, any> = {
		prompt: '',
		files: [],
		...input,
		hermesOptions: { dispatch: '', model: 'gemini-chat', provider: '' },
		hermesDispatchToRestore,
		messageQueue: [
			{ id: 'q1', chatId: 'c', prompt: 'fix it', files: [{ id: 'f' }], ...queued },
			{ id: 'q2', chatId: 'c', prompt: 'later', files: [] }
		]
	};
	const context = new Proxy(store, {
		has: (target, key) => typeof key === 'string' && (key in target || !(key in globalThis)),
		get: (target, key) => (typeof key === 'string' && key in target ? target[key] : vi.fn()),
		set: (target, key, value) => {
			target[key as string] = value;
			return true;
		}
	});
	const edit = new Function('context', `with (context) { return (${source}); }`)(context);
	return { store, edit };
};

describe('editQueuedMessage', () => {
	it('returns the text, the files and the dispatch to the input', () => {
		const { store, edit } = composer({
			hermesOptions: { dispatch: 'reclaude', model: 'claude-chat', provider: '' }
		});

		edit('q1');

		expect(store.prompt).toBe('fix it');
		expect(store.files).toEqual([{ id: 'f' }]);
		// The dispatch comes back; the chat's model stays what the panel shows now.
		expect(store.hermesOptions).toEqual({ dispatch: 'reclaude', model: 'gemini-chat', provider: '' });
		expect(store.messageQueue.map((item: any) => item.id)).toEqual(['q2']);
	});

	it('puts a follow-up back on following the chat, not on a new task', () => {
		const { store, edit } = composer({
			hermesOptions: {
				dispatch: 'reclaude',
				model: '',
				provider: '',
				continue_run: '20260927-005655-f2dd355f'
			}
		});

		edit('q1');

		expect(store.hermesOptions).toEqual({ dispatch: '', model: 'gemini-chat', provider: '' });
	});

	it('leaves the panel alone for a message queued without a dispatch', () => {
		const { store, edit } = composer({ hermesOptions: null });

		edit('q1');

		expect(store.hermesOptions).toEqual({ dispatch: '', model: 'gemini-chat', provider: '' });
		expect(store.prompt).toBe('fix it');
	});

	it('keeps what is already in the input, after the queued text', () => {
		const { store, edit } = composer(
			{ hermesOptions: null },
			{ prompt: 'and also this', files: [{ id: 'draft' }] }
		);

		edit('q1');

		expect(store.prompt).toBe('fix it\n\nand also this');
		expect(store.files).toEqual([{ id: 'f' }, { id: 'draft' }]);
	});
});

describe('drainQueuedMessage', () => {
	const drainer = (state: Record<string, any> = {}) => {
		const submitPrompt = vi.fn(async () => {});
		const store: Record<string, any> = {
			$chatId: 'c',
			taskIds: [],
			history: { currentId: 'a', messages: { a: { id: 'a', done: true } } },
			prompt: 'half-typed thought',
			files: [{ id: 'draft' }],
			drainingQueue: false,
			submitPrompt,
			messageQueue: [
				{ id: 'q1', chatId: 'c', prompt: 'queued', files: [{ id: 'f' }], hermesOptions: null },
				{ id: 'q2', chatId: 'c', prompt: 'later', files: [] }
			],
			...state
		};
		const context = new Proxy(store, {
			has: (target, key) => typeof key === 'string' && (key in target || !(key in globalThis)),
			get: (target, key) => (typeof key === 'string' && key in target ? target[key] : vi.fn()),
			set: (target, key, value) => {
				target[key as string] = value;
				return true;
			}
		});
		const drain = new Function('context', `with (context) { return (${drainSource}); }`)(context);
		return { store, drain, submitPrompt };
	};

	it('sends the next message with its own files and leaves the input alone', async () => {
		const { store, drain, submitPrompt } = drainer();

		await drain('c');

		expect(submitPrompt).toHaveBeenCalledTimes(1);
		expect(submitPrompt).toHaveBeenCalledWith('queued', {
			referenceFiles: [],
			hermesOptions: null,
			queuedFiles: [{ id: 'f' }]
		});
		expect(store.prompt).toBe('half-typed thought');
		expect(store.files).toEqual([{ id: 'draft' }]);
		expect(store.messageQueue.map((item: any) => item.id)).toEqual(['q2']);
	});

	it('sends one message at a time and waits while a reply runs', async () => {
		let release!: () => void;
		const { store, drain, submitPrompt } = drainer();
		submitPrompt.mockImplementation(() => new Promise<void>((resolve) => (release = resolve)));

		const first = drain('c');
		await drain('c'); // a sync lands while the first is still going out
		expect(submitPrompt).toHaveBeenCalledTimes(1);
		release();
		await first;

		store.taskIds = ['t'];
		await drain('c');
		expect(submitPrompt).toHaveBeenCalledTimes(1);
		expect(store.messageQueue.map((item: any) => item.id)).toEqual(['q2']);
	});
});
