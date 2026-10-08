// Image studio: a generation the page lost track of (phone reloaded it mid-run,
// 2026-10-05) is picked up with the same request id and recorded once; a lost
// connection is asked again with that id instead of being shown as a failure.
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/workspace/images');

const images = vi.hoisted(() => ({
	getImageGenerationModels: vi.fn(),
	getImageUsageConfig: vi.fn(),
	imageGenerations: vi.fn()
}));
vi.mock('$lib/apis/images', () => images);
const studio = vi.hoisted(() => ({
	clearImageStudioItems: vi.fn(),
	deleteImageStudioItem: vi.fn(),
	getImageStudioItemPage: vi.fn(),
	getImageStudioItems: vi.fn(),
	importLegacyImageStudioItems: vi.fn(),
	upsertImageStudioItems: vi.fn()
}));
vi.mock('$lib/apis/image-studio', () => studio);
vi.mock('$lib/utils/reliable-upload', () => ({ uploadFileReliably: vi.fn() }));
vi.mock('$app/navigation', () => ({ goto: vi.fn(), replaceState: vi.fn() }));
const toasts = vi.hoisted(() => ({
	success: vi.fn(),
	error: vi.fn(),
	info: vi.fn(),
	warning: vi.fn()
}));
vi.mock('svelte-sonner', () => ({ toast: toasts }));

const PENDING_KEY = 'workspace:image-studio:pending-run:v1';

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const until = async (check: () => boolean, ms = 30000) => {
	const end = Date.now() + ms;
	while (!check()) {
		if (Date.now() > end) throw new Error('timed out waiting for the view');
		await sleep(25);
	}
};

let Images: any;
let app: any;
let stores: any;

beforeAll(async () => {
	stores = await import('$lib/stores');
	Images = (await import('./Images.svelte')).default;
}, 60000);

beforeEach(() => {
	Object.values(images).forEach((fn: any) => fn.mockReset());
	Object.values(studio).forEach((fn: any) => fn.mockReset());
	Object.values(toasts).forEach((fn: any) => fn.mockReset());
	localStorage.clear();
	localStorage.token = 't';
	// Nothing left to migrate from this browser.
	localStorage.setItem(
		'workspace:image-studio:server-migration:v1',
		JSON.stringify({ userId: 'u1' })
	);
	stores.user.set({ id: 'u1', role: 'admin', permissions: {} } as any);
	stores.settings.set({} as any);
	images.getImageUsageConfig.mockResolvedValue({ enabled: true });
	images.getImageGenerationModels.mockResolvedValue([
		{
			id: 'gpt-image',
			name: 'gpt-image',
			selection_id: 'm-img',
			provider: 'openai',
			size_mode: 'exact'
		}
	]);
	studio.getImageStudioItems.mockResolvedValue([]);
	studio.getImageStudioItemPage.mockResolvedValue({ items: [], next: null });
	studio.upsertImageStudioItems.mockResolvedValue([]);
});

afterEach(() => {
	app?.$destroy();
	app = null;
	document.body.innerHTML = '';
});

const mount = async () => {
	const { writable } = await import('svelte/store');
	const target = document.createElement('div');
	document.body.appendChild(target);
	app = new Images({ target, context: new Map([['i18n', writable({ t: (s: string) => s })]]) });
	return target;
};

const pendingRun = (startedAt: number) => ({
	id: 'run-1',
	startedAt,
	payload: {
		client_request_id: 'run-1',
		prompt: '第二世界海报',
		model: 'm-img',
		image_url: '/ref'
	},
	record: {
		prompt: '第二世界海报',
		model: 'gpt-image',
		size: '1024x1536',
		parameters: { modelId: 'm-img', size: '1024x1536', references: ['/ref'] }
	}
});

const upserted = () => studio.upsertImageStudioItems.mock.calls.flatMap((call: any[]) => call[1]);

describe('Image studio run that outlives the page', () => {
	it('picks up the unfinished run after a reload, with the same id, and records it once', async () => {
		const startedAt = Date.now() - 50_000;
		localStorage.setItem(PENDING_KEY, JSON.stringify(pendingRun(startedAt)));
		images.imageGenerations.mockResolvedValue([{ url: '/api/v1/files/new/content' }]);

		await mount();
		await until(() => upserted().length > 0);

		expect(images.imageGenerations).toHaveBeenCalledTimes(1);
		expect(images.imageGenerations.mock.calls[0][1]).toEqual(pendingRun(startedAt).payload);
		expect(toasts.info).toHaveBeenCalledWith('Picking up the image you started generating');

		const items = upserted();
		const history = items.find((item: any) => item.kind === 'history');
		const gallery = items.find((item: any) => item.kind === 'gallery');
		expect(history.data).toMatchObject({
			status: 'success',
			prompt: '第二世界海报',
			images: ['/api/v1/files/new/content'],
			createdAt: startedAt,
			parameters: { references: ['/ref'] }
		});
		expect(gallery.data).toMatchObject({ url: '/api/v1/files/new/content', size: '1024x1536' });
		expect(localStorage.getItem(PENDING_KEY)).toBeNull();
	});

	it('asks again when the connection is lost instead of failing', async () => {
		localStorage.setItem(PENDING_KEY, JSON.stringify(pendingRun(Date.now())));
		images.imageGenerations
			.mockRejectedValueOnce('Server connection failed')
			.mockResolvedValueOnce([{ url: '/api/v1/files/again/content' }]);

		await mount();
		await until(() => upserted().length > 0, 10000);

		expect(images.imageGenerations).toHaveBeenCalledTimes(2);
		const ids = images.imageGenerations.mock.calls.map((call: any[]) => call[1].client_request_id);
		expect(ids).toEqual(['run-1', 'run-1']);
		expect(toasts.error).not.toHaveBeenCalled();
		expect(upserted().find((item: any) => item.kind === 'history').data.status).toBe('success');
	});

	it('opened again while this page still waits for the run: sent and recorded once', async () => {
		localStorage.setItem(PENDING_KEY, JSON.stringify(pendingRun(Date.now())));
		let finish: (value: unknown) => void = () => {};
		images.imageGenerations.mockReturnValueOnce(new Promise((resolve) => (finish = resolve)));

		await mount();
		await until(() => images.imageGenerations.mock.calls.length === 1);
		// Leave for a chat and come back while the image is still being made.
		app.$destroy();
		document.body.innerHTML = '';
		await mount();
		await until(() => images.getImageGenerationModels.mock.calls.length === 2);
		await sleep(200);
		expect(images.imageGenerations).toHaveBeenCalledTimes(1);

		finish([{ url: '/api/v1/files/once/content' }]);
		await until(() => upserted().length > 0);
		await sleep(200);
		expect(upserted().filter((item: any) => item.kind === 'history')).toHaveLength(1);
	});

	it('leaves an expired run alone', async () => {
		localStorage.setItem(PENDING_KEY, JSON.stringify(pendingRun(Date.now() - 31 * 60 * 1000)));
		await mount();
		await until(() => images.getImageGenerationModels.mock.calls.length > 0);
		await sleep(200);
		expect(images.imageGenerations).not.toHaveBeenCalled();
		expect(localStorage.getItem(PENDING_KEY)).toBeNull();
	});
});
