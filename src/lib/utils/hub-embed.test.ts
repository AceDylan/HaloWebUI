import { describe, expect, it, vi } from 'vitest';

import {
	HUB_REAUTH_GUARD_MS,
	hubNoteUrl,
	hubReturnPath,
	openNoteInHub,
	parseHubTicket,
	postActivityToHub,
	rememberHubOrigin,
	requestHubReauth,
	splitVaultNotePaths,
	stripHubTicket,
	takeHubTicket,
	vaultNotePath
} from './hub-embed';

const TICKET = [
	'v2',
	'chat',
	'1790000000',
	'Zm9vYmFyYmF6cXV4MTIzNDU2',
	'aHR0cHM6Ly9iZXN0LmFjZWR5bGFuLnVzOjU1MjY',
	'aHR0cHM6Ly9ob3N0LmFjZWR5bGFuLnVzOjMwMDE',
	'a'.repeat(64)
].join('.');

describe('parseHubTicket', () => {
	it('reads the ticket from the fragment, with or without the leading #', () => {
		expect(parseHubTicket(`#hub_ticket=${TICKET}`)).toBe(TICKET);
		expect(parseHubTicket(`hub_ticket=${TICKET}&other=1`)).toBe(TICKET);
	});

	it('ignores fragments that carry no ticket', () => {
		expect(parseHubTicket('')).toBeNull();
		expect(parseHubTicket('#token=abc')).toBeNull();
	});

	it('refuses anything that is not shaped like a v2 ticket', () => {
		for (const bad of [
			'v1.enter.1790000000.nonce.sig',
			TICKET.replace('v2.', 'v3.'),
			`${TICKET}.extra`,
			TICKET.split('.').slice(0, 6).join('.'),
			`${TICKET}<script>`,
			`v2.${'a'.repeat(2000)}.b.c.d.e.f`
		]) {
			expect(parseHubTicket(`#hub_ticket=${encodeURIComponent(bad)}`)).toBeNull();
		}
	});
});

describe('stripHubTicket', () => {
	it('drops only the ticket and keeps path, query and other fragment parameters', () => {
		const url = new URL(`https://host.example:3001/auth?redirect=%2Fc%2F1#hub_ticket=${TICKET}`);
		expect(stripHubTicket(url)).toBe('/auth?redirect=%2Fc%2F1');

		const mixed = new URL(`https://host.example:3001/auth#a=1&hub_ticket=${TICKET}&b=2`);
		expect(stripHubTicket(mixed)).toBe('/auth#a=1&b=2');
	});
});

describe('takeHubTicket', () => {
	const history = () => ({ state: { 'sveltekit:history': 3 }, replaceState: vi.fn() });

	it('returns the ticket and scrubs it from the address, keeping the history state', () => {
		const h = history();
		const ticket = takeHubTicket({ href: `https://host.example:3001/auth#hub_ticket=${TICKET}` }, h);
		expect(ticket).toBe(TICKET);
		expect(h.replaceState).toHaveBeenCalledTimes(1);
		expect(h.replaceState).toHaveBeenCalledWith(h.state, '', '/auth');
	});

	it('scrubs a malformed ticket too, but does not hand it on', () => {
		const h = history();
		expect(takeHubTicket({ href: 'https://host.example:3001/auth#hub_ticket=garbage' }, h)).toBeNull();
		expect(h.replaceState).toHaveBeenCalledTimes(1);
		expect(h.replaceState).toHaveBeenCalledWith(h.state, '', '/auth');
	});

	it('leaves an ordinary address alone (OAuth puts #token= here)', () => {
		const h = history();
		expect(takeHubTicket({ href: 'https://host.example:3001/auth#token=abc' }, h)).toBeNull();
		expect(h.replaceState).not.toHaveBeenCalled();
	});
});

