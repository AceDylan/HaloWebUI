// Mounts the personal audio form and saves it with every choice on "Default". The patch
// must carry '' / {} explicitly: the server deep-merges user settings, so a key left out
// (undefined) keeps the old value — "Default" never replaced a stored Kokoro engine.
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/settings/audio');

vi.mock('$app/environment', () => ({
	browser: true,
	dev: false,
	building: false,
	version: 'test'
}));
vi.mock('dompurify', () => ({ default: { sanitize: (html: unknown) => String(html ?? '') } }));
vi.mock('svelte-sonner', () => ({
	toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() }
}));
vi.mock('$lib/apis/audio', async (importOriginal) => ({
	...(await importOriginal<any>()),
	getVoices: vi.fn(async () => ({ voices: [] }))
}));

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

let target: any;
let app: any;
let saveSettings: ReturnType<typeof vi.fn>;

describe('personal audio settings: "Default" is saved, not dropped', () => {
	beforeAll(async () => {
		const { writable } = await import('svelte/store');
		const stores = await import('$lib/stores');
		stores.user.set({ id: 'u-test', role: 'admin', permissions: {} });
		stores.config.set({
			audio: { stt: { engine: 'openai' }, tts: { engine: 'openai', voice: 'alloy' } }
		} as any);
		stores.settings.set({
			audio: {
				stt: { engine: '', language: '' },
				tts: { engine: '', voice: '', defaultVoice: 'alloy' }
			}
		} as any);
		const i18n = writable({
			language: 'en-US',
			t: (key: string, opts?: Record<string, any>) =>
				typeof opts?.defaultValue === 'string' ? opts.defaultValue : key,
			exists: () => false,
			on: () => {},
			off: () => {}
		});
		saveSettings = vi.fn(async () => {});
		const { default: Form } = await import('./PersonalAudioSettingsForm.svelte');
		target = document.createElement('div');
		document.body.appendChild(target);
		app = new Form({
			target,
			props: { saveSettings },
			context: new Map<string, any>([['i18n', i18n]])
		});
		await sleep(300);
	});
	afterAll(() => {
		app?.$destroy();
		target?.remove();
	});

	it('sends empty engines, language and voice, and an empty per-model voice map', async () => {
		await app.save();
		expect(saveSettings).toHaveBeenCalledTimes(1);
		const patch = saveSettings.mock.calls[0][0];
		expect(patch.audio.stt).toEqual({ engine: '', language: '' });
		expect(patch.audio.tts.engine).toBe('');
		expect(patch.audio.tts.voice).toBe('');
		expect(patch.audio.tts.modelVoices).toEqual({});
		// The same object survives the JSON round trip to the server.
		const wire = JSON.parse(JSON.stringify(patch));
		expect(wire.audio.tts).toHaveProperty('engine', '');
		expect(wire.audio.stt).toHaveProperty('engine', '');
	});
});
