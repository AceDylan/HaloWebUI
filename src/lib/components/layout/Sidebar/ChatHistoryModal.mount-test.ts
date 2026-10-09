// 全部对话: every chat carries its mark (讨论 / 精答 / 协作 / 生图), and a discussion opens in
// 讨论台 rather than as a bare chat.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

const nav = vi.hoisted(() => ({ goto: vi.fn(async () => {}) }));
vi.mock('$app/navigation', () => nav);
vi.mock('$lib/apis/chats', () => ({
	getChatList: vi.fn(async () => [
		{ id: 'd1', title: '选数据库', updated_at: 1_760_000_000, created_at: 1, kind: 'discuss' },
		{ id: 'c1', title: '普通问题', updated_at: 1_760_000_000, created_at: 1, kind: null }
	]),
	getChatListBySearchText: vi.fn(async () => [])
}));

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const waitFor = async <T>(probe: () => T | null | undefined | false, timeout = 15000) => {
	const started = Date.now();
	for (;;) {
		const value = probe();
		if (value) return value as T;
		if (Date.now() - started > timeout) throw new Error('timed out');
		await sleep(20);
	}
};

let app: any;
let target: any;

afterEach(() => {
	app?.$destroy();
	target?.remove();
	app = null;
});

describe('ChatHistoryModal', () => {
	it('marks a discussion and opens it in 讨论台', async () => {
		const { writable } = await import('svelte/store');
		const i18n = writable({ t: (s: string) => s, language: 'zh-CN', resolvedLanguage: 'zh-CN' });
		const { default: Modal } = await import('./ChatHistoryModal.svelte');
		target = document.createElement('div');
		document.body.appendChild(target);
		app = new Modal({
			target,
			props: { show: true },
			context: new Map<string, any>([['i18n', i18n]])
		});
		const links = await waitFor(() => {
			const found = Array.from(document.body.querySelectorAll('a[href]')) as any[];
			return found.length >= 2 ? found : null;
		});
		const discuss = links.find((a) => a.textContent.includes('选数据库'));
		const plain = links.find((a) => a.textContent.includes('普通问题'));
		expect(discuss.getAttribute('href')).toBe('/discuss/d1');
		expect(plain.getAttribute('href')).toBe('/c/c1');
		expect(discuss.querySelector('[data-halo-chat-kind]').textContent.trim()).toBe('讨论');
		expect(plain.querySelectorAll('[data-halo-chat-kind]').length).toBe(0);
		discuss.click();
		await sleep(20);
		expect(nav.goto).toHaveBeenCalledWith('/discuss/d1');
	}, 90_000);
});
