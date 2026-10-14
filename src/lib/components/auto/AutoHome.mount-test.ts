import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { tick } from 'svelte';
import { installDominoDom } from '$lib/test-support/domino-dom';
installDominoDom('http://localhost/auto');
const api = vi.hoisted(() => ({
	createAutoRoute: vi.fn(),
	getAutoRoute: vi.fn(),
	listAutoRoutes: vi.fn(),
	cancelAutoRoute: vi.fn()
}));
vi.mock('$lib/apis/auto', async (original) => ({ ...(await original<any>()), ...api }));
const nav = vi.hoisted(() => ({ goto: vi.fn(), replaceState: vi.fn() }));
vi.mock('$app/navigation', () => nav);
const files = vi.hoisted(() => ({
	uploadFileReliably: vi.fn(),
	uploadErrorText: (e: any) => e.message
}));
vi.mock('$lib/utils/reliable-upload', () => files);
let Home: any, stores: any, app: any, target: HTMLElement;
const wait = () => new Promise((resolve) => setTimeout(resolve, 20));
const until = async (fn: () => boolean) => {
	for (let i = 0; i < 100 && !fn(); i++) await wait();
	expect(fn()).toBe(true);
};
const row = (extra = {}) => ({
	id: 'r1',
	question: '比较方案',
	status: 'routing',
	mode: null,
	target_id: null,
	target_status: null,
	href: null,
	reason: '',
	error: '',
	created_at: 1,
	auto_start: false,
	...extra
});
beforeAll(async () => {
	stores = await import('$lib/stores');
	Home = (await import('./AutoHome.svelte')).default;
});
beforeEach(() => {
	Object.values(api).forEach((fn) => fn.mockReset());
	nav.goto.mockReset();
	nav.replaceState.mockReset();
	sessionStorage.clear();
	localStorage.token = 'test';
	stores.config.set({ features: { enable_agent_teams: true, enable_web_search: true } });
	stores.mobile.set(false);
	api.listAutoRoutes.mockResolvedValue({ items: [], more: false });
	api.createAutoRoute.mockResolvedValue(row());
	api.getAutoRoute.mockResolvedValue(row());
	target = document.createElement('div');
	document.body.appendChild(target);
});
afterEach(() => {
	app?.$destroy();
	target.remove();
	app = null;
});
async function mount() {
	app = new Home({ target });
	await tick();
	await wait();
}
async function typeQuestion(text: string) {
	const input = target.querySelector('[aria-label="问题或任务"]') as HTMLTextAreaElement;
	input.value = text;
	input.dispatchEvent(new Event('input', { bubbles: true }));
	await tick();
}
async function submit() {
	target
		.querySelector('form')!
		.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
	await tick();
	await wait();
}

describe('automatic workbench', () => {
	it('carries incoming drafts, attachments and constraints into one request', async () => {
		const { handOff } = await import('$lib/utils/handoff');
		handOff(sessionStorage, {
			to: 'auto',
			text: '比较方案',
			context: '只分析',
			files: [{ id: 'f1', name: 'notes.txt', type: 'file' }]
		});
		await mount();
		await submit();
		expect(api.createAutoRoute).toHaveBeenCalledTimes(1);
		expect(api.createAutoRoute.mock.calls[0][1]).toMatchObject({
			question: '比较方案',
			context: '只分析',
			files: ['f1'],
			mode: 'auto',
			auto_start: false
		});
		expect(target.textContent).toContain('正在选择处理方式');
	});
	it.each([
		['answer', '/answer/a1'],
		['discuss', '/discuss/d1'],
		['team', '/teams/t1']
	])('opens the selected %s workbench', async (mode, href) => {
		api.getAutoRoute.mockResolvedValue(
			row({ status: 'dispatched', mode, target_id: 'target', href, reason: '按目标选择' })
		);
		await mount();
		await typeQuestion('请处理问题');
		await submit();
		await until(() => nav.goto.mock.calls.length > 0);
		expect(nav.goto).toHaveBeenCalledWith(href);
	});
	it('reuses the key when a response is lost and across a reload', async () => {
		api.createAutoRoute.mockRejectedValue(new Error('network'));
		await mount();
		await typeQuestion('解释报错');
		await submit();
		const key = api.createAutoRoute.mock.calls[0][1].client_key;
		app.$destroy();
		app = null;
		target.innerHTML = '';
		await mount();
		await submit();
		expect(api.createAutoRoute.mock.calls[1][1].client_key).toBe(key);
	});
	it('can cancel before dispatch and never navigates after cancellation', async () => {
		api.cancelAutoRoute.mockResolvedValue(row({ status: 'cancelled' }));
		await mount();
		await typeQuestion('解释报错');
		await submit();
		const cancel = Array.from(target.querySelectorAll('button')).find(
			(b) => b.textContent === '取消分流'
		)!;
		cancel.click();
		await wait();
		expect(api.cancelAutoRoute).toHaveBeenCalledWith('test', 'r1');
		expect(target.textContent).toContain('已取消');
		expect(nav.goto).not.toHaveBeenCalled();
	});
});
