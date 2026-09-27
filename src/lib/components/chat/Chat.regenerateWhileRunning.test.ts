import { readFileSync } from 'node:fs';
import { parse, preprocess } from 'svelte/compiler';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import { beforeAll, describe, expect, it, vi } from 'vitest';

// Runs Chat.svelte's real regenerateResponse against a fake component state:
// answering an earlier reply again while the latest one still runs stops the
// latest (it is on the branch being left). Same technique as
// Chat.webSearch.test.ts.

let sourceOf: (name: string) => string;

beforeAll(async () => {
	const filename = process.env.HALO_CHAT_COMPONENT_SOURCE ?? 'src/lib/components/chat/Chat.svelte';
	const { code } = await preprocess(readFileSync(filename, 'utf8'), vitePreprocess(), {
		filename
	});
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

// u1 -> a1 (done) -> u2 -> a2 (latest), plus a2b: another model's reply to u2.
const chat = (latestDone: boolean) => {
	const history = {
		currentId: 'a2',
		messages: {
			u1: { id: 'u1', parentId: null, childrenIds: ['a1'], role: 'user', content: 'first' },
			a1: { id: 'a1', parentId: 'u1', childrenIds: ['u2'], role: 'assistant', done: true },
			u2: { id: 'u2', parentId: 'a1', childrenIds: ['a2', 'a2b'], role: 'user', content: 'second' },
			a2: { id: 'a2', parentId: 'u2', childrenIds: [], role: 'assistant', done: latestDone },
			a2b: { id: 'a2b', parentId: 'u2', childrenIds: [], role: 'assistant', done: true }
		}
	};
	const calls: string[] = [];
	const context: Record<string, any> = {
		history,
		$config: {},
		$i18n: { t: (key: string) => key },
		toast: { info: vi.fn() },
		isHermesAgentModelId: () => false,
		confirmHermesRerun: async () => true,
		autoScroll: false,
		reasoningEffort: null,
		webSearchMode: 'off',
		_pendingInstruction: null,
		atSelectedModel: undefined,
		selectedModels: ['gpt-chat'],
		stopResponse: vi.fn(async () => {
			calls.push('stop');
		}),
		sendPrompt: vi.fn(async () => {
			calls.push('send');
		})
	};
	context.regenerateResponse = new Function(
		'context',
		`with (context) { return ${sourceOf('regenerateResponse')}; }`
	)(context);
	return { context, calls, history };
};

describe('answering a reply again', () => {
	it('stops the latest reply when an earlier one is answered again', async () => {
		const { context, calls, history } = chat(false);
		await context.regenerateResponse(history.messages.a1);
		expect(calls).toEqual(['stop', 'send']);
		expect(context.toast.info).toHaveBeenCalledWith(
			'The reply that was running has been stopped.'
		);
	});

	it('leaves the latest reply running when another reply of its turn is redone', async () => {
		const { context, calls, history } = chat(false);
		await context.regenerateResponse(history.messages.a2b);
		expect(calls).toEqual(['send']);
	});

	it('stops nothing when nothing is running', async () => {
		const { context, calls, history } = chat(true);
		await context.regenerateResponse(history.messages.a1);
		expect(calls).toEqual(['send']);
	});
});
