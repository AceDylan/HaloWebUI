import { afterEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom();
vi.mock('$app/environment', () => ({ browser: true }));
vi.mock('$lib/apis/prompts', () => ({ getPrompts: vi.fn(async () => []) }));
vi.mock('$lib/apis/image-studio', () => ({ getImageStudioItems: vi.fn(async () => []) }));
vi.mock('$lib/apis/users', () => ({ updateUserSettings: vi.fn(), getUserSettings: vi.fn() }));
vi.mock('dompurify', () => ({ default: { sanitize: (html: string) => html } }));

const { tick } = await import('svelte');
const { writable, get } = await import('svelte/store');
const { imageStudioTemplates, prompts, settings, settingsRevision, user } = await import(
	'$lib/stores'
);
const { updateUserSettings, getUserSettings } = await import('$lib/apis/users');
const { getPrompts } = await import('$lib/apis/prompts');
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
	settings.set({});
	settingsRevision.set(0);
	vi.mocked(updateUserSettings).mockImplementation(async (_token, patch) => ({
		ui: { ...get(settings), ...patch.ui },
		revision: (patch.revision ?? 0) + 1
	}));
	imageStudioTemplates.set(cached ? structuredClone(templates) : null);
	prompts.set([{ command: '/chat', title: 'Chat only', content: 'Chat instruction' }] as never);
	user.set({ id: 'test-user', role: 'admin' } as never);
	target = document.createElement('div');
	document.body.appendChild(target);
	app = new QuickCommands({
		target,
		props: { imageMode },
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
	(target.querySelector('[data-halo-quick-commands]') as HTMLButtonElement).click();
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
	vi.mocked(updateUserSettings).mockReset();
	vi.mocked(getUserSettings).mockReset();
	vi.mocked(getPrompts).mockReset().mockResolvedValue([]);
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
		expect(target.textContent).not.toContain('Chat only');
		await open();
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

const chatPrompts = Array.from({ length: 12 }, (_, i) => ({
	id: `chat-${i}`,
	command: `/chat-${i}`,
	name: `Chat ${i}`,
	content: `Chat content ${i}\n完整正文  `
}));
const listedIds = () =>
	Array.from(document.querySelectorAll('[data-prompt-id]')).map((el) =>
		el.getAttribute('data-prompt-id')
	);
const move = async (id: string, label: string) => {
	const row = document.querySelector(`[data-prompt-id="${id}"]`)!;
	const action = Array.from(row.querySelectorAll('button')).find(
		(el) => el.textContent?.trim() === label
	)!;
	expect(action).toBeTruthy();
	action.click();
	await settle();
};

describe('chat prompt picker', () => {
	it('starts collapsed, searches all active prompts and inserts exact content beyond eight items', async () => {
		await mount(false);
		prompts.set([
			...chatPrompts,
			{ id: 'disabled', name: 'Disabled', is_active: false, content: 'hidden' },
			{ id: 'blank', name: 'Blank', content: '  ' }
		] as never);
		await settle();
		expect(target.textContent).not.toContain('Chat 11');
		expect(document.querySelector('[role="dialog"]')).toBeFalsy();
		await open();
		expect(listedIds()).toHaveLength(12);
		await search('  CHAT-11 ');
		expect(listedIds()).toEqual(['id:chat-11']);
		button('Chat 11').click();
		await settle();
		expect(selected).toHaveBeenCalledWith({ name: 'Chat 11', content: chatPrompts[11].content });
		expect(document.querySelector('[role="dialog"]')).toBeFalsy();
	});

	it('handles empty data, permissions, a failed load and retry', async () => {
		await mount();
		prompts.set(null);
		vi.mocked(getPrompts).mockRejectedValueOnce(new Error('offline'));
		app.$set({ imageMode: false });
		await settle();
		await open();
		expect(document.body.textContent).toContain('Failed to load prompts.');
		expect(get(prompts)).toBeNull();
		button('Retry').click();
		await settle();
		expect(document.body.textContent).toContain('No prompts yet.');
		expect(button('Sort prompts').disabled).toBe(true);
		expect(document.querySelector('a[href="/workspace/prompts"]')).toBeTruthy();
		user.set({ id: 'test-user', role: 'user', permissions: {} } as never);
		await settle();
		expect(document.querySelector('a[href="/workspace/prompts"]')).toBeFalsy();
	});
});

describe.each([true, false])('persistent prompt sorting (imageMode=%s)', (imageMode) => {
	const first = imageMode ? 'template-0' : 'id:chat-0';
	const second = imageMode ? 'template-1' : 'id:chat-1';
	const last = imageMode ? 'template-22' : 'id:chat-11';
	const orderKey = imageMode ? 'imagePromptOrder' : 'chatPromptOrder';
	const otherKey = imageMode ? 'chatPromptOrder' : 'imagePromptOrder';

	it('moves items, saves only its own setting and restores server order after remount', async () => {
		await mount(imageMode);
		prompts.set(chatPrompts as never);
		settings.set({ [otherKey]: ['other'], chatBubble: true });
		await open();
		await search('content that does not exist');
		button('Sort prompts').click();
		await settle();
		expect((document.querySelector('input[type="search"]') as HTMLInputElement).value).toBe('');
		expect((document.querySelector('input[type="search"]') as HTMLInputElement).disabled).toBe(
			true
		);
		await move(last, 'Move to top');
		expect(listedIds().slice(0, 3)).toEqual([last, first, second]);
		await move(last, 'Move down');
		expect(listedIds().slice(0, 3)).toEqual([first, last, second]);
		await move(second, 'Move up');
		expect(listedIds().slice(0, 3)).toEqual([first, second, last]);
		expect(get(settings)[otherKey]).toEqual(['other']);
		expect(get(settings).chatBubble).toBe(true);
		expect(updateUserSettings).toHaveBeenLastCalledWith(undefined, {
			ui: { [orderKey]: listedIds() },
			revision: 2
		});
		expect(selected).not.toHaveBeenCalled();
		const snapshot = structuredClone(get(settings));
		app.$destroy();
		target.remove();
		await mount(imageMode);
		prompts.set(chatPrompts as never);
		settings.set(snapshot);
		await open();
		expect(listedIds().slice(0, 3)).toEqual([first, second, last]);
		// The other family has its own default order.
		app.$set({ imageMode: !imageMode });
		await settle();
		await open();
		expect(listedIds()[0]).toBe(imageMode ? 'id:chat-0' : 'template-0');
	});

	it('disables duplicate moves while saving and preserves the order on failure, allowing retry', async () => {
		await mount(imageMode);
		prompts.set(chatPrompts as never);
		await open();
		button('Sort prompts').click();
		await settle();
		let rejectSave: (error: Error) => void;
		vi.mocked(updateUserSettings).mockReturnValueOnce(
			new Promise((_resolve, reject) => (rejectSave = reject))
		);
		await move(last, 'Move to top');
		expect(listedIds()[0]).toBe(first);
		expect(button('Done').disabled).toBe(true);
		await move(last, 'Move up');
		expect(updateUserSettings).toHaveBeenCalledTimes(1);
		rejectSave!(new Error('offline'));
		await settle();
		expect(document.body.textContent).toContain('Failed to save prompt order. Please try again.');
		expect(listedIds()[0]).toBe(first);
		await move(last, 'Move to top');
		expect(listedIds()[0]).toBe(last);
		expect(document.body.textContent).toContain('Prompt order saved.');
	});

	it('loads the latest order on a revision conflict, then retries against that revision', async () => {
		await mount(imageMode);
		prompts.set(chatPrompts as never);
		await open();
		button('Sort prompts').click();
		await settle();
		vi.mocked(updateUserSettings).mockRejectedValueOnce({ status: 409 });
		vi.mocked(getUserSettings).mockResolvedValueOnce({
			ui: { [orderKey]: [second, first] },
			revision: 42
		});
		await move(last, 'Move to top');
		expect(listedIds().slice(0, 2)).toEqual([second, first]);
		expect(document.body.textContent).toContain(
			'Prompt order changed elsewhere. Please try again.'
		);
		await move(last, 'Move to top');
		expect(listedIds().slice(0, 3)).toEqual([last, second, first]);
		expect(updateUserSettings).toHaveBeenLastCalledWith(undefined, {
			ui: { [orderKey]: listedIds() },
			revision: 42
		});
	});
});
