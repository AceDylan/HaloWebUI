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
const api = vi.hoisted(() => ({
	getVideoPage: vi.fn(),
	deleteLibraryVideo: vi.fn(async () => true),
	getMusicFiles: vi.fn(async () => [] as any[])
}));
vi.mock('$lib/apis/video-studio', () => api);
const upload = vi.hoisted(() => ({ uploadFileReliably: vi.fn() }));
vi.mock('$lib/utils/reliable-upload', () => upload);
const prepApi = vi.hoisted(() => ({ startStudioPrep: vi.fn(), getStudioPrep: vi.fn(), cancelStudioPrep: vi.fn(async () => ({})) }));
vi.mock('$lib/apis/studio-prep', () => prepApi);
const toasts = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() }));
vi.mock('$lib/services/models', () => ({ ensureModels: vi.fn(async () => {}) }));
vi.mock('svelte-sonner', () => ({ toast: toasts }));

// The browser reads the music's length from its metadata; this one says 163.6 s (2:43), or
// fails to decode a file whose URL says so.
class FakeAudio {
	duration = NaN;
	preload = '';
	onloadedmetadata: (() => void) | null = null;
	onerror: (() => void) | null = null;
	set src(value: string) {
		setTimeout(() => {
			if (value.includes('broken')) this.onerror?.();
			else {
				this.duration = 163.6;
				this.onloadedmetadata?.();
			}
		}, 1);
	}
	removeAttribute() {}
}

const dropOn = async (el: any, file: File) => {
	const event: any = new Event('drop');
	event.dataTransfer = { files: [file], types: ['Files'] };
	el.dispatchEvent(event);
	await sleep(40);
};
const mp3 = (name = '夏日.mp3', bytes = [0x49, 0x44, 0x33, 4, 0, 0]) => new File([new Uint8Array(bytes)], name, { type: 'audio/mpeg' });

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
	api.getMusicFiles.mockReset();
	api.getMusicFiles.mockResolvedValue([]);
	upload.uploadFileReliably.mockReset();
	Object.values(toasts).forEach((fn) => fn.mockClear());
	(globalThis as any).Audio = FakeAudio;
	(globalThis as any).URL.createObjectURL ??= () => 'blob:local';
	(globalThis as any).URL.revokeObjectURL ??= () => {};
	sessionStorage.removeItem('halo.handoff');
	localStorage.removeItem('halo.videoStudio.settings');
	// 提示词增强 off unless a test turns it on (it is on by default)
	localStorage.setItem('halo.videoStudio.prep', JSON.stringify({ enhance: false, research: true, deeper: true }));
	sessionStorage.removeItem('halo.videoStudio.prepJob');
	prepApi.startStudioPrep.mockReset();
	prepApi.getStudioPrep.mockReset();
	prepApi.cancelStudioPrep.mockClear();
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

const prepJob = (extra: Record<string, unknown> = {}) => ({
	id: 'job1',
	kind: 'video',
	status: 'done',
	idea: '用 30 秒讲讲番茄工作法',
	steps: [],
	run: null,
	result: {
		idea: '增强后的需求：开场一个番茄钟倒计时……',
		notes: '- 番茄工作法由 Francesco Cirillo 在 1980 年代末提出',
		sources: [{ n: 1, title: '番茄工作法 - 百科', url: 'https://example.com/pomodoro' }],
		run: { kind: 'answer', chatId: 'c1', href: '/answer/c1', label: '精答' }
	},
	error: '',
	model: 'gpt-chat',
	createdAt: 1,
	...extra
});