describe('postActivityToHub', () => {
	const framed = () => {
		const parent = { postMessage: vi.fn() };
		return { win: { parent }, parent };
	};

	it('posts the state to the configured Hub origin when framed', () => {
		const { win, parent } = framed();
		expect(postActivityToHub('done', 'https://best.acedylan.us:5526', win)).toBe(true);
		expect(parent.postMessage).toHaveBeenCalledWith(
			{ source: 'halowebui', type: 'activity', state: 'done' },
			'https://best.acedylan.us:5526'
		);
	});

	it('stays quiet when not framed or no Hub is configured', () => {
		const top: any = { postMessage: vi.fn() };
		top.parent = top;
		expect(postActivityToHub('done', 'https://best.acedylan.us:5526', top)).toBe(false);
		expect(top.postMessage).not.toHaveBeenCalled();

		const { win, parent } = framed();
		expect(postActivityToHub('running', undefined, win)).toBe(false);
		expect(postActivityToHub('running', '', win)).toBe(false);
		expect(postActivityToHub('running', '*', win)).toBe(false);
		expect(postActivityToHub('running', 'https://hub.example/path', win)).toBe(false);
		expect(parent.postMessage).not.toHaveBeenCalled();
	});
});

const ROOT = '/root/Documents/Obsidian Vault';
const HUB = 'https://best.acedylan.us:5526';

describe('vaultNotePath', () => {
	it('gives the vault-relative path of a note under the root', () => {
		expect(vaultNotePath(`${ROOT}/项目/HaloWebUI.md`, ROOT)).toBe('项目/HaloWebUI.md');
		expect(vaultNotePath(` ${ROOT}/a b（2026-09-27）.md `, `${ROOT}/`)).toBe(
			'a b（2026-09-27）.md'
		);
		expect(vaultNotePath(`file://${ROOT}/x.md`, ROOT)).toBe('x.md');
	});

	it('reads a percent-encoded link target', () => {
		expect(vaultNotePath(encodeURI(`${ROOT}/项目/HaloWebUI.md`), ROOT)).toBe('项目/HaloWebUI.md');
		expect(vaultNotePath('/root/Documents/Obsidian%20Vault/%E9%A1%B9.md', ROOT)).toBe('项.md');
		expect(vaultNotePath('/root/Documents/Obsidian%ZZVault/x.md', ROOT)).toBeNull();
	});

	it('refuses anything that is not a note inside the vault', () => {
		for (const bad of [
			`${ROOT}`,
			`${ROOT}/`,
			`${ROOT}/项目`,
			`${ROOT}/a.png`,
			`${ROOT}/../etc/x.md`,
			`${ROOT}/.obsidian/x.md`,
			`${ROOT}//x.md`,
			`${ROOT}/a\\b.md`,
			`${ROOT}Other/x.md`,
			'/etc/x.md',
			'项目/HaloWebUI.md',
			`${ROOT}/${'x'.repeat(600)}.md`
		]) {
			expect(vaultNotePath(bad, ROOT), bad).toBeNull();
		}
		expect(vaultNotePath(`${ROOT}/x.md`, '')).toBeNull();
		expect(vaultNotePath(`${ROOT}/x.md`, 'relative')).toBeNull();
		expect(vaultNotePath(`${ROOT}/x.md`, undefined)).toBeNull();
	});
});

describe('splitVaultNotePaths', () => {
	it('leaves text without the root alone', () => {
		expect(splitVaultNotePaths('nothing here', ROOT)).toEqual([
			{ text: 'nothing here', path: null }
		]);
		expect(splitVaultNotePaths(`${ROOT}/x.md`, '')).toEqual([{ text: `${ROOT}/x.md`, path: null }]);
	});

	it('cuts out paths with spaces and CJK, ending at the first .md', () => {
		const text = `记录已更新：${ROOT}/系统/Hermes/YCE 更新 v2.3.3（2026-08-11）.md，另见 ${ROOT}/项目/HaloWebUI.md。`;
		expect(splitVaultNotePaths(text, ROOT)).toEqual([
			{ text: '记录已更新：', path: null },
			{
				text: `${ROOT}/系统/Hermes/YCE 更新 v2.3.3（2026-08-11）.md`,
				path: '系统/Hermes/YCE 更新 v2.3.3（2026-08-11）.md'
			},
			{ text: '，另见 ', path: null },
			{ text: `${ROOT}/项目/HaloWebUI.md`, path: '项目/HaloWebUI.md' },
			{ text: '。', path: null }
		]);
	});

	it('keeps the vault folder itself and non-note files as plain text', () => {
		expect(splitVaultNotePaths(`Vault 是 ${ROOT}，每 15 分钟提交。`, ROOT)).toEqual([
			{ text: `Vault 是 ${ROOT}，每 15 分钟提交。`, path: null }
		]);
		expect(splitVaultNotePaths(`${ROOT}/附件/a.png 和 ${ROOT}/.git/x.md`, ROOT)).toEqual([
			{ text: `${ROOT}/附件/a.png 和 ${ROOT}/.git/x.md`, path: null }
		]);
	});

	it('does not stop inside a longer name', () => {
		expect(splitVaultNotePaths(`${ROOT}/a.mdx.md!`, ROOT)).toEqual([
			{ text: `${ROOT}/a.mdx.md`, path: 'a.mdx.md' },
			{ text: '!', path: null }
		]);
	});
});

