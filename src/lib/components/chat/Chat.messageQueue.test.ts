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

beforeAll(async () => {
	const filename = process.env.HALO_CHAT_COMPONENT_SOURCE ?? 'src/lib/components/chat/Chat.svelte';
	const { code } = await preprocess(readFileSync(filename, 'utf8'), vitePreprocess(), { filename });
	const declarations = parse(code).instance!.content.body.flatMap(
		(node: any) => node.declarations ?? []
	);
	const declaration = declarations.find((node: any) => node.id.name === 'editQueuedMessage');
	if (!declaration) throw new Error('Chat.svelte no longer declares editQueuedMessage');
	source = code.slice(declaration.init.start, declaration.init.end);
});

const composer = (queued: Record<string, any>) => {
	const store: Record<string, any> = {
		prompt: '',
		files: [],
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
});
