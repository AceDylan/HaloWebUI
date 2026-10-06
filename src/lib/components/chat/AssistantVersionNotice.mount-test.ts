// A chat keeps the assistant version it started with: when the assistant moved on, the chat says
// so and can switch to the new version.
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

const api = vi.hoisted(() => ({ getStalePins: vi.fn(), refreshPin: vi.fn() }));
vi.mock('$lib/apis/assistant-library', () => api);
const toasts = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock('svelte-sonner', () => ({ toast: toasts }));

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const until = async (check: () => boolean, ms = 10000) => {
	const end = Date.now() + ms;
	while (!check()) {
		if (Date.now() > end) throw new Error('timed out waiting for the view');
		await sleep(25);
	}
};

let Notice: any;
const apps: any[] = [];

beforeAll(async () => {
	Notice = (await import('./AssistantVersionNotice.svelte')).default;
}, 60000);

afterEach(() => {
	apps.splice(0).forEach((app) => app.$destroy());
	document.body.innerHTML = '';
});

const mount = (props: Record<string, unknown>) => {
	const target = document.createElement('div');
	document.body.appendChild(target);
	apps.push(new Notice({ target, props }));
	return target;
};

describe('AssistantVersionNotice', () => {
	it('says the chat keeps an older version and switches to the new one', async () => {
		localStorage.token = 't';
		api.getStalePins.mockResolvedValue([{ id: 'asst-1', name: '软件架构师', pinned: 2, current: 3 }]);
		api.refreshPin.mockResolvedValue({ ok: true });
		const target = mount({ chatId: 'c1' });
		await until(() => !!target.querySelector('[data-assistant-version-notice="asst-1"]'));
		expect(target.textContent).toContain('第 3 版');
		expect(target.textContent).toContain('第 2 版');
		(target.querySelector('[data-assistant-version-switch]') as any).click();
		await until(() => !target.querySelector('[data-assistant-version-notice]'));
		expect(api.refreshPin).toHaveBeenCalledWith('t', 'c1', 'asst-1');
		expect(toasts.success).toHaveBeenCalled();
	});

	it('asks nothing for a new or temporary chat', async () => {
		api.getStalePins.mockReset();
		mount({ chatId: '' });
		mount({ chatId: 'local:abc' });
		await sleep(50);
		expect(api.getStalePins).not.toHaveBeenCalled();
	});
});
