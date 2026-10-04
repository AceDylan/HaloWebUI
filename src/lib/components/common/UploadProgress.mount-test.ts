// While an attachment uploads, the thumbnail / file card says how far it has got.
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

let UploadProgress: any;
let FileItem: any;
let app: any;

beforeAll(async () => {
	UploadProgress = (await import('./UploadProgress.svelte')).default;
	FileItem = (await import('./FileItem.svelte')).default;
}, 60000);

afterEach(() => {
	app?.$destroy();
	app = null;
	document.body.innerHTML = '';
});

const t = (key: string, vars: Record<string, unknown> = {}) =>
	key.replace(/\{\{(\w+)\}\}/g, (_, name) => String(vars[name] ?? ''));

const mount = async (Component: any, props: Record<string, unknown>) => {
	const { writable } = await import('svelte/store');
	const target = document.createElement('div');
	document.body.appendChild(target);
	app = new Component({
		target,
		props,
		context: new Map<string, any>([['i18n', writable({ t })]])
	});
	await new Promise((resolve) => setTimeout(resolve, 0));
	return target;
};

describe('UploadProgress', () => {
	it('draws a ring with the percentage while the bytes go out', async () => {
		const target = await mount(UploadProgress, { progress: 42.7 });
		const bar = target.querySelector('[role="progressbar"]')!;
		expect(bar.getAttribute('aria-valuenow')).toBe('42');
		expect(bar.getAttribute('aria-label')).toBe('Uploading 42%');
		expect(target.textContent?.trim()).toBe('42%');
		const arc = target.querySelectorAll('circle')[1];
		const full = Number(arc.getAttribute('stroke-dasharray'));
		expect(Number(arc.getAttribute('stroke-dashoffset'))).toBeCloseTo(full * 0.58, 3);
	});

	it('turns into a spinner once everything is sent', async () => {
		const target = await mount(UploadProgress, { progress: 100 });
		expect(target.querySelector('[role="progressbar"]')!.getAttribute('aria-label')).toBe(
			'Processing...'
		);
		expect(target.querySelectorAll('circle')).toHaveLength(0);
		expect(target.querySelector('.tabular-nums')).toBeFalsy();
	});

	it('is a spinner when the upload cannot report progress', async () => {
		const target = await mount(UploadProgress, { progress: null });
		expect(target.querySelector('[role="progressbar"]')!.getAttribute('aria-label')).toBe(
			'Uploading...'
		);
		expect(target.querySelectorAll('circle')).toHaveLength(0);
	});
});

describe('FileItem while uploading', () => {
	const props = (progress?: number) => ({
		item: { status: 'uploading', ...(progress === undefined ? {} : { progress }) },
		name: 'report.pdf',
		type: 'file',
		size: 2048,
		loading: true
	});

	it('says how much has gone out', async () => {
		const target = await mount(FileItem, props(37));
		expect(target.querySelector('[data-upload-status]')?.textContent?.trim()).toBe('Uploading 37%');
		expect(target.querySelector('[role="progressbar"]')?.getAttribute('aria-valuenow')).toBe('37');
	});

	it('says the server is working once the file is sent', async () => {
		const target = await mount(FileItem, props(100));
		expect(target.querySelector('[data-upload-status]')?.textContent?.trim()).toBe('Processing...');
	});

	it('keeps the old spinner and type line without a progress number', async () => {
		const target = await mount(FileItem, props());
		expect(target.querySelector('[data-upload-status]')).toBeFalsy();
		expect(target.querySelector('[role="progressbar"]')).toBeFalsy();
		expect(target.textContent).toContain('File');
	});
});
