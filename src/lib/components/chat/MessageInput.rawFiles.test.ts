import { readFileSync } from 'node:fs';
import { parse, preprocess } from 'svelte/compiler';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import { beforeAll, describe, expect, it, vi } from 'vitest';

// Exercise the actual upload handlers at the upload API boundary, without
// mounting the entire chat and its model/network dependencies.
let sources: Record<string, string> = {};

beforeAll(async () => {
	for (const [component, names] of [
		['MessageInput', ['uploadFileHandler', 'uploadImageFileHandler', 'inputFilesHandler']],
		['Chat', ['uploadGoogleDriveFile']]
	] as const) {
		const filename = `src/lib/components/chat/${component}.svelte`;
		const { code } = await preprocess(readFileSync(filename, 'utf8'), vitePreprocess(), {
			filename
		});
		const declarations = parse(code).instance!.content.body.flatMap(
			(node: any) => node.declarations ?? []
		);
		for (const name of names) {
			const declaration = declarations.find((node: any) => node.id.name === name);
			if (!declaration) throw new Error(`${component} no longer declares ${name}`);
			sources[name] = code.slice(declaration.init.start, declaration.init.end);
		}
	}
});

const composer = (hermes: boolean) => {
	const uploaded = { id: 'stored-file', meta: { processing_mode: 'retrieval' } };
	const store: Record<string, any> = {
		showHermesOptions: hermes,
		$_user: { role: 'user', permissions: { chat: { file_upload: true } } },
		$config: {},
		$settings: {},
		files: [],
		uuidv4: () => 'temp-file',
		localStorage: { token: 'test-token' },
		token: 'test-token',
		uploadFile: vi.fn().mockResolvedValue(uploaded),
		WEBUI_API_BASE_URL: '/api/v1',
		IMAGE_INPUT_MIME_TYPES: ['image/png', 'image/jpeg'],
		visionCapableModels: ['vision-model'],
		isVideoFile: (file: File) => file.type.startsWith('video/'),
		videoContactSheet: vi.fn(
			async () => new File(['jpeg'], 'clip · 画面拼图.jpg', { type: 'image/jpeg' })
		),
		buildUploadedImageContentUrl: (id: string) => `/api/v1/files/${id}/content`,
		revokePreviewUrl: () => {},
		URL: { createObjectURL: () => 'blob:preview', revokeObjectURL: () => {} },
		isHeicFile: () => false,
		setUploadFailure: vi.fn(),
		setLocalUploadFailure: vi.fn(),
		setUploadProgress: vi.fn(),
		toast: { error: vi.fn(), success: vi.fn() },
		$i18n: { t: (text: string) => text },
		fetch: vi.fn().mockResolvedValue({
			ok: true,
			headers: new Headers({ 'content-type': 'application/zip' }),
			blob: async () => new Blob(['archive'], { type: 'application/zip' })
		})
	};
	const context = new Proxy(store, {
		has: (target, key) => typeof key === 'string' && (key in target || !(key in globalThis)),
		get: (target, key) => target[key as string],
		set: (target, key, value) => {
			target[key as string] = value;
			return true;
		}
	});
	for (const [name, source] of Object.entries(sources)) {
		store[name] = new Function('context', `with (context) { return (${source}); }`)(context);
	}
	return store;
};

describe('agent attachment uploads', () => {
	it.each([
		['bundle.zip', 'application/zip'],
		['bundle.rar', 'application/vnd.rar'],
		['bundle.7z', 'application/x-7z-compressed'],
		['clip.mp4', 'video/mp4'],
		['voice.mp3', 'audio/mpeg'],
		['data.custom', ''],
		['report.pdf', 'application/pdf']
	])('uploads %s as a raw Hermes attachment', async (name, type) => {
		const store = composer(true);
		const file = new File(['attachment'], name, { type });
		await store.inputFilesHandler([file]);
		expect(store.uploadFile).toHaveBeenCalledWith('test-token', file, {
			process: false,
			processingMode: undefined,
			onProgress: expect.any(Function)
		});
		expect(store.files[0]).toMatchObject({ id: 'stored-file', name, status: 'uploaded' });
		expect(store.setUploadFailure).not.toHaveBeenCalled();
	});

	it('keeps normal model extraction and full-context uploads', async () => {
		const store = composer(false);
		await store.uploadFileHandler(new File(['text'], 'notes.txt'), true);
		expect(store.uploadFile.mock.calls[0][2]).toMatchObject({
			process: true,
			processingMode: 'full_context'
		});
	});

	it.each([true, false])(
		'uses the same upload policy for URL files (Hermes: %s)',
		async (hermes) => {
			const store = composer(hermes);
			await store.uploadGoogleDriveFile({
				id: 'drive-file',
				url: 'https://example.com/bundle.zip',
				name: 'bundle.zip',
				headers: { Authorization: 'Bearer test-token' }
			});
			expect(store.uploadFile.mock.calls[0][2]).toEqual({ process: !hermes });
			expect(store.files[0]).toMatchObject({ id: 'stored-file', status: 'uploaded' });
			expect(store.setLocalUploadFailure).not.toHaveBeenCalled();
		}
	);

	it('adds a video\'s frames as one picture for models that read images', async () => {
		const store = composer(false);
		const video = new File(['video'], 'clip.mp4', { type: 'video/mp4' });
		await store.inputFilesHandler([video]);
		expect(store.videoContactSheet).toHaveBeenCalledWith(video);
		expect(store.uploadFile.mock.calls.map((call: any[]) => [call[1].name, call[2].process])).toEqual([
			['clip.mp4', true],
			['clip · 画面拼图.jpg', false]
		]);
		expect(store.files.map((f: any) => f.type)).toEqual(['file', 'image']);
	});

	it.each([
		['Hermes', true, ['vision-model']],
		['a text-only model', false, []]
	])('sends only the video to %s', async (_, hermes, vision) => {
		const store = composer(hermes as boolean);
		store.visionCapableModels = vision;
		await store.inputFilesHandler([new File(['video'], 'clip.mp4', { type: 'video/mp4' })]);
		expect(store.videoContactSheet).not.toHaveBeenCalled();
		expect(store.uploadFile).toHaveBeenCalledTimes(1);
	});

	it('still enforces upload permission', async () => {
		const store = composer(true);
		store.$_user.permissions.chat.file_upload = false;
		await store.inputFilesHandler([new File(['archive'], 'bundle.zip')]);
		expect(store.uploadFile).not.toHaveBeenCalled();
	});

	it('still enforces the configured file size limit', async () => {
		const store = composer(true);
		store.$config.file = { max_size: 0 };
		await store.inputFilesHandler([new File(['archive'], 'bundle.zip')]);
		expect(store.uploadFile).not.toHaveBeenCalled();
	});
});
