// 讨论台 sidebar hint: counts the discussions under way, starting from the list and then
// following the live socket events; the expanded and the collapsed entry share the count.
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

const api = vi.hoisted(() => ({ listDiscussions: vi.fn() }));
vi.mock('$lib/apis/discussions', () => api);

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const until = async (check: () => boolean, ms = 10000) => {
	const end = Date.now() + ms;
	while (!check()) {
		if (Date.now() > end) throw new Error('timed out waiting for the view');
		await sleep(25);
	}
};

let Badge: any;
let stores: any;
let handlers: Record<string, ((e: any) => void)[]> = {};
const apps: any[] = [];

const emit = (chatId: string, data: any) =>
	(handlers['chat-events'] ?? []).forEach((fn) => fn({ chat_id: chatId, data: { type: 'discuss', data } }));

beforeAll(async () => {
	stores = await import('$lib/stores');
	Badge = (await import('./DiscussBadge.svelte')).default;
}, 60000);

afterEach(() => {
	apps.splice(0).forEach((app) => app.$destroy());
	document.body.innerHTML = '';
});

const mount = (props: Record<string, unknown>) => {
	const target = document.createElement('div');
	document.body.appendChild(target);
	apps.push(new Badge({ target, props }));
	return target;
};

describe('DiscussBadge', () => {
	it('starts from the running discussions and follows start / end events', async () => {
		handlers = {};
		stores.socket.set({
			on: (name: string, fn: any) => (handlers[name] = [...(handlers[name] ?? []), fn]),
			off: (name: string, fn: any) => (handlers[name] = (handlers[name] ?? []).filter((f) => f !== fn))
		});
		localStorage.token = 't';
		api.listDiscussions.mockResolvedValue({
			items: [
				{ id: 'c1', running: true, status: 'running' },
				{ id: 'c2', running: false, status: 'done' }
			],
			next: null,
			total: null,
			live: 0
		});

		const wide = mount({});
		const narrow = mount({ compact: true });
		await until(() => !!wide.querySelector('[data-discuss-badge]'));
		expect(wide.querySelector('[data-discuss-badge]')!.textContent!.trim()).toBe('1');
		expect(narrow.querySelector('[data-discuss-badge]')).toBeTruthy();
		expect(api.listDiscussions).toHaveBeenCalledTimes(1);
		// the discussions under way only, never the whole history
		expect(api.listDiscussions.mock.calls[0][1]).toEqual({ status: 'live' });

		// another discussion starts; a delta (no status) changes nothing; other chat events are ignored
		emit('c3', { kind: 'state', ask: { status: 'running' } });
		emit('c3', { kind: 'delta', parts: [] });
		(handlers['chat-events'] ?? []).forEach((fn) => fn({ chat_id: 'c9', data: { type: 'status' } }));
		await sleep(30);
		expect(wide.querySelector('[data-discuss-badge]')!.textContent!.trim()).toBe('2');

		// concluding still counts; then both end
		emit('c1', { kind: 'state', ask: { status: 'concluding' } });
		emit('c1', { kind: 'end', status: 'done' });
		await sleep(30);
		expect(wide.querySelector('[data-discuss-badge]')!.textContent!.trim()).toBe('1');
		emit('c3', { kind: 'state', ask: { status: 'stopped' } });
		await sleep(30);
		expect(wide.querySelector('[data-discuss-badge]')).toBeFalsy();
		expect(narrow.querySelector('[data-discuss-badge]')).toBeFalsy();
	});
});
