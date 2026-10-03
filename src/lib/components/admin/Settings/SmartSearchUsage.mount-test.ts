// Mounts the Smart Search usage panel of the web search settings with what
// `smart-search usage --format json` prints: per-source calls, free allowances
// (live credits when asked for), sources parked after a quota error.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

const usage = (live = false) => ({
	ok: true,
	available: true,
	today: '2026-10-03',
	days: 7,
	providers: {
		direct: { today: { calls: 25, ok: 20, errors: 5, units: 0, avg_ms: 1024 }, month: { calls: 25 }, window: { calls: 25, ok: 20, errors: 5, units: 0, avg_ms: 1024 } },
		tavily: {
			today: { calls: 13, ok: 12, errors: 0, units: 3, avg_ms: 2471 },
			month: { calls: 13 },
			window: { calls: 13, ok: 12, errors: 0, units: 3, avg_ms: 2471 },
			free_allowance: { period: 'month', allowance: 1000, used_here: 3, note: '' }
		},
		zhipu: { paid_unit: '¥0.05/次', today: { calls: 1, ok: 0, errors: 1, units: 1, avg_ms: 900 }, month: { calls: 1 }, window: { calls: 1, ok: 0, errors: 1, units: 1, avg_ms: 900 } },
		baidu: { free_allowance: { period: 'day', allowance: 50, used_here: 4, note: '' }, paid_unit: '超出免费后 ¥0.036/次' }
	},
	exhausted: { zhipu: '1113: 余额不足' },
	free_page_reads: { direct: 20, cache: 3 },
	origins: { hermes: 40, halowebui: 17 },
	...(live ? { live: { tavily: { used: 80, limit: 1000 } } } : {})
});

const getSmartSearchUsage = vi.fn(async (_token: string, live = false) => usage(live));
vi.mock('$lib/apis/retrieval', () => ({ getSmartSearchUsage }));

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

let app: any;
let target: any;

afterEach(() => {
	app?.$destroy();
	target?.remove();
	app = null;
});

describe('Smart Search usage panel', () => {
	it('shows calls per source, free allowances and parked sources, and asks for live credits', async () => {
		(globalThis as any).localStorage.token = 'tok';
		const { writable } = await import('svelte/store');
		const i18n = writable({ language: 'zh-CN', t: (key: string) => key });
		const { default: SmartSearchUsage } = await import('./SmartSearchUsage.svelte');
		target = document.createElement('div');
		document.body.appendChild(target);
		app = new SmartSearchUsage({ target, context: new Map<string, any>([['i18n', i18n]]) });
		await sleep(20);

		const text = target.textContent.replace(/\s+/g, ' ');
		expect(text).toContain('本机直抓 免费');
		expect(text).toContain('智谱 ¥0.05/次');
		expect(text).toContain('百度搜索：每天 免费 50，已用 本机记账约 4');
		expect(text).toContain('额度用完、今天先跳过： 智谱');
		expect(text).toContain('近 7 天免费读到网页 23 页');
		expect(text).toContain('近 7 天调用次数：Hermes 40，HaloWebUI 17');
		// rows sort by calls: direct first
		expect(target.querySelector('tbody tr td').textContent).toContain('本机直抓');

		const button = Array.from(target.querySelectorAll('button') as ArrayLike<any>).find((b: any) =>
			b.textContent.includes('查服务商剩余额度')
		);
		button.click();
		await sleep(20);

		expect(getSmartSearchUsage).toHaveBeenLastCalledWith('tok', true);
		expect(target.textContent.replace(/\s+/g, ' ')).toContain('Tavily：每月 免费 1000，已用 80 / 1000（服务商实时）');
	});
});
