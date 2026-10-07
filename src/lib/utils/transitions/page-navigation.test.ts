import { readFileSync } from 'node:fs';
import { parse, preprocess } from 'svelte/compiler';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import { beforeAll, describe, expect, it, vi } from 'vitest';

// Exercise the real layout navigation callback at the browser API boundary.
let callbackSource: string;
beforeAll(async () => {
	const filename = 'src/routes/(app)/+layout.svelte';
	const { code } = await preprocess(readFileSync(filename, 'utf8'), vitePreprocess(), { filename });
	const registration = parse(code).instance!.content.body.find(
		(node: any) => node.expression?.callee?.name === 'onNavigate'
	) as any;
	const callback = registration.expression.arguments[0];
	callbackSource = code.slice(callback.start, callback.end);
});

const navigate = (
	from: string,
	to: string,
	type = 'link',
	activeViewTransition?: { skipTransition: () => void },
	media: (query: string) => boolean = () => false
) => {
	const transition = {
		ready: Promise.resolve(),
		finished: Promise.resolve(),
		skipTransition: vi.fn()
	};
	const startViewTransition = vi.fn((update: () => Promise<void>) => {
		void update();
		return transition;
	});
	const guardViewTransition = vi.fn();
	const context = {
		document: {
			startViewTransition,
			activeViewTransition,
			documentElement: { style: { setProperty: vi.fn() } }
		},
		window: { matchMedia: (query: string) => ({ matches: media(query) }) },
		scifiOn: false,
		guardViewTransition
	};
	const callback = new Function('context', `with (context) { return ${callbackSource}; }`)(context);
	const result = callback({
		from: { url: new URL(from, 'https://halo.example') },
		to: { url: new URL(to, 'https://halo.example') },
		type,
		delta: -1,
		willUnload: false,
		complete: Promise.resolve()
	});
	return { startViewTransition, guardViewTransition, transition, result };
};

describe('chat page navigation', () => {
	it.each(['/', '/c/previous', '/teams', '/answer', '/discuss', '/workspace/images'])(
		'opens chat history from %s without a snapshot over the messages',
		(from) => {
			const { startViewTransition, result } = navigate(from, '/c/target');
			expect(startViewTransition).not.toHaveBeenCalled();
			expect(result).toBeUndefined();
		}
	);

	it.each(['/teams', '/answer', '/c/previous'])(
		'opens the chat home from %s without a snapshot',
		(from) => {
			const { startViewTransition } = navigate(from, '/?fresh-chat=true');
			expect(startViewTransition).not.toHaveBeenCalled();
		}
	);

	it('does not snapshot chat history when leaving it', () => {
		const { startViewTransition } = navigate('/c/previous', '/teams');
		expect(startViewTransition).not.toHaveBeenCalled();
	});

	it('opens a chat immediately when going back in browser history', () => {
		const { startViewTransition, result } = navigate('/teams', '/c/previous', 'popstate');
		expect(startViewTransition).not.toHaveBeenCalled();
		expect(result).toBeUndefined();
	});

	it('removes the previous page snapshot when a rapid click opens a chat', () => {
		const active = { skipTransition: vi.fn() };
		const { startViewTransition, result } = navigate('/teams', '/c/target', 'link', active);
		expect(active.skipTransition).toHaveBeenCalledTimes(1);
		expect(startViewTransition).not.toHaveBeenCalled();
		expect(result).toBeUndefined();
	});

	it('runs a guarded transition between other pages', async () => {
		const { startViewTransition, guardViewTransition, transition, result } = navigate(
			'/teams',
			'/discuss'
		);
		await result;
		expect(startViewTransition).toHaveBeenCalledTimes(1);
		expect(guardViewTransition).toHaveBeenCalledWith(transition, {
			onGiveUp: expect.any(Function)
		});
	});

	it('takes no snapshot on a phone: the panel is the whole screen there', () => {
		const active = { skipTransition: vi.fn() };
		const phone = (query: string) => query.includes('max-width: 767px') && query.includes('pointer: coarse');
		const { startViewTransition, result } = navigate('/teams', '/discuss', 'link', active, phone);
		expect(startViewTransition).not.toHaveBeenCalled();
		expect(active.skipTransition).toHaveBeenCalledTimes(1);
		expect(result).toBeUndefined();
	});
});
