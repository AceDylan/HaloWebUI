// Exercise the public DOM while driving browser frames and flight completion deterministically.
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

let Orbit: any;
let stores: any;
let app: any;
let target: HTMLElement;
let now = 0;
let measured = true;
let nextFrame = 0;
const frames = new Map<number, FrameRequestCallback>();
const mediaListeners = new Set<() => void>();
const media = {
	matches: false,
	addEventListener: (_: string, listener: () => void) => mediaListeners.add(listener),
	removeEventListener: (_: string, listener: () => void) => mediaListeners.delete(listener)
};
const flights: any[] = [];
const names = [
	'hermes-agent',
	'gpt-chat',
	'deepseek-chat',
	'gpt-image',
	'gemini-chat',
	'claude-chat',
	'kimi-chat',
	'qwen-chat'
];
const models = names.map((name) => ({
	id: name,
	name,
	owned_by: 'openai',
	selection_id: name,
	info: { meta: { profile_image_url: '/static/favicon.png' } }
}));

const flush = async () => {
	for (let i = 0; i < 5; i++) await Promise.resolve();
};
const advance = async (dt = 50) => {
	now += dt;
	const pending = [...frames.values()];
	frames.clear();
	pending.forEach((callback) => callback(now));
	await flush();
};
const seat = (id: string) => target.querySelector(`[data-halo-model-card="${id}"]`)!.parentElement!;
const position = (id = 'gpt-chat') => seat(id).style.transform;
const event = async (id: string, type: string) => {
	seat(id).querySelector('button')!.dispatchEvent(new Event(type));
	await flush();
};
const mount = async () => {
	target = document.createElement('div');
	document.body.appendChild(target);
	app = new Orbit({ target, props: { selected: models[0], onSelect: vi.fn() } });
	await flush();
};

beforeAll(async () => {
	Object.defineProperties(Element.prototype, {
		clientWidth: { configurable: true, get: () => (measured ? 390 : 0) },
		clientHeight: { configurable: true, get: () => (measured ? 400 : 0) },
		animate: {
			configurable: true,
			value: function (keyframes: any[]) {
				const run = {
					el: this,
					keyframes,
					onfinish: () => {},
					oncancel: () => {},
					cancel() {
						this.oncancel();
					}
				};
				flights.push(run);
				return run;
			}
		}
	});
	stores = await import('$lib/stores');
	Orbit = (await import('./ModelOrbit.svelte')).default;
}, 60000);

beforeEach(() => {
	now = 0;
	measured = true;
	media.matches = false;
	flights.length = 0;
	vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
		frames.set(++nextFrame, callback);
		return nextFrame;
	});
	vi.stubGlobal('cancelAnimationFrame', (id: number) => frames.delete(id));
	vi.spyOn(window, 'matchMedia').mockReturnValue(media as any);
	stores.models.set(models);
	stores.config.set({ hermes_agent_model_ids: ['hermes-agent'] });
	stores.settings.set({ pinnedModels: ['hermes-agent'] });
});

afterEach(() => {
	app?.$destroy();
	app = null;
	document.body.innerHTML = '';
	frames.clear();
	mediaListeners.clear();
	vi.restoreAllMocks();
	vi.unstubAllGlobals();
});

