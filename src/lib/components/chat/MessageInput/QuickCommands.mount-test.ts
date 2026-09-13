import { afterEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom();
vi.mock('$app/environment', () => ({ browser: true }));
vi.mock('$lib/apis/prompts', () => ({ getPrompts: vi.fn(async () => []) }));
vi.mock('$lib/apis/image-studio', () => ({ getImageStudioItems: vi.fn(async () => []) }));
vi.mock('dompurify', () => ({ default: { sanitize: (html: string) => html } }));

const { tick } = await import('svelte');
const { writable, get } = await import('svelte/store');
const { imageStudioTemplates, prompts, user } = await import('$lib/stores');
const { getImageStudioItems } = await import('$lib/apis/image-studio');
const { default: QuickCommands } = await import('./QuickCommands.svelte');

const templates = Array.from({ length: 23 }, (_, i) => ({
	id: `template-${i}`,
	name: `${'长名称用于区分不同画面构图与风格'.repeat(4)}-${i}`,
	tags: [i === 22 ? '水彩' : '摄影'],
	createdAt: 1,
	updatedAt: 23 - i,
	config: { prompt: `完整提示词 ${i}\n${i === 22 ? 'Unique Lighthouse' : 'mountains'}\n保留结尾  ` }
}));

let app: InstanceType<typeof QuickCommands>;
let target: HTMLDivElement;
const selected = vi.fn();
const settle = async () => {
	await tick();
	await new Promise((resolve) => setTimeout(resolve, 20));
	await tick();
};
const mount = async (imageMode = true, cached = true) => {
	imageStudioTemplates.set(cached ? structuredClone(templates) : null);
	prompts.set([{ command: '/chat', title: 'Chat only', content: 'Chat instruction' }] as never);
	user.set({ id: 'test-user', role: 'admin' } as never);
	target = document.createElement('div');
	document.body.appendChild(target);
	app = new QuickCommands({
		target,
		props: { imageMode, max: 2 },
		context: new Map([['i18n', writable({ t: (key: string) => key })]])
	});
	app.$on('select', (event) => selected(event.detail));
	await settle();
};
const button = (label: string) => {
	const el = Array.from(document.querySelectorAll('button')).find(
		(el) => el.getAttribute('aria-label') === label || el.textContent?.trim() === label
	);
	expect(el, `button: ${label}`).toBeTruthy();
	return el!;
};
const open = async () => {
	(target.querySelector('[data-halo-quick-commands="image"]') as HTMLButtonElement).click();
	await settle();
};
const search = async (query: string) => {
	const input = document.querySelector('input[type="search"]') as HTMLInputElement;
	input.value = query;
	input.dispatchEvent(new Event('input', { bubbles: true }));
	await settle();
};

afterEach(async () => {
	app?.$destroy();
	target?.remove();
	selected.mockClear();
	vi.mocked(getImageStudioItems).mockReset().mockResolvedValue([]);
	await settle();
});

describe('image prompts in the message input', () => {
	it('offers all 23 templates beyond the chat chip limit, with full names and intact selection', async () => {
		await mount();
		await open();
		const dialog = document.querySelector('[role="dialog"]')!;
		expect(dialog).toBeTruthy();
		for (const template of templates)
			expect(button(template.name).textContent).toContain(template.name);
		expect(dialog.textContent).not.toContain('Chat only');
		button(templates[22].name).click();
		await settle();
		expect(selected).toHaveBeenCalledTimes(1);
		expect(selected).toHaveBeenCalledWith({
			name: templates[22].name,
			content: templates[22].config.prompt
		});
		expect(document.querySelector('[role="dialog"]')).toBeFalsy();
		expect(get(imageStudioTemplates)).toEqual(templates);
	});

	it('searches names, tags and full content case-insensitively, and clears search on reopen', async () => {
		await mount();
		await open();
		for (const query of ['-22', '水彩', '  unique LIGHTHOUSE  ']) {
			await search(query);
			expect(button(templates[22].name)).toBeTruthy();
			expect(document.querySelector('[role="dialog"]')!.textContent).not.toContain(
				templates[0].name
			);
		}
		await search('no matching template');
		expect(document.body.textContent).toContain('No templates match');
		button('Close').click();
		await settle();
		await open();
		expect((document.querySelector('input[type="search"]') as HTMLInputElement).value).toBe('');
		expect(button(templates[0].name)).toBeTruthy();
		expect(selected).not.toHaveBeenCalled();
	});

	it('removes an open picker on mode switch and preserves ordinary chat selection', async () => {
		await mount();
		await open();
		app.$set({ imageMode: false });
		await settle();
		expect(document.querySelector('[role="dialog"]')).toBeFalsy();
		expect(target.textContent).not.toContain('Image prompts');
		button('Chat only').click();
		await settle();
		expect(selected).toHaveBeenCalledTimes(1);
		expect(selected).toHaveBeenCalledWith({ name: 'Chat only', content: 'Chat instruction' });
		app.$set({ imageMode: true });
		await settle();
		await open();
		expect(button(templates[22].name)).toBeTruthy();
	});

	it('shows load failure and allows an explicit retry without silently caching an empty list', async () => {
		vi.mocked(getImageStudioItems).mockRejectedValueOnce(new Error('offline'));
		await mount(true, false);
		await open();
		expect(document.body.textContent).toContain('Failed to load image prompts.');
		expect(get(imageStudioTemplates)).toBeNull();
		button('Retry').click();
		await settle();
		expect(getImageStudioItems).toHaveBeenCalledTimes(2);
		expect(document.body.textContent).toContain('No templates saved yet');
		expect(get(imageStudioTemplates)).toEqual([]);
	});

	it('shows loading then offers server templates without requiring a mode toggle', async () => {
		let finish: (items: Awaited<ReturnType<typeof getImageStudioItems>>) => void;
		vi.mocked(getImageStudioItems).mockReturnValueOnce(
			new Promise((resolve) => (finish = resolve))
		);
		await mount(true, false);
		await open();
		expect(document.body.textContent).toContain('Loading...');
		finish!(templates.map((template) => ({ id: template.id, kind: 'template', data: template })));
		await settle();
		expect(document.body.textContent).not.toContain('Loading...');
		expect(button(templates[22].name)).toBeTruthy();
		expect(getImageStudioItems).toHaveBeenCalledTimes(1);
	});

	it('keeps empty and non-insertable templates accessible through the management link', async () => {
		await mount();
		imageStudioTemplates.set([{ ...templates[0], config: { prompt: '  ' } }]);
		await open();
		expect(document.body.textContent).toContain('No templates saved yet');
		expect(document.querySelector('a[href="/workspace/images?tab=prompts"]')).toBeTruthy();
		user.set({ id: 'test-user', role: 'user', permissions: {} } as never);
		await settle();
		expect(document.querySelector('a[href="/workspace/images?tab=prompts"]')).toBeFalsy();
	});
});
