import { readFileSync } from 'node:fs';
import { parse, preprocess } from 'svelte/compiler';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import { beforeAll, describe, expect, it, vi } from 'vitest';
import {
	findHermesContinuation,
	hermesOptionsForMessage,
	hermesOptionsToKeep
} from '$lib/utils/hermes';

// Runs the real takeHermesOptionsForMessage() out of Chat.svelte (same technique
// as Chat.messageQueue.test.ts). After an exclusive reclaude run reported back,
// the next message left on "直接" was answered by hermes' model instead of going
// back to that run: 2026-09-27, "多久观察一次" after "如何破局呢".

let source: string;
let template: any;

beforeAll(async () => {
	const filename = process.env.HALO_CHAT_COMPONENT_SOURCE ?? 'src/lib/components/chat/Chat.svelte';
	const { code } = await preprocess(readFileSync(filename, 'utf8'), vitePreprocess(), { filename });
	const ast = parse(code);
	template = ast.html;
	const declarations = ast.instance!.content.body.flatMap(
		(node: any) => node.declarations ?? []
	);
	const declaration = declarations.find(
		(node: any) => node.id.name === 'takeHermesOptionsForMessage'
	);
	if (!declaration) throw new Error('Chat.svelte no longer declares takeHermesOptionsForMessage');
	source = code.slice(declaration.init.start, declaration.init.end);
});

const runId = '20260927-005655-f2dd355f';

const composer = (dispatch = '') => {
	const store: Record<string, any> = {
		showHermesOptions: true,
		hermesOptions: { dispatch, model: 'gpt-chat', provider: 'custom' },
		history: {
			currentId: 'report',
			messages: {
				notice: {
					id: 'notice',
					role: 'user',
					content: `[后台任务完成通知] reclaude 运行 ${runId} 已结束，状态：success，Claude 会话：s。`
				},
				report: { id: 'report', parentId: 'notice', role: 'assistant', done: true, content: '✅' },
				hermesReply: { id: 'hermesReply', parentId: 'report', role: 'assistant', done: true }
			}
		},
		findHermesContinuation,
		hermesOptionsForMessage,
		hermesOptionsToKeep
	};
	const context = new Proxy(store, {
		has: (target, key) => typeof key === 'string' && (key in target || !(key in globalThis)),
		get: (target, key) => (typeof key === 'string' && key in target ? target[key] : vi.fn()),
		set: (target, key, value) => {
			target[key as string] = value;
			return true;
		}
	});
	const take = new Function('context', `with (context) { return (${source}); }`)(context);
	return { store, take };
};

describe('takeHermesOptionsForMessage after a runner report', () => {
	it('sends a message left on "直接" back to the run', () => {
		const { store, take } = composer();
		expect(take('多久观察一次？')).toEqual({
			dispatch: 'reclaude',
			model: 'gpt-chat',
			provider: 'custom',
			continue_run: runId
		});
		// Nothing to reset: the panel keeps following the chat.
		expect(store.hermesOptions.dispatch).toBe('');
	});

	it('leaves it to hermes when "直接" was picked, and resets the panel', () => {
		const { store, take } = composer('hermes');
		expect(take('多久观察一次？')).toEqual({ dispatch: '', model: 'gpt-chat', provider: 'custom' });
		expect(store.hermesOptions.dispatch).toBe('');
	});

	it('follows the message it answers, not the end of the chat', () => {
		const { take } = composer();
		// submitMessage(parentId, …) under a later reply: no report above it.
		expect(take('x', 'hermesReply').continue_run).toBeUndefined();
		expect(take('/reclaude 新任务').continue_run).toBeUndefined();
	});
});

describe('the composer under a chat', () => {
	// 05420ac passed the continuation to <Placeholder>, the empty new-chat page,
	// which never ends on a report (and has no such prop), not to the composer
	// under a chat: after a report the button still read "Hermes" and the panel
	// "直接", with no "接着上次" (2026-09-27, chat 9d3eb38b). A message sent from
	// there still went back to the run, whatever the panel said.
	const components = (name: string) => {
		const found: any[] = [];
		const walk = (node: any) => {
			if (!node || typeof node !== 'object') return;
			if (node.type === 'InlineComponent' && node.name === name) found.push(node);
			for (const value of Object.values(node)) {
				if (Array.isArray(value)) value.forEach(walk);
				else if (value && typeof value === 'object' && (value as any).type) walk(value);
			}
		};
		walk(template);
		return found;
	};
	const passes = (node: any, prop: string) =>
		node.attributes.some((attribute: any) => attribute.name === prop);

	it('is told which run the next message goes back to', () => {
		const inputs = components('MessageInput');
		expect(inputs.length).toBeGreaterThan(0);
		expect(inputs.map((node) => passes(node, 'hermesContinuation'))).toEqual(
			inputs.map(() => true)
		);
	});

	it('is not handed to the new-chat page, which has nothing to go back to', () => {
		expect(components('Placeholder').some((node) => passes(node, 'hermesContinuation'))).toBe(
			false
		);
	});
});
