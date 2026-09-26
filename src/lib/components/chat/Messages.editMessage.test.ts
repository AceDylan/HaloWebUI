import { readFileSync } from 'node:fs';
import { parse, preprocess } from 'svelte/compiler';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import { beforeAll, describe, expect, it, vi } from 'vitest';

// Runs the real editMessage() out of Messages.svelte (same technique as
// Chat.initNewChat.test.ts): an edited user message that is resent becomes a new
// user message, and it has to carry the Hermes choices (派发方式, model) the
// original was sent with, as regenerating a reply does. It used to drop them, so
// fixing a typo in a task handed to reclaude sent it to Hermes directly.

let editMessageSource: string;

beforeAll(async () => {
	// HALO_MESSAGES_COMPONENT_SOURCE runs the test against an older Messages.svelte.
	const filename =
		process.env.HALO_MESSAGES_COMPONENT_SOURCE ?? 'src/lib/components/chat/Messages.svelte';
	const { code } = await preprocess(readFileSync(filename, 'utf8'), vitePreprocess(), {
		filename
	});
	const declarations = parse(code).instance!.content.body.flatMap(
		(node: any) => node.declarations ?? []
	);
	const declaration = declarations.find((node: any) => node.id.name === 'editMessage');
	if (!declaration) throw new Error('Messages.svelte no longer declares editMessage');
	editMessageSource = code.slice(declaration.init.start, declaration.init.end);
});

const chat = (original: Record<string, any>) => {
	const history = {
		currentId: 'u1',
		messages: {
			u1: { id: 'u1', parentId: null, childrenIds: ['a1'], role: 'user', ...original },
			a1: { id: 'a1', parentId: 'u1', childrenIds: [], role: 'assistant', content: 'ok' }
		} as Record<string, any>
	};
	const store: Record<string, any> = {
		history,
		selectedModels: ['hermes-agent'],
		uuidv4: () => 'u2',
		tick: async () => undefined,
		sendPrompt: vi.fn(async () => undefined),
		updateChat: vi.fn(async () => undefined)
	};
	const context = new Proxy(store, {
		has: (target, key) => typeof key === 'string' && (key in target || !(key in globalThis)),
		get: (target, key) => (typeof key === 'string' && key in target ? target[key] : vi.fn()),
		set: (target, key, value) => {
			target[key as string] = value;
			return true;
		}
	});
	const editMessage = new Function('context', `with (context) { return (${editMessageSource}); }`)(
		context
	);
	return { history, store, editMessage };
};

describe('editMessage', () => {
	it('resends an edited message with the dispatch and model it was sent with', async () => {
		const sent = { dispatch: 'reclaude', model: 'claude-chat', provider: 'p' };
		const { history, store, editMessage } = chat({ content: 'fix teh bug', hermesOptions: sent });

		await editMessage('u1', 'fix the bug');

		const resent = history.messages.u2;
		expect(resent.content).toBe('fix the bug');
		expect(resent.hermesOptions).toEqual(sent);
		expect(resent.hermesOptions).not.toBe(sent);
		expect(store.sendPrompt).toHaveBeenCalledWith(history, 'fix the bug', 'u2');
	});

	it('adds nothing for a message sent without Hermes choices', async () => {
		const { history, editMessage } = chat({ content: 'hello' });

		await editMessage('u1', 'hello there');

		expect('hermesOptions' in history.messages.u2).toBe(false);
	});

	it('keeps the choices on an edit that is only saved', async () => {
		const sent = { dispatch: 'codex', model: '', provider: '' };
		const { history, editMessage } = chat({ content: 'a', hermesOptions: sent });

		await editMessage('u1', 'b', false);

		expect(history.messages.u1.content).toBe('b');
		expect(history.messages.u1.hermesOptions).toEqual(sent);
	});
});
