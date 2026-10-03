// "改这张" hands the image to the chat page (an event with the file id); "工作台"
// opens the image studio with it as a reference and the prompt that made it.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { writable } from 'svelte/store';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

const nav = vi.hoisted(() => ({ goto: vi.fn() }));
vi.mock('$app/navigation', () => nav);
const sonner = vi.hoisted(() => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('svelte-sonner', () => sonner);

let app: any;
let target: any;

afterEach(() => {
	app?.$destroy();
	target?.remove();
	app = null;
	vi.clearAllMocks();
});

const mount = async (props: Record<string, unknown>) => {
	const { default: ImageHandoffActions } = await import('./ImageHandoffActions.svelte');
	target = document.createElement('div');
	document.body.appendChild(target);
	app = new ImageHandoffActions({
		target,
		props,
		context: new Map<string, any>([['i18n', writable({ t: (key: string) => key, language: 'zh-CN' })]])
	});
};

describe('ImageHandoffActions', () => {
	it('puts our image in the message box and opens it in the studio', async () => {
		const { CHAT_EDIT_IMAGE_EVENT } = await import('$lib/utils/image-handoff');
		await mount({ url: '/api/v1/files/abc/content', name: 'cup.png', prompt: '一只杯子' });
		const seen: any[] = [];
		const listener = (event: any) => seen.push(event.detail);
		window.addEventListener(CHAT_EDIT_IMAGE_EVENT, listener);
		try {
			(target.querySelector('[data-image-action="edit"]') as any).click();
		} finally {
			window.removeEventListener(CHAT_EDIT_IMAGE_EVENT, listener);
		}
		expect(seen).toEqual([{ fileId: 'abc', name: 'cup.png' }]);
		expect(target.textContent).toContain('改这张');

		(target.querySelector('[data-image-action="studio"]') as any).click();
		const url = String(nav.goto.mock.calls[0]?.[0] ?? '');
		const params = new URLSearchParams(url.split('?')[1]);
		expect(url.startsWith('/workspace/images?')).toBe(true);
		expect(params.get('reference')).toBe('/api/v1/files/abc/content');
		expect(params.get('prompt')).toBe('一只杯子');
	});

	it('says so instead of handing over an outside image', async () => {
		await mount({ url: 'https://elsewhere.example/a.png' });
		(target.querySelector('[data-image-action="edit"]') as any).click();
		expect(sonner.toast.error).toHaveBeenCalledTimes(1);
	});
});
