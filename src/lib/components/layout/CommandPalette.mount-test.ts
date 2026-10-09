// ⌘K palette: opens on the store, lists places and recent chats, searches chats on the server,
// keyboard picks and opens; a search hit opens at its message; 收藏 flips its store.
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

const nav = vi.hoisted(() => ({ goto: vi.fn(async () => {}) }));
vi.mock('$app/navigation', () => nav);
const chatsApi = vi.hoisted(() => ({ getChatListBySearchText: vi.fn() }));
vi.mock('$lib/apis/chats', () => chatsApi);

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const until = async (check: () => boolean, ms = 10000) => {
	const end = Date.now() + ms;
	while (!check()) {
		if (Date.now() > end) throw new Error(`timed out; text: ${document.body.textContent?.slice(0, 300)}`);
		await sleep(20);
	}
};

let stores: any;
let Palette: any;
let app: any;
let target: any;

beforeAll(async () => {
	stores = await import('$lib/stores');
	Palette = (await import('./CommandPalette.svelte')).default;
}, 120_000);

beforeEach(async () => {
	nav.goto.mockReset();
	chatsApi.getChatListBySearchText.mockReset();
	(globalThis as any).localStorage.token = 'tok';
	stores.config.set({ features: { enable_agent_teams: true } });
	stores.user.set({ id: 'u1', role: 'admin' });
	stores.chats.set([
		{ id: 'c1', title: '部署 HaloWebUI', kind: null },
		{ id: 'd1', title: '选数据库', kind: 'discuss' }
	]);
	stores.models.set([{ id: 'openai.gpt-chat', name: 'gpt-chat' }]);
	stores.showBookmarks.set(false);
	stores.pendingMessageReveal.set(null);
	const { writable } = await import('svelte/store');
	target = document.createElement('div');
	document.body.appendChild(target);
	app = new Palette({ target, context: new Map([['i18n', writable({ t: (s: string) => s })]]) });
	stores.showCommandPalette.set(true);
	await until(() => !!target.querySelector('[data-command-palette-input]'));
});

afterEach(() => {
	stores.showCommandPalette.set(false);
	app?.$destroy();
	target?.remove();
	app = null;
});

const input = () => target.querySelector('[data-command-palette-input]') as any;
const type = async (text: string) => {
	input().value = text;
	input().dispatchEvent(new (window as any).Event('input'));
	await sleep(10);
};
const key = async (k: string) => {
	// domino has no KeyboardEvent: a plain event carrying the key, as TeamLead's test does
	const event = new (window as any).Event('keydown', { bubbles: true }) as any;
	event.key = k;
	input().dispatchEvent(event);
	await sleep(20);
};
const ids = () =>
	Array.from(target.querySelectorAll('[data-command-palette-item]')).map((el: any) =>
		el.getAttribute('data-command-palette-item')
	);

describe('CommandPalette', () => {
	it('lists the places and recent chats, and Enter opens the one picked', async () => {
		expect(ids().slice(0, 3)).toEqual(['go:new', 'go:answer', 'go:discuss']);
		expect(ids()).toContain('go:schedules');
		expect(ids()).toContain('chat:d1');
		await key('ArrowUp'); // wraps to the last item: the oldest recent chat
		await key('Enter');
		expect(nav.goto).toHaveBeenCalledWith('/discuss/d1');
		expect(target.querySelectorAll('[data-command-palette]').length).toBe(0);
	});

	it('searches chats on the server and opens a hit at its message', async () => {
		chatsApi.getChatListBySearchText.mockResolvedValue([
			{ id: 'c7', title: '价格对比', snippet: '…gpt 的价格…', message_id: 'm9', kind: null, archived: true }
		]);
		await type('gpt');
		await until(() => ids().includes('chat:c7'));
		expect(chatsApi.getChatListBySearchText).toHaveBeenCalledWith('tok', 'gpt', 1);
		expect(ids()).toEqual(['chat:c7', 'model:openai.gpt-chat']);
		await key('Enter');
		expect(stores.pendingMessageReveal ? (await import('svelte/store')).get(stores.pendingMessageReveal) : null).toEqual({
			chatId: 'c7',
			messageId: 'm9'
		});
		expect(nav.goto).toHaveBeenCalledWith('/c/c7');
	});

	it('starts a chat on a model, and opens 收藏 without leaving the page', async () => {
		chatsApi.getChatListBySearchText.mockResolvedValue([]);
		await type('gpt-chat');
		await until(() => ids().includes('model:openai.gpt-chat') && chatsApi.getChatListBySearchText.mock.calls.length > 0);
		(target.querySelector('[data-command-palette-item="model:openai.gpt-chat"]') as any).click();
		await sleep(20);
		expect(nav.goto).toHaveBeenCalledWith('/?models=openai.gpt-chat');

		stores.showCommandPalette.set(true);
		await until(() => !!target.querySelector('[data-command-palette-input]'));
		await type('收藏');
		await key('Enter');
		const { get } = await import('svelte/store');
		expect(get(stores.showBookmarks)).toBe(true);
	});

	it('closes on Escape', async () => {
		await key('Escape');
		expect(target.querySelectorAll('[data-command-palette]').length).toBe(0);
	});
});
