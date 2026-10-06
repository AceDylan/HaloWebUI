// 版本记录: versions newest first with what made each, a line diff against the current one,
// a link to the run, and 「恢复到这一版」 only when the assistant may be edited.
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/workspace/models');

const library = vi.hoisted(() => ({
	getAssistantVersions: vi.fn(),
	restoreAssistantVersion: vi.fn()
}));
vi.mock('$lib/apis/assistant-library', async (original) => ({
	...((await original()) as object),
	...library
}));
const toasts = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock('svelte-sonner', () => ({ toast: toasts }));

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const until = async (check: () => boolean, ms = 10000) => {
	const end = Date.now() + ms;
	while (!check()) {
		if (Date.now() > end) throw new Error('timed out waiting for the view');
		await sleep(20);
	}
};

const versions = (editable: boolean) => ({
	id: 'coder',
	name: 'Coder',
	editable,
	source: 'answer',
	domain: '',
	createdFor: { runRef: 'answer:c0', at: 1 },
	current: { version: 2, name: 'Coder', system: 'role\nnew rule', description: '', at: 3 },
	revisions: [{ version: 1, at: 2, source: 'discuss', runRef: 'discuss:c9:a1', change: '加了规则', system: 'role\nold rule' }]
});

let Modal: any;
let app: any;

beforeAll(async () => {
	Modal = (await import('./AssistantVersionsModal.svelte')).default;
}, 60000);

beforeEach(() => {
	Object.values(library).forEach((fn: any) => fn.mockReset());
	localStorage.token = 't';
});

afterEach(() => {
	app?.$destroy();
	app = null;
	document.body.innerHTML = '';
});

const mount = async (onRestored = vi.fn()) => {
	const { writable } = await import('svelte/store');
	const target = document.createElement('div');
	document.body.appendChild(target);
	app = new Modal({
		target,
		props: { show: true, modelId: 'coder', onRestored },
		context: new Map([
			[
				'i18n',
				writable({
					t: (s: string, o: Record<string, any> = {}) => s.replace(/{{(\w+)}}/g, (_, k) => `${o[k] ?? ''}`),
					language: 'zh-CN',
					resolvedLanguage: 'zh-CN'
				})
			]
		])
	});
	await until(() => document.querySelectorAll('[data-version]').length > 0);
	return document;
};

describe('AssistantVersionsModal', () => {
	it('lists versions, diffs an older one against the current and restores it', async () => {
		library.getAssistantVersions.mockResolvedValue(versions(true));
		library.restoreAssistantVersion.mockResolvedValue({
			...versions(true),
			current: { version: 3, name: 'Coder', system: 'role\nold rule', description: '', at: 4 },
			revisions: []
		});
		const onRestored = vi.fn();
		const doc = await mount(onRestored);

		const rows = Array.from(doc.querySelectorAll('[data-version]')) as any[];
		expect(rows.map((el) => el.getAttribute('data-version'))).toEqual(['2', '1']);
		// v2 was made by the discussion run that changed v1; v1 by 精答 when it was created
		expect(rows[0].textContent).toContain('讨论台');
		expect(rows[0].textContent).toContain('加了规则');
		expect(rows[1].textContent).toContain('创建');
		expect(doc.querySelector('a[href="/discuss/c9"]')).toBeTruthy();
		expect(doc.querySelector('a[href="/answer/c0"]')).toBeTruthy();
		expect(doc.querySelector('[data-restore-version]')).toBeFalsy();

		rows[1].click();
		await until(() => !!doc.querySelector('[data-diff]'));
		const lines = (Array.from(doc.querySelectorAll('[data-diff-line]')) as any[]).map((el) => el.getAttribute('data-diff-line'));
		expect(lines).toEqual(['same', 'del', 'add']);

		(doc.querySelector('[data-restore-version="1"]') as any).click();
		await until(() => library.restoreAssistantVersion.mock.calls.length === 1);
		expect(library.restoreAssistantVersion.mock.calls[0].slice(1)).toEqual(['coder', 1]);
		await until(() => onRestored.mock.calls.length === 1);
	});

	it('offers no restore when the assistant may not be edited', async () => {
		library.getAssistantVersions.mockResolvedValue(versions(false));
		const doc = await mount();
		(doc.querySelectorAll('[data-version]')[1] as any).click();
		await until(() => !!doc.querySelector('[data-diff]'));
		expect(doc.querySelector('[data-restore-version]')).toBeFalsy();
	});
});
