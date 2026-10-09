import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');
vi.mock('dompurify', () => ({ default: { sanitize: (html: unknown) => String(html ?? '') } }));
vi.mock('svelte-sonner', () => ({
	toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() }
}));
const sleep = (ms = 30) => new Promise((r) => setTimeout(r, ms));
let app: any;
let target: any;
let Component: any;
beforeAll(async () => {
	Component = (await import('./BranchCompare.svelte')).default;
}, 120000);
afterEach(() => {
	app?.$destroy();
	app = null;
	document.body.innerHTML = '';
});

describe('branch comparison dialog', () => {
	it('renders two real answers with their prompts and closes without selecting a branch', async () => {
		const { writable } = await import('svelte/store');
		const { get } = await import('svelte/store');
		const { showArtifacts, settings, chatId } = await import('$lib/stores');
		showArtifacts.set(false);
		settings.set({ detectArtifacts: true, responseHtmlFormat: true } as any);
		chatId.set('chat-1');
		const history = {
			currentId: 'a2',
			messages: {
				u1: { id: 'u1', role: 'user', parentId: null, childrenIds: ['a1'], content: '原问题' },
				a1: {
					id: 'a1',
					role: 'assistant',
					parentId: 'u1',
					content: '**原回答**\n\n```svg\n<svg></svg>\n```',
					done: true
				},
				u2: {
					id: 'u2',
					role: 'user',
					parentId: null,
					childrenIds: ['a2'],
					content: '编辑后的问题'
				},
				a2: { id: 'a2', role: 'assistant', parentId: 'u2', content: '**新回答**', done: true }
			}
		};
		const before = JSON.stringify(history);
		target = document.createElement('div');
		document.body.appendChild(target);
		app = new Component({
			target,
			props: { history, messageId: 'a2' },
			context: new Map([['i18n', writable({ t: (key: string) => key })]])
		});
		target.querySelector('[data-halo-branch-compare]').click();
		await sleep(100);
		const left = document.querySelector('[data-halo-compare-side="left"]')!;
		const right = document.querySelector('[data-halo-compare-side="right"]')!;
		expect(left.textContent).toContain('编辑后的问题');
		expect(left.querySelector('strong')?.textContent?.trim()).toBe('新回答');
		expect(right.textContent).toContain('原问题');
		expect(right.querySelector('strong')?.textContent?.trim()).toBe('原回答');
		expect(get(showArtifacts)).toBe(false);
		const close = Array.from(document.querySelectorAll('button')).find(
			(b) => b.textContent === '关闭'
		)!;
		close.click();
		await sleep();
		expect(document.querySelector('[data-halo-branch-comparison]')).toBeFalsy();
		expect(JSON.stringify(history)).toBe(before);
	});
});
