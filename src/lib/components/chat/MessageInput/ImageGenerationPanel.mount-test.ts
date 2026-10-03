import { afterEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom();
vi.mock('$app/environment', () => ({ browser: true }));
vi.mock('$lib/apis/images', () => ({ getImageGenerationModels: vi.fn(async () => []) }));
vi.mock('$lib/apis/functions', () => ({
	getUserValvesById: vi.fn(),
	getUserValvesSpecById: vi.fn(),
	updateUserValvesById: vi.fn()
}));
vi.mock('svelte-sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const { tick } = await import('svelte');
const { writable } = await import('svelte/store');
const { getImageGenerationModels } = await import('$lib/apis/images');
const { toast } = await import('svelte-sonner');
const { default: ImageGenerationPanel } = await import('./ImageGenerationPanel.svelte');

// The cch connection's gpt-image as the runtime list reports it: exact sizes, quality, background.
const gptImage = {
	id: 'gpt-image',
	name: 'gpt-image',
	provider: 'openai',
	size_mode: 'exact',
	supports_background: true,
	supports_quality: true
};

let app: InstanceType<typeof ImageGenerationPanel>;
let target: HTMLDivElement;
const settle = async () => {
	for (let i = 0; i < 4; i += 1) {
		await tick();
		await new Promise((resolve) => setTimeout(resolve, 10));
	}
};
const mount = async (models: unknown[], options: Record<string, unknown> = {}) => {
	vi.mocked(getImageGenerationModels).mockResolvedValue(models as never);
	localStorage.setItem('token', 'test');
	target = document.createElement('div');
	document.body.appendChild(target);
	app = new ImageGenerationPanel({
		target,
		props: {
			imageGenerationEnabled: true,
			imageGenerationOptions: options,
			currentModel: { id: 'gpt-image', name: 'gpt-image' } as never
		},
		context: new Map([
			['i18n', writable({ t: (_key: string, o: { defaultValue?: string } = {}) => o.defaultValue })]
		])
	});
	await settle();
};
const options = () => app.$$.ctx[app.$$.props.imageGenerationOptions];
const pending = () => app.$$.ctx[app.$$.props.pendingTemplateConfig];

afterEach(() => {
	app?.$destroy();
	target?.remove();
	vi.mocked(toast.success).mockClear();
});

describe('image template settings in the chat image panel', () => {
	it("applies a picked template's size and quality once the model is known", async () => {
		await mount([gptImage], { quality: 'low' });
		app.$set({
			pendingTemplateConfig: { prompt: 'p', size: '1024x1536', aspectRatio: '2:3', quality: 'high' }
		});
		await settle();
		expect(options()).toMatchObject({ size: '1024x1536', aspect_ratio: null, quality: 'high' });
		expect(pending()).toBeNull();
		expect(toast.success).toHaveBeenCalledTimes(1);
	});

	it('keeps what the model cannot take and stays quiet when nothing changes', async () => {
		await mount([{ ...gptImage, supports_quality: false }], { size: '1536x1024' });
		app.$set({ pendingTemplateConfig: { size: '1536x1024', quality: 'high' } });
		await settle();
		expect(options()).toEqual({ size: '1536x1024' });
		expect(pending()).toBeNull();
		expect(toast.success).not.toHaveBeenCalled();
	});
});