describe('Videos 提示词增强', () => {
	it('enhances the request before it goes out: the enhanced text, the user\'s words, the facts and their sources', async () => {
		localStorage.setItem('halo.videoStudio.prep', JSON.stringify({ enhance: true, research: true, deeper: true }));
		api.getVideoPage.mockResolvedValue({ items: [], next: null });
		prepApi.startStudioPrep.mockResolvedValue(prepJob());
		const target = await mount();
		await typeIdea(target, '用 30 秒讲讲番茄工作法');
		expect(target.querySelector('[data-video-status]').textContent).toContain('先增强需求');
		target.querySelector('[data-video-workbench]').dispatchEvent(new Event('submit'));
		await sleep(30);
		expect(prepApi.startStudioPrep).toHaveBeenCalledTimes(1);
		const form = prepApi.startStudioPrep.mock.calls[0][1];
		expect(form).toMatchObject({ kind: 'video', idea: '用 30 秒讲讲番茄工作法', research: true, deeper: true });
		expect(form.settings).toContain('做法：讲解动画');
		expect(form.settings).toContain('时长：约 30 秒');
		expect(nav.goto).toHaveBeenCalledWith('/');
		const text = JSON.parse(sessionStorage.getItem('halo.handoff')!).text;
		expect(text).toContain('## 想要的视频\n增强后的需求');
		expect(text).toContain('## 用户原话');
		expect(text).toContain('用 30 秒讲讲番茄工作法');
		expect(text).toContain('## 资料与依据');
		expect(text).toContain('Francesco Cirillo');
		expect(text).toContain('精答结论：HaloWebUI /answer/c1');
		expect(text).toContain('1. 番茄工作法 - 百科 https://example.com/pomodoro');
		expect(text).toContain('MEDIA:」紧跟成片');
		expect(target.querySelector('[data-video-idea]').value).toContain('增强后的需求');
	});

	it('goes on from the words as written when the enhancement fails', async () => {
		localStorage.setItem('halo.videoStudio.prep', JSON.stringify({ enhance: true, research: false, deeper: false }));
		api.getVideoPage.mockResolvedValue({ items: [], next: null });
		prepApi.startStudioPrep.mockRejectedValue({ detail: '没有可用来增强的文本模型' });
		const target = await mount();
		await typeIdea(target, '做个片头');
		target.querySelector('[data-video-workbench]').dispatchEvent(new Event('submit'));
		await sleep(30);
		expect(prepApi.startStudioPrep.mock.calls[0][1]).toMatchObject({ research: false, deeper: false });
		expect(toasts.warning).toHaveBeenCalledWith('没有可用来增强的文本模型，按原文制作');
		const text = JSON.parse(sessionStorage.getItem('halo.handoff')!).text;
		expect(text).toContain('## 想要的视频\n做个片头');
		expect(text).not.toContain('## 用户原话');
	});

	it('「增强」 puts the enhanced text in the box to read first, with a way back', async () => {
		api.getVideoPage.mockResolvedValue({ items: [], next: null });
		prepApi.startStudioPrep.mockResolvedValue(prepJob({ status: 'running', result: null, steps: [{ key: 'plan', label: '分析需求', status: 'running' }] }));
		prepApi.getStudioPrep.mockResolvedValue(prepJob());
		const target = await mount();
		await typeIdea(target, '用 30 秒讲讲番茄工作法');
		target.querySelector('[data-video-enhance]').click();
		await sleep(30);
		expect(target.querySelector('[data-studio-prep="running"]')).toBeTruthy();
		expect(target.querySelector('[data-studio-prep-step="plan"]').textContent).toContain('分析需求');
		expect(target.querySelector('[data-video-start]').disabled).toBe(true);
		await sleep(1700);
		expect(target.querySelector('[data-video-idea]').value).toContain('增强后的需求');
		expect(target.querySelector('[data-studio-prep="done"]').textContent).toContain('参考了精答结论');
		expect(nav.goto).not.toHaveBeenCalled();
		// 开始制作 now sends it as it is: no second enhancement
		target.querySelector('[data-video-workbench]').dispatchEvent(new Event('submit'));
		await sleep(30);
		expect(prepApi.startStudioPrep).toHaveBeenCalledTimes(1);
		expect(JSON.parse(sessionStorage.getItem('halo.handoff')!).text).toContain('增强后的需求');
	}, 10000);

	it('undoes the enhancement, and remembers what it may do', async () => {
		api.getVideoPage.mockResolvedValue({ items: [], next: null });
		prepApi.startStudioPrep.mockResolvedValue(prepJob());
		const target = await mount();
		await typeIdea(target, '用 30 秒讲讲番茄工作法');
		target.querySelector('[data-video-enhance]').click();
		await sleep(30);
		target.querySelector('[data-studio-prep-undo]').click();
		await sleep(10);
		expect(target.querySelector('[data-video-idea]').value).toBe('用 30 秒讲讲番茄工作法');
		expect(target.querySelector('[data-studio-prep]')).toBeFalsy();
		target.querySelector('[data-video-prep="deeper"]').click();
		target.querySelector('[data-video-prep="enhance"]').click();
		await sleep(10);
		expect(JSON.parse(localStorage.getItem('halo.videoStudio.prep')!)).toEqual({ enhance: true, research: true, deeper: false });
	});
});

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

	it('makes the video to the MP3 the user uploads, and sends that music with the brief', async () => {
		api.getVideoPage.mockResolvedValue({ items: [], next: null });
		upload.uploadFileReliably.mockResolvedValue({ file: { id: 'm9' } });
		const target = await mount();
		await typeIdea(target, '用这首歌做旅行回顾');
		await dropOn(target.querySelector('[data-video-music]'), mp3());
		expect(upload.uploadFileReliably).toHaveBeenCalledTimes(1);
		expect(upload.uploadFileReliably.mock.calls[0][2]).toMatchObject({ process: false });
		expect(target.querySelector('[data-video-music-picked]').getAttribute('data-video-music-picked')).toBe('m9');
		expect(target.querySelector('[data-video-music-picked]').textContent).toContain('2:43');
		expect(target.querySelector('[data-video-music-player]')).toBeTruthy();
		const brief = () => target.querySelector('[data-video-brief] pre').textContent;
		// the music decides the length: as long as the music by default
		expect(brief()).toContain('时长：跟背景音乐一样长（2:43）');
		expect(brief()).toContain('音乐文件：夏日.mp3（2:43）');
		expect(brief()).toContain('--check-music');
		expect(target.querySelector('[data-video-status]').textContent).toContain('跟音乐 2:43 · 配乐已定');
		// a length chip cuts the music to it; 「跟音乐一样长」 goes back
		target.querySelector('[data-video-length="60"]').click();
		await sleep(10);
		expect(brief()).toContain('"music_fit": "trim", "seconds": 60');
		expect(target.querySelector('[data-video-music-fit="trim"]').textContent).toContain('1 分钟');
		target.querySelector('[data-video-music-fit="full"]').click();
		await sleep(10);
		expect(brief()).toContain('"music_fit": "full"');
		target.querySelector('[data-video-workbench]').dispatchEvent(new Event('submit'));
		await sleep(10);
		const entry = JSON.parse(sessionStorage.getItem('halo.handoff')!);
		expect(entry.files).toEqual([{ id: 'm9', name: '夏日.mp3', type: 'file' }]);
		expect(entry.text).toContain('## 背景音乐');
		expect(entry.text).not.toContain('参考附件');
		expect(JSON.parse(localStorage.getItem('halo.videoStudio.settings')!)).toMatchObject({ musicFit: 'full' });
	});

	it('refuses background music that is not a playable MP3, and waits for an upload', async () => {
		api.getVideoPage.mockResolvedValue({ items: [], next: null });
		const target = await mount();
		const area = target.querySelector('[data-video-music]');
		await dropOn(area, new File([new Uint8Array([1, 2, 3])], 'song.wav', { type: 'audio/wav' }));
		await dropOn(area, mp3('fake.mp3', [0x3c, 0x68, 0x74, 0x6d]));
		expect(toasts.error.mock.calls.map((c) => c[0])).toEqual(['背景音乐只支持 MP3 文件', '文件内容不是 MP3']);
		(globalThis as any).URL.createObjectURL = () => 'blob:broken';
		await dropOn(area, mp3('坏的.mp3'));
		expect(toasts.error).toHaveBeenLastCalledWith('「坏的.mp3」放不出来，换一个 MP3 试试');
		expect(upload.uploadFileReliably).not.toHaveBeenCalled();
		expect(target.querySelector('[data-video-music-picked]')).toBeFalsy();
		(globalThis as any).URL.createObjectURL = () => 'blob:local';
		// while it uploads the video cannot start
		upload.uploadFileReliably.mockReturnValue(new Promise(() => {}));
		await typeIdea(target, '做个片头');
		await dropOn(area, mp3());
		expect(target.querySelector('[data-video-start]').disabled).toBe(true);
		expect(target.querySelector('[data-video-blocked]').textContent).toContain('背景音乐还在上传');
		target.querySelector('[data-video-music-remove]').click();
		await sleep(10);
		expect(target.querySelector('[data-video-start]').disabled).toBe(false);
	});

	it('picks music uploaded before, and takes it out again', async () => {
		api.getVideoPage.mockResolvedValue({ items: [], next: null });
		api.getMusicFiles.mockResolvedValue([{ id: 'm1', name: 'old.mp3', size: 1024, createdAt: 1 }]);
		const target = await mount();
		await typeIdea(target, '做个片头');
		target.querySelector('[data-video-music-pick="m1"]').click();
		await sleep(20);
		expect(target.querySelector('[data-video-music-player]').getAttribute('src')).toBe('/api/v1/files/m1/content');
		expect(target.querySelector('[data-video-brief] pre').textContent).toContain('音乐文件：old.mp3（2:43）');
		target.querySelector('[data-video-music-remove]').click();
		await sleep(10);
		expect(target.querySelector('[data-video-brief] pre').textContent).not.toContain('背景音乐');
		expect(target.querySelector('[data-video-music-pick="m1"]')).toBeTruthy();
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

	it('shows a video from a run started on Telegram by its task, runner and platform', async () => {
		api.getVideoPage.mockResolvedValue({
			items: [video(7, { origin: 'runner', runner: 'codex', platform: 'telegram', runId: '20261015-224655-9fe3765e', runTitle: '生成一段视频，讲述长征', name: '长征_山河记得.mp4' })],
			next: null
		});
		const target = await mount();
		target.querySelector('[data-video-tab="library"]').click();
		await sleep(20);
		const card = target.querySelector('[data-video-card="video_7"]');
		expect(card.textContent).toContain('生成一段视频，讲述长征');
		expect(card.textContent).toContain('codex');
		expect(card.querySelector('[data-video-chat]')).toBeFalsy();
		const source = card.querySelector('[data-video-run]');
		expect(source.textContent.trim()).toBe('Telegram');
		expect(source.getAttribute('title')).toContain('20261015-224655-9fe3765e');
	});
});