describe('hubNoteUrl / openNoteInHub', () => {
	it('builds the Hub address for a note', () => {
		expect(hubNoteUrl('项目/a b.md', HUB)).toBe(`${HUB}/?note=%E9%A1%B9%E7%9B%AE%2Fa%20b.md#vault`);
		expect(hubNoteUrl('x.md', 'https://hub.example/path')).toBeNull();
		expect(hubNoteUrl('x.md', undefined)).toBeNull();
	});

	it('asks only the Hub, and only when framed', () => {
		const parent = { postMessage: vi.fn() };
		expect(openNoteInHub('项目/x.md', HUB, { parent })).toBe(true);
		expect(parent.postMessage).toHaveBeenCalledWith(
			{ source: 'halowebui', type: 'open-note', path: '项目/x.md' },
			HUB
		);

		const top: any = { postMessage: vi.fn() };
		top.parent = top;
		expect(openNoteInHub('项目/x.md', HUB, top)).toBe(false);
		expect(top.postMessage).not.toHaveBeenCalled();
		expect(openNoteInHub('项目/x.md', '*', { parent })).toBe(false);
		expect(parent.postMessage).toHaveBeenCalledTimes(1);
	});
});

describe('requestHubReauth', () => {
	const memory = () => {
		const data = new Map<string, string>();
		return {
			getItem: (k: string) => (data.has(k) ? data.get(k)! : null),
			setItem: (k: string, v: string) => void data.set(k, String(v))
		};
	};

	it('lands on the same chat, never on a query', () => {
		expect(hubReturnPath('/c/0b5e-42')).toBe('/c/0b5e-42');
		expect(hubReturnPath('/')).toBe('/');
		expect(hubReturnPath('/?q=hi')).toBe('/');
		expect(hubReturnPath('/c/../admin')).toBe('/');
		expect(hubReturnPath('/workspace')).toBe('/');
		expect(hubReturnPath(undefined)).toBe('/');
	});

	it('asks only the Hub, once a minute, and only when framed', () => {
		const store = memory();
		const parent = { postMessage: vi.fn() };
		expect(requestHubReauth(HUB, '/c/abc', { parent }, store, 1_000_000)).toBe(true);
		expect(parent.postMessage).toHaveBeenCalledWith(
			{ source: 'halowebui', type: 'reauth', path: '/c/abc' },
			HUB
		);
		expect(requestHubReauth(HUB, '/c/abc', { parent }, store, 1_000_000 + 5_000)).toBe(false);
		expect(
			requestHubReauth(HUB, '/', { parent }, store, 1_000_000 + HUB_REAUTH_GUARD_MS)
		).toBe(true);
		expect(parent.postMessage).toHaveBeenCalledTimes(2);

		const top: any = { postMessage: vi.fn() };
		top.parent = top;
		expect(requestHubReauth(HUB, '/', top, memory(), 1)).toBe(false);
		expect(requestHubReauth('*', '/', { parent }, memory(), 1)).toBe(false);
		expect(requestHubReauth(HUB, '/', { parent }, null, 1)).toBe(false);
		expect(parent.postMessage).toHaveBeenCalledTimes(2);
	});

	it('uses the origin remembered while signed in once the config no longer names it', () => {
		const store = memory();
		const parent = { postMessage: vi.fn() };
		expect(requestHubReauth(undefined, '/', { parent }, store, 1)).toBe(false);
		rememberHubOrigin('https://evil.example/path', store);
		expect(requestHubReauth(undefined, '/', { parent }, store, 1)).toBe(false);
		rememberHubOrigin(HUB, store);
		expect(requestHubReauth(undefined, '/c/x', { parent }, store, 1)).toBe(true);
		expect(parent.postMessage).toHaveBeenCalledWith(
			{ source: 'halowebui', type: 'reauth', path: '/c/x' },
			HUB
		);
	});
});
