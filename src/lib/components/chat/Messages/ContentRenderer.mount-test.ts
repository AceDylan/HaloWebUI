// Mounts the real answer renderer with the HTML answer format on. Guards the
// freeze where opening a finished answer with a code block pinned the tab: the
// formatter's output changed on every call, and bind:headings from Markdown
// re-ran ContentRenderer's whole reactive chain, so Svelte kept re-rendering in
// one flush. The formatter below is deliberately made to differ per call; the
// renderer must still settle, and throws instead of hanging if it does not.
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

vi.mock('dompurify', () => ({ default: { sanitize: (html: unknown) => String(html ?? '') } }));
vi.mock('svelte-sonner', () => ({
	toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() }
}));

const MAX_FORMAT_CALLS = 40;
const formatCalls = vi.hoisted(() => ({ count: 0 }));

vi.mock('$lib/utils/response-html-format', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/utils/response-html-format')>();
	return {
		...actual,
		renderResponseHtmlFormat: (content: string) => {
			formatCalls.count += 1;
			if (formatCalls.count > MAX_FORMAT_CALLS) {
				throw new Error('answer renderer never settled');
			}
			return `${actual.renderResponseHtmlFormat(content)}<!-- ${formatCalls.count} -->`;
		}
	};
});

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

let ContentRenderer: any;
let app: any;
let target: any;

beforeAll(async () => {
	ContentRenderer = (await import('./ContentRenderer.svelte')).default;
});

afterEach(() => {
	app?.$destroy();
	app = null;
	document.body.innerHTML = '';
});

describe('ContentRenderer', () => {
	it('settles on a finished answer with a code block in the HTML answer format', async () => {
		const { writable } = await import('svelte/store');
		const { settings } = await import('$lib/stores');
		settings.set({ responseHtmlFormat: true } as any);
		formatCalls.count = 0;

		target = document.createElement('div');
		document.body.appendChild(target);
		app = new ContentRenderer({
			target,
			props: {
				id: 'message-1',
				content: '结论：先清磁盘。\n\n```bash\ndf -h\ndocker system df\n```\n\n然后重启 [1]。',
				sources: [
					{
						source: { name: 'notes.txt', id: 'file-1' },
						document: ['notes'],
						metadata: [{ name: 'notes.txt' }]
					}
				],
				streaming: false,
				isLastMessage: true
			},
			context: new Map<string, any>([['i18n', writable({ t: (key: string) => key })]])
		});
		await sleep(50);

		expect(formatCalls.count).toBeGreaterThan(0);
		expect(formatCalls.count).toBeLessThan(MAX_FORMAT_CALLS);
		expect(target.querySelector('[data-halo-response-html-format="inline"]')).not.toBeNull();
		expect(target.querySelector('pre[data-halo-code="true"]')?.textContent).toContain('df -h');
	});
});
