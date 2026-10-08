// Mounts the inline Markdown renderer with a Hub vault configured: absolute note
// paths in a reply (plain text, code span, link target) open the note in the Hub.
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { writable } from 'svelte/store';
import { marked } from 'marked';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');
// unescapeHtml (code spans) parses with DOMParser, which domino lacks.
(globalThis as any).DOMParser ??= class {
	parseFromString(html: string) {
		const root = document.createElement('div');
		root.innerHTML = html;
		return { documentElement: root };
	}
};

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const ROOT = '/root/Documents/Obsidian Vault';
const HUB = 'https://best.acedylan.us:5526';

let MarkdownInlineTokens: any;
let config: any;
let app: any;
let target: any;

beforeAll(async () => {
	MarkdownInlineTokens = (await import('./MarkdownInlineTokens.svelte')).default;
	config = (await import('$lib/stores')).config;
});

afterEach(() => {
	app?.$destroy();
	app = null;
	document.body.innerHTML = '';
});

const i18n = writable({
	t: (key: string) => ({ 'Open in notes': '在笔记中打开', 'Open note': '打开笔记' })[key] ?? key
});

const mount = async (markdown: string) => {
	const tokens = (marked.lexer(markdown)[0] as any).tokens;
	target = document.createElement('div');
	document.body.appendChild(target);
	app = new MarkdownInlineTokens({
		target,
		props: { id: 't', tokens },
		context: new Map([['i18n', i18n]])
	});
	await sleep(0);
	return Array.from(target.querySelectorAll('a')) as any[];
};

describe('note paths in a reply', () => {
	it('turns a plain-text path into a link to the Hub', async () => {
		config.set({ hub_origin: HUB, hub_vault_root: ROOT });
		const links = await mount(`记录已更新：${ROOT}/系统/Hermes/YCE 更新（2026-08-11）.md。`);
		expect(links).toHaveLength(1);
		expect(links[0].textContent).toBe(`${ROOT}/系统/Hermes/YCE 更新（2026-08-11）.md`);
		expect(links[0].getAttribute('href')).toBe(
			`${HUB}/?note=${encodeURIComponent('系统/Hermes/YCE 更新（2026-08-11）.md')}#vault`
		);
		expect(target.textContent).toBe(`记录已更新：${ROOT}/系统/Hermes/YCE 更新（2026-08-11）.md。`);
	});

	it('keeps a code span copyable and adds a small open button after it', async () => {
		config.set({ hub_origin: HUB, hub_vault_root: ROOT });
		const links = await mount(`见 \`${ROOT}/项目/HaloWebUI.md\``);
		expect(target.querySelector('code').textContent).toBe(`${ROOT}/项目/HaloWebUI.md`);
		expect(links).toHaveLength(1);
		expect(links[0].textContent).toBe('打开笔记');
		expect(links[0].getAttribute('href')).toBe(
			`${HUB}/?note=${encodeURIComponent('项目/HaloWebUI.md')}#vault`
		);
	});

	it('repairs a link whose target is the note on disk, without nesting links', async () => {
		config.set({ hub_origin: HUB, hub_vault_root: ROOT });
		const links = await mount(`[${ROOT}/项目/HaloWebUI.md](<${ROOT}/项目/HaloWebUI.md>)`);
		expect(links).toHaveLength(1);
		expect(links[0].getAttribute('href')).toBe(
			`${HUB}/?note=${encodeURIComponent('项目/HaloWebUI.md')}#vault`
		);
	});

	it('when framed, a plain click asks the Hub instead of opening a tab', async () => {
		config.set({ hub_origin: HUB, hub_vault_root: ROOT });
		const post = vi.fn();
		const realParent = Object.getOwnPropertyDescriptor(window, 'parent');
		Object.defineProperty(window, 'parent', { configurable: true, value: { postMessage: post } });
		try {
			const [link] = await mount(`${ROOT}/项目/a.md`);
			const event = document.createEvent('MouseEvent');
			event.initEvent('click', true, true);
			link.dispatchEvent(event);
			expect(post).toHaveBeenCalledWith(
				{ source: 'halowebui', type: 'open-note', path: '项目/a.md' },
				HUB
			);
			expect(event.defaultPrevented).toBe(true);
		} finally {
			if (realParent) Object.defineProperty(window, 'parent', realParent);
		}
	});

	it('leaves everything as it was without a vault root or a Hub', async () => {
		config.set({ hub_origin: HUB });
		expect(await mount(`${ROOT}/项目/a.md 和 \`${ROOT}/项目/b.md\``)).toHaveLength(0);
		app.$destroy();
		config.set({ hub_vault_root: ROOT });
		expect(await mount(`${ROOT}/项目/a.md`)).toHaveLength(0);
	});
});

describe('links to this app in a reply', () => {
	it('open in place; websites and files still open in a new tab', async () => {
		config.set({});
		const links = await mount(
			'在协作台看：[结果页](/teams/t1/conclusion) · [产出文件](/teams/t1/conclusion#files) · [网站](https://example.com/x) · [文件](/api/v1/teams/t1/files/a.md)'
		);
		const seen = links.map((a) => [
			a.textContent.trim(),
			a.getAttribute('target'),
			a.getAttribute('rel')
		]);
		expect(seen).toEqual([
			['结果页', null, null],
			['产出文件', null, null],
			['网站', '_blank', 'noopener noreferrer nofollow'],
			['文件', '_blank', 'noopener noreferrer nofollow']
		]);
		expect(links[1].getAttribute('href')).toBe('/teams/t1/conclusion#files');
	});
});
