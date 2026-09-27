import { readFileSync } from 'node:fs';
import { parse, preprocess } from 'svelte/compiler';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import { beforeAll, describe, expect, it, vi } from 'vitest';

// Runs Messages.svelte's real editMessage against a fake component state: an
// edited message sent while the chat's reply is still running stops that reply
// first. Same technique as Chat.webSearch.test.ts.

let sourceOf: (name: string) => string;

beforeAll(async () => {
	const filename = 'src/lib/components/chat/Messages.svelte';
	const { code } = await preprocess(readFileSync(filename, 'utf8'), vitePreprocess(), {
		filename
	});
	const ast = parse(code);
	const declarations = ast.instance!.content.body.flatMap((node: any) => node.declarations ?? []);
	sourceOf = (name) => {
		const declaration = declarations.find((node: any) => node.id.name === name);
		if (!declaration) {
			throw new Error(`Messages.svelte no longer declares ${name}`);
		}
		return code.slice(declaration.init.start, declaration.init.end);
	};
});

const chatWith = (replyDone: boolean | undefined) => {
	const history = {
		currentId: 'a1',
		messages: {
			u1: { id: 'u1', parentId: null, childrenIds: ['a1'], role: 'user', content: 'sleep 45' },
			a1: {
				id: 'a1',
				parentId: 'u1',
				childrenIds: [],
				role: 'assistant',
				content: '',
				...(replyDone === undefined ? {} : { done: replyDone })
			}
		}
	};
	const calls: string[] = [];
	const context: Record<string, any> = {
		history,
		selectedModels: ['hermes-agent'],
		$i18n: { t: (key: string) => key },
		toast: { info: vi.fn() },
		tick: async () => {},
		uuidv4: () => 'u2',
		updateChat: vi.fn(),
		stopResponse: vi.fn(async () => {
			calls.push('stop');
		}),
		sendPrompt: vi.fn(async () => {
			calls.push('send');
		})
	};
	for (const name of ['replyRunning', 'editMessage']) {
		context[name] = new Function('context', `with (context) { return ${sourceOf(name)}; }`)(
			context
		);
	}
	return { context, calls };
};

describe('editing a message and sending it', () => {
	it('stops the reply still running, then sends the edit', async () => {
		const { context, calls } = chatWith(undefined);
		await context.editMessage('u1', 'just say hi');
		expect(calls).toEqual(['stop', 'send']);
		expect(context.toast.info).toHaveBeenCalledWith(
			'The reply that was running has been stopped.'
		);
		expect(context.history.messages.u2.content).toBe('just say hi');
	});

	it('leaves a finished reply alone', async () => {
		const { context, calls } = chatWith(true);
		await context.editMessage('u1', 'just say hi');
		expect(calls).toEqual(['send']);
		expect(context.toast.info).not.toHaveBeenCalled();
	});

	it('does not stop anything for an edit that is only saved', async () => {
		const { context, calls } = chatWith(undefined);
		await context.editMessage('u1', 'just say hi', false);
		expect(calls).toEqual([]);
		expect(context.updateChat).toHaveBeenCalled();
	});
});
