// Mounts the real sources button and source view with the stored shape of a web
// search answer. Guards the three ways a citation used to show nothing: the
// source list clipped inside the message (it must live in <body>), [n]
// opening a different source than the one numbered n, and a page without text
// opening as a blank view.
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

vi.mock('dompurify', () => ({ default: { sanitize: (html: unknown) => String(html ?? '') } }));
vi.mock('svelte-sonner', () => ({
	toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() }
}));

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const waitFor = async <T>(probe: () => T | null | undefined | false, label: string) => {
	const started = Date.now();
	for (;;) {
		const value = probe();
		if (value) return value as T;
		if (Date.now() - started > 8000) {
			throw new Error(
				`timed out waiting for ${label}; page text: ${String(document.body.textContent ?? '')
					.replace(/\s+/g, ' ')
					.slice(0, 400)}`
			);
		}
		await sleep(15);
	}
};

const webSource = (query: string, url: string, title: string, text: string) => ({
	source: { name: query, type: 'web_search', urls: [url] },
	document: [text],
	metadata: [{ source: url, title }]
});

const sources = [
	webSource('q1', 'https://a.example/one', 'Page one', 'Text of page one'),
	webSource('q1', 'https://b.example/two', 'Page two', 'Text of page two'),
	webSource('q2', 'https://a.example/one', 'Page one', 'More of page one'),
	webSource('q2', 'https://c.example/three', 'Blocked page', '')
];

let app: any;
let target: any;
let Citations: any;

// Compiling the component tree (Markdown and its renderers) takes most of the
// per-test timeout, so it happens once, under the longer hook timeout.
beforeAll(async () => {
	Citations = (await import('./Citations.svelte')).default;
});

const mount = async () => {
	const { writable } = await import('svelte/store');
	const i18n = writable({ t: (key: string) => key });
	target = document.createElement('div');
	document.body.appendChild(target);
	app = new Citations({
		target,
		props: { id: 'message-1', sources },
		context: new Map<string, any>([['i18n', i18n]])
	});
};

afterEach(() => {
	app?.$destroy();
	document.body.innerHTML = '';
});

describe('Citations', () => {
	it('lists one entry per page, outside the message, in [n] order', async () => {
		await mount();
		(target.querySelector('button[aria-expanded]') as any).click();

		const entries = await waitFor(
			() =>
				document.body.querySelectorAll('[id^="source-message-1-"]').length === 3 &&
				Array.from(document.body.querySelectorAll('[id^="source-message-1-"]')),
			'source list'
		);
		const list = entries[0].parentElement as any;
		expect(list.parentElement).toBe(document.body);
		expect(target.contains(list)).toBe(false);
		expect(entries.map((entry: any) => entry.textContent.trim())).toEqual([
			'a.example',
			'b.example',
			'c.example'
		]);
	});

	it('opens the source numbered n, and says so when a page has no text', async () => {
		await mount();

		expect(app.openCitationByIndex(2)).toBe(true);
		await waitFor(() => document.body.textContent?.includes('Text of page two'), 'source 2');
		expect(document.body.textContent).toContain('Page two');
		expect(document.body.textContent).toContain('https://b.example/two');
		expect(document.body.textContent).not.toContain('Text of page one');

		expect(app.openCitationByIndex(3)).toBe(true);
		await waitFor(
			() => document.body.textContent?.includes('No page text was captured for this source.'),
			'empty-page note'
		);
		const link = Array.from(document.body.querySelectorAll('a')).find(
			(a: any) => a.textContent.trim() === 'Open link'
		) as any;
		expect(link?.getAttribute('href')).toBe('https://c.example/three');

		expect(app.openCitationByIndex(4)).toBe(false);
	});
});
