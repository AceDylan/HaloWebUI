// Mounts the 消息网关 settings page. The Hermes options panel says
// 「思考强度高 … 去修改」 and links here, so the thinking-level select must use
// the same words (高/超高), not the raw values (high/xhigh).
import { afterEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

vi.mock('$lib/apis', () => ({ getModels: vi.fn(async () => []) }));
vi.mock('$lib/apis/haloclaw', () => ({
	getHaloClawConfig: vi.fn(async () => ({ enabled: true, default_reasoning_effort: 'high' })),
	updateHaloClawConfig: vi.fn(),
	getGateways: vi.fn(async () => []),
	createGateway: vi.fn(),
	updateGateway: vi.fn(),
	toggleGateway: vi.fn(),
	deleteGateway: vi.fn()
}));

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

let app: any;
let target: any;

afterEach(() => {
	app?.$destroy();
	target?.remove();
	app = null;
});

describe('HaloClaw settings', () => {
	it('names the thinking levels the way the Hermes panel does', async () => {
		(globalThis as any).localStorage.token = 'tok';
		const { writable } = await import('svelte/store');
		const i18n = writable({ language: 'zh-CN', t: (key: string) => key });
		const { default: HaloClaw } = await import('./HaloClaw.svelte');
		target = document.createElement('div');
		document.body.appendChild(target);
		app = new HaloClaw({ target, context: new Map<string, any>([['i18n', i18n]]) });

		const started = Date.now();
		let select: any;
		while (!select) {
			select = Array.from(target.querySelectorAll('select')).find((el: any) =>
				Array.from(el.querySelectorAll('option')).some((o: any) => o.value === 'xhigh')
			);
			if (Date.now() - started > 8000) throw new Error('timed out waiting for the select');
			await sleep(15);
		}
		const options = Array.from(select.querySelectorAll('option')).map((o: any) => [
			o.value,
			o.textContent.trim()
		]);
		expect(options).toEqual([
			['none', '关闭'],
			['low', '低'],
			['medium', '中'],
			['high', '高'],
			['xhigh', '超高'],
			['max', '最大']
		]);
	});
});