describe('ModelOrbit motion', () => {
	it('advances clockwise at four degrees per second and caps a hidden-tab gap', async () => {
		await mount();
		await advance();
		const initial = position();
		const wire = () => target.querySelector('.halo-orbit__wire')!.getAttribute('d');
		const initialWire = wire();
		await advance();
		expect(position()).not.toBe(initial);
		expect(wire()).not.toBe(initialWire);
		const dock = target.querySelector('.halo-orbit__dock')!;
		// At twelve o'clock a positive angle moves right; 50ms corresponds to 0.2 degrees.
		expect(Number(dock.getAttribute('cx'))).toBeCloseTo(
			195 + 151 * Math.sin((0.2 * Math.PI) / 180),
			4
		);
		await advance(60000);
		expect(Number(dock.getAttribute('cx'))).toBeCloseTo(
			195 + 151 * Math.sin((0.4 * Math.PI) / 180),
			4
		);
	});

	it('pauses on core hover or node focus and resumes without consuming paused time', async () => {
		await mount();
		await advance();
		await advance();
		const paused = position();
		await event('hermes-agent', 'pointerenter');
		await advance(5000);
		expect(position()).toBe(paused);
		await event('gpt-chat', 'focus');
		await event('hermes-agent', 'pointerleave');
		await advance(5000);
		expect(position()).toBe(paused);
		await event('gpt-chat', 'blur');
		await advance(5000);
		expect(position()).toBe(paused);
		await advance();
		expect(position()).not.toBe(paused);
		// the core keeps focus after a click: that alone does not hold the orbit
		const moving = position();
		await event('hermes-agent', 'focus');
		await advance();
		await advance();
		expect(position()).not.toBe(moving);
	});

	it('freezes the rotated seats until both exchange flights finish', async () => {
		await mount();
		await advance();
		await advance();
		const fromRing = position();
		const fromCore = position('hermes-agent');
		app.$set({ selected: models[1] });
		await flush();
		expect(flights).toHaveLength(2);
		expect(flights[0].keyframes[0].transform).toBe(fromRing);
		expect(flights[1].keyframes[0].transform).toBe(fromCore);
		expect(flights[1].keyframes.at(-1).transform).toBe(fromRing);
		const wire = target.querySelector('.halo-orbit__wire')!.getAttribute('d');
		await advance(900);
		expect(target.querySelector('.halo-orbit__wire')!.getAttribute('d')).toBe(wire);
		flights[0].onfinish();
		await advance();
		expect(target.querySelector('.halo-orbit__wire')!.getAttribute('d')).toBe(wire);
		flights[1].onfinish();
		await flush();
		await advance();
		await advance();
		expect(position('hermes-agent')).not.toBe(fromRing);
		expect(target.querySelectorAll('.is-flying')).toHaveLength(0);
	});

	it('stays at spin zero for reduced motion, including a live preference change', async () => {
		media.matches = true;
		await mount();
		const initial = position();
		await advance();
		await advance(5000);
		expect(position()).toBe(initial);
		media.matches = false;
		mediaListeners.forEach((listener) => listener());
		await advance();
		await advance();
		expect(position()).not.toBe(initial);
		media.matches = true;
		mediaListeners.forEach((listener) => listener());
		await flush();
		expect(position()).toBe(initial);
		app.$set({ selected: models[1] });
		await flush();
		expect(flights).toHaveLength(0);
	});

	it('keeps the greeting outside the toolbar and Home returns focus to the core', async () => {
		await mount();
		const stage = target.querySelector('[role="toolbar"]')!;
		const greeting = target.querySelector('.halo-orbit__greeting')!;
		expect(stage.contains(greeting)).toBe(false);
		expect(greeting.previousElementSibling).toBe(stage);
		const button = seat('hermes-agent').querySelector('button')!;
		const focus = vi.spyOn(button, 'focus');
		seat('kimi-chat')
			.querySelector('button')!
			.dispatchEvent(
				Object.assign(new Event('keydown', { bubbles: true, cancelable: true }), { key: 'Home' })
			);
		expect(focus).toHaveBeenCalledOnce();
	});

	it('cancels active exchange flights when destroyed', async () => {
		await mount();
		app.$set({ selected: models[1] });
		await flush();
		expect(target.querySelectorAll('.is-flying')).toHaveLength(2);
		const cancel = flights.map((run) => vi.spyOn(run, 'cancel'));
		app.$destroy();
		app = null;
		await flush();
		cancel.forEach((spy) => expect(spy).toHaveBeenCalledOnce());
		expect(frames.size).toBe(0);
	});

	it('waits for measurement and releases the frame and preference listener on destroy', async () => {
		measured = false;
		await mount();
		const initial = position();
		await advance();
		await advance(5000);
		expect(position()).toBe(initial);
		expect(target.querySelector('.is-measured')).toBeFalsy();
		expect(mediaListeners.size).toBe(1);
		app.$destroy();
		app = null;
		expect(frames.size).toBe(0);
		expect(mediaListeners.size).toBe(0);
	});
});
