// 自动分流 in a chat: a request that failed or was interrupted is routed again from its card,
// automatically or straight to a chosen mode, without leaving the chat.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';
installDominoDom('http://localhost/c/chat-1');
const api = vi.hoisted(() => ({
	getAutoRoute: vi.fn(),
	cancelAutoRoute: vi.fn(),
	retryAutoRoute: vi.fn()
}));
vi.mock('$lib/apis/auto', async (original) => ({ ...(await original<any>()), ...api }));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const until = async (fn: () => boolean) => {
	for (let i = 0; i < 200 && !fn(); i++) await sleep(20);
	expect(fn()).toBe(true);
};
const row = (extra = {}) => ({
	id: 'r1',
	question: '解释报错',
	status: 'error',
	mode: null,
	target_id: null,
	target_status: null,
	href: null,
	reason: '',
	error: '未能完成派发，请查看原任务或调整后重试',
	created_at: 1,
	auto_start: false,
	...extra
});
let app: any;
let target: HTMLElement;
afterEach(() => {
	app?.$destroy();
	target?.remove();
});

describe('AutoDispatchCard', () => {
	it('routes a failed request again from the card, to a chosen mode', async () => {
		(globalThis as any).localStorage.token = 'tok';
		api.getAutoRoute.mockResolvedValue(row());
		api.retryAutoRoute.mockResolvedValue(row({ id: 'r2', status: 'routing', error: '' }));
		const { default: Card } = await import('./AutoDispatchCard.svelte');
		target = document.createElement('div');
		document.body.appendChild(target);
		app = new Card({ target, props: { id: 'r1', history: { messages: {} } } });
		await until(() => !!target.querySelector('[data-auto-retry]'));
		expect(
			[...target.querySelectorAll('[data-auto-retry-mode]')].map((b: any) => b.getAttribute('data-auto-retry-mode'))
		).toEqual(['auto', 'answer', 'discuss', 'team']);
		(target.querySelector('[data-auto-retry-mode="discuss"]') as any).click();
		await until(() => api.retryAutoRoute.mock.calls.length === 1);
		expect(api.retryAutoRoute.mock.calls[0]).toEqual(['tok', 'r1', 'discuss']);
		await until(() => !target.querySelector('[data-auto-retry]'));
		// the card follows the new request from here on
		api.getAutoRoute.mockResolvedValue(row({ id: 'r2', status: 'routing', error: '' }));
		await until(() => api.getAutoRoute.mock.calls.some((call: any[]) => call[1] === 'r2'));
	});

	it('tells a stand-in and a blocker apart from a normal choice', async () => {
		(globalThis as any).localStorage.token = 'tok';
		const { default: Card } = await import('./AutoDispatchCard.svelte');
		target = document.createElement('div');
		document.body.appendChild(target);
		api.getAutoRoute.mockResolvedValue(
			row({
				status: 'error',
				blocked: true,
				error: '需要查看真实的仓库或文件，但协作台现在不可用'
			})
		);
		app = new Card({ target, props: { id: 'r1', history: { messages: {} } } });
		await until(() => !!target.querySelector('[data-auto-blocked]'));
		expect(target.textContent).toContain('已阻塞');
		expect(target.textContent).not.toContain('派发失败');
		// still routed again from here: e.g. to 精答 for general advice only
		expect(target.querySelector('[data-auto-retry-mode="answer"]')).toBeTruthy();
		app.$destroy();
		target.innerHTML = '';
		api.getAutoRoute.mockResolvedValue(
			row({
				status: 'dispatched',
				mode: 'team',
				read_only: true,
				target_id: null,
				error: '',
				reason: '要看仓库'
			})
		);
		app = new Card({ target, props: { id: 'r2', history: { messages: {} } } });
		await until(() => (target.textContent ?? '').includes('协作台（只读）'));
		expect(target.querySelector('[data-auto-degraded]')).toBeFalsy();
		app.$destroy();
		target.innerHTML = '';
		api.getAutoRoute.mockResolvedValue(
			row({
				status: 'dispatched',
				mode: 'answer',
				degraded: 'discuss',
				target_id: null,
				error: '',
				reason: '讨论不可用（可用模型不足 2 个），临时改由精答处理'
			})
		);
		app = new Card({ target, props: { id: 'r3', history: { messages: {} } } });
		await until(() => !!target.querySelector('[data-auto-degraded]'));
		expect(target.textContent).toContain('临时改用');
	});
});
