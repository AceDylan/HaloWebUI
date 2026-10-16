// 视频工作台: the brief goes to a new Hermes chat and is sent at once (a runner by its command in
// front); the library comes a page at a time, links back to the chat and takes a video out.
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/workspace/videos');

const nav = vi.hoisted(() => ({ goto: vi.fn(), replaceState: vi.fn() }));
vi.mock('$app/navigation', () => nav);
vi.mock('$app/stores', async () => {
	const { writable } = await import('svelte/store');
	return { page: writable({ url: new URL('http://localhost/workspace/videos') }), navigating: writable(null), updated: { subscribe: writable(false).subscribe } };
});
const api = vi.hoisted(() => ({ getVideoPage: vi.fn(), deleteLibraryVideo: vi.fn(async () => true) }));
vi.mock('$lib/apis/video-studio', () => api);
vi.mock('$lib/services/models', () => ({ ensureModels: vi.fn(async () => {}) }));
vi.mock('svelte-sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
let stores: any;
const apps: any[] = [];

const video = (n: number, extra: Record<string, unknown> = {}) => ({
	id: `video_${n}`,
	fileId: `f${n}`,
	url: `/api/v1/files/f${n}/content`,
	name: `clip-${n}.mp4`,
	title: `clip-${n}`,
	size: 2048,
	contentType: 'video/mp4',
	origin: 'hermes',
	createdAt: 1_700_000_000_000 + n,
	...extra
});

beforeAll(async () => {
	stores = await import('$lib/stores');
}, 60000);

beforeEach(() => {
	nav.goto.mockReset();
	api.getVideoPage.mockReset();
	api.deleteLibraryVideo.mockClear();
	sessionStorage.removeItem('halo.handoff');
	localStorage.removeItem('halo.videoStudio.settings');
	localStorage.token = 'token';
	stores.config.set({ features: {}, hermes_agent_model_ids: ['hermes-agent'] } as any);
	stores.user.set({ id: 'u1', role: 'admin' } as any);
	stores.models.set([
		{ id: 'openai.gpt-chat', name: 'gpt-chat' },
		{ id: 'hermes.hermes-agent', name: 'Hermes', original_id: 'hermes-agent' }
	] as any);
});

afterEach(() => {
	apps.splice(0).forEach((app) => app.$destroy());
	document.body.innerHTML = '';
});

const mount = async () => {
	const { writable } = await import('svelte/store');
	const { default: Videos } = await import('./Videos.svelte');
	const target = document.createElement('div');
	document.body.appendChild(target);
	apps.push(new Videos({ target, props: {}, context: new Map([['i18n', writable({ t: (s: string) => s })]]) }));
	await sleep(30);
	return target;
};

const typeIdea = async (target: any, text: string) => {
	const box = target.querySelector('[data-video-idea]');
	box.value = text;
	box.dispatchEvent(new Event('input'));
	await sleep(10);
};

describe('Videos', () => {
	it('sends the brief to a new Hermes chat, with a runner in front when one is picked', async () => {
		api.getVideoPage.mockResolvedValue({ items: [], next: null });
		const target = await mount();
		const start = target.querySelector('[data-video-start]');
		expect(start.disabled).toBe(true);
		await typeIdea(target, '用 30 秒讲讲番茄工作法');
		expect(start.disabled).toBe(false);
		target.querySelector('[data-video-maker="codex"]').click();
		target.querySelector('[data-video-recipe="story"]').click();
		await sleep(10);
		expect(target.querySelector('[data-video-brief] pre').textContent).toContain('做法：图文成片');
		target.querySelector('[data-video-workbench]').dispatchEvent(new Event('submit'));
		await sleep(10);
		expect(nav.goto).toHaveBeenCalledWith('/');
		const entry = JSON.parse(sessionStorage.getItem('halo.handoff')!);
		expect(entry).toMatchObject({ to: 'chat', models: ['hermes.hermes-agent'], send: true, files: [] });
		expect(entry.text.startsWith('/codex 请制作一个视频')).toBe(true);
		expect(entry.text).toContain('用 30 秒讲讲番茄工作法');
		// the choices are remembered for next time
		expect(JSON.parse(localStorage.getItem('halo.videoStudio.settings')!)).toMatchObject({ maker: 'codex', recipe: 'story' });
	});

	it('says why it cannot start without a Hermes model', async () => {
		api.getVideoPage.mockResolvedValue({ items: [], next: null });
		stores.models.set([{ id: 'openai.gpt-chat', name: 'gpt-chat' }] as any);
		const target = await mount();
		await typeIdea(target, '做个片头');
		expect(target.querySelector('[data-video-start]').disabled).toBe(true);
		expect(target.querySelector('[data-video-blocked]').textContent).toContain('没有可用的 Hermes 模型');
	});

	it('takes over a draft and its files handed from a chat', async () => {
		api.getVideoPage.mockResolvedValue({ items: [], next: null });
		sessionStorage.setItem(
			'halo.handoff',
			JSON.stringify({ to: 'video', text: '把这些照片做成旅行回顾', models: [], files: [{ id: 'p1', name: 'a.jpg', type: 'image' }, { id: 'm1', name: 'bgm.mp3', type: 'file' }], context: '', from: { kind: 'chat', id: 'c1', title: '旅行' }, at: Date.now() })
		);
		const target = await mount();
		expect(target.querySelector('[data-video-idea]').value).toBe('把这些照片做成旅行回顾');
		expect(target.querySelectorAll('[data-video-attachments] img').length).toBe(1);
		expect(target.querySelector('[data-video-brief] pre').textContent).toContain('1 个图片、1 个音频');
		expect(target.querySelector('[data-handoff-back="chat"]').getAttribute('href')).toBe('/c/c1');
	});

	it('lists the library a page at a time and takes a video out', async () => {
		api.getVideoPage
			.mockResolvedValueOnce({ items: [video(3, { chatId: 'c9', chatTitle: '番茄工作法', origin: 'runner' }), video(2)], next: 'cursor-1' })
			.mockResolvedValueOnce({ items: [video(1)], next: null });
		const target = await mount();
		target.querySelector('[data-video-tab="library"]').click();
		await sleep(20);
		const cards = () => [...target.querySelectorAll('[data-video-card]')].map((el: any) => el.getAttribute('data-video-card'));
		expect(cards()).toEqual(['video_3', 'video_2']);
		expect(target.querySelector('[data-video-card="video_3"]').textContent).toContain('番茄工作法');
		expect(target.querySelector('[data-video-card="video_3"]').textContent).toContain('runner');
		expect(target.querySelector('[data-video-card="video_3"] [data-video-chat]').getAttribute('href')).toBe('/c/c9');
		expect(target.querySelector('[data-video-card="video_2"] [data-video-chat]')).toBeFalsy();
		target.querySelector('[data-load-more-button]').click();
		await sleep(20);
		expect(api.getVideoPage).toHaveBeenLastCalledWith(expect.anything(), { limit: 24, before: 'cursor-1', q: '' });
		expect(cards()).toEqual(['video_3', 'video_2', 'video_1']);
		target.querySelector('[data-video-delete="video_2"]').click();
		await sleep(20);
		expect(api.deleteLibraryVideo).toHaveBeenCalledWith(expect.anything(), 'video_2');
		expect(cards()).toEqual(['video_3', 'video_1']);
	});
});
