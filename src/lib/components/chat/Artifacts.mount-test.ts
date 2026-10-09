// 内容预览 panel (chat menu → Artifacts): HTML previews follow the app's light / dark
// theme like the inline answer cards, and a theme switch keeps the version on screen.
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { writable } from 'svelte/store';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

const theme = vi.hoisted(() => ({ store: null as any }));
vi.mock('$lib/utils/dark-mode', async () => {
	const { writable } = await import('svelte/store');
	theme.store = writable(false);
	return { isDarkMode: { subscribe: theme.store.subscribe } };
});

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const DARK_STYLES = '<style data-halo-artifact-dark-styles';

let Artifacts: any;
let stores: any;
const apps: any[] = [];

beforeAll(async () => {
	stores = await import('$lib/stores');
	Artifacts = (await import('./Artifacts.svelte')).default;
}, 60000);

afterEach(() => {
	apps.splice(0).forEach((app) => app.$destroy());
	document.body.innerHTML = '';
	theme.store.set(false);
});

const htmlAnswer = (title: string) => `\`\`\`html\n<h1>${title}</h1>\n\`\`\``;
const history = {
	currentId: 'a2',
	messages: {
		u1: { id: 'u1', role: 'user', content: 'q', parentId: null, childrenIds: ['a1'] },
		a1: {
			id: 'a1',
			role: 'assistant',
			content: htmlAnswer('one'),
			parentId: 'u1',
			childrenIds: ['u2'],
			done: true
		},
		u2: { id: 'u2', role: 'user', content: 'q2', parentId: 'a1', childrenIds: ['a2'] },
		a2: {
			id: 'a2',
			role: 'assistant',
			content: htmlAnswer('two'),
			parentId: 'u2',
			childrenIds: [],
			done: true
		}
	}
};

const mount = () => {
	const target = document.createElement('div');
	document.body.appendChild(target);
	const app = new Artifacts({
		target,
		props: { history },
		context: new Map([
			['i18n', writable({ t: (s: string, v?: any) => (v ? `${s} ${JSON.stringify(v)}` : s) })]
		])
	});
	apps.push(app);
	return target;
};

const frameDoc = (target: HTMLElement) =>
	target.querySelector('iframe')?.getAttribute('srcdoc') ?? '';

describe('Artifacts panel theme', () => {
	it('renders HTML previews in the current theme and follows live switches', async () => {
		stores.artifactPreviewTarget.set(null);
		const target = mount();
		await sleep(20);
		expect(frameDoc(target)).toContain('two');
		expect(frameDoc(target)).not.toContain(DARK_STYLES);

		theme.store.set(true);
		await sleep(20);
		expect(frameDoc(target)).toContain(DARK_STYLES);
		expect(frameDoc(target)).toContain('data-halo-html-preview-theme');

		theme.store.set(false);
		await sleep(20);
		expect(frameDoc(target)).not.toContain(DARK_STYLES);
	});

	it('keeps the selected version when the theme changes', async () => {
		stores.artifactPreviewTarget.set(null);
		const target = mount();
		await sleep(20);
		const prev = Array.from(target.querySelectorAll('button')).find((b) =>
			b.querySelector('path[d^="M15.75"]')
		) as HTMLButtonElement;
		prev.click();
		await sleep(20);
		expect(frameDoc(target)).toContain('one');

		theme.store.set(true);
		await sleep(20);
		expect(frameDoc(target)).toContain('one');
		expect(frameDoc(target)).toContain(DARK_STYLES);
	});
});
