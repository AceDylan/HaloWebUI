// 定时任务 page against a fake hermes: jobs listed with their time in words and their state,
// 立即运行 / 暂停 call hermes, a new job is made from the picker, a script job keeps its prompt.
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/workspace/schedules');

const api = vi.hoisted(() => ({
	listHermesJobs: vi.fn(),
	createHermesJob: vi.fn(),
	updateHermesJob: vi.fn(),
	deleteHermesJob: vi.fn(),
	hermesJobAction: vi.fn(),
	getHermesJobOutputs: vi.fn()
}));
vi.mock('$lib/apis/hermes', () => api);
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() }));
vi.mock('svelte-sonner', () => ({ toast }));

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const until = async (check: () => boolean, ms = 15000) => {
	const end = Date.now() + ms;
	while (!check()) {
		if (Date.now() > end) throw new Error(`timed out; text: ${document.body.textContent?.slice(0, 300)}`);
		await sleep(20);
	}
};

const base = {
	prompt: '',
	script: null,
	no_agent: false,
	skills: [],
	schedule_display: null,
	repeat: { times: null, completed: 3 },
	enabled: true,
	state: 'scheduled',
	paused_reason: null,
	created_at: null,
	last_status: 'ok',
	last_error: null,
	last_delivery_error: null,
	failure_streak: 0,
	latest_execution: null
};
const JOBS = [
	{
		...base,
		id: 'c5a0e24a8ec9',
		name: '每周更新 CLI',
		script: 'weekly-cli-updates.sh',
		no_agent: true,
		schedule: { kind: 'cron', expr: '0 7 * * 1', display: '0 7 * * 1' },
		next_run_at: '2099-10-12T07:00:00+08:00',
		last_run_at: '2026-10-05T07:01:18+08:00',
		deliver: 'telegram:5231'
	},
	{
		...base,
		id: 'aaaaaaaaaaaa',
		name: '早报',
		prompt: '汇总新闻',
		schedule: { kind: 'interval', minutes: 120 },
		enabled: false,
		state: 'paused',
		next_run_at: null,
		last_run_at: null,
		last_status: null,
		deliver: 'local'
	},
	{
		...base,
		id: 'bbbbbbbbbbbb',
		name: '一次性提醒',
		prompt: '提醒我',
		schedule: { kind: 'once', run_at: '2026-10-07T04:45:00+08:00' },
		state: 'completed',
		enabled: false,
		next_run_at: null,
		last_run_at: '2026-10-07T04:45:10+08:00',
		deliver: 'telegram:5231'
	}
];

let Page: any;
let app: any;
let target: any;

beforeAll(async () => {
	Page = (await import('./Schedules.svelte')).default;
}, 120_000);

beforeEach(() => {
	Object.values(api).forEach((fn: any) => fn.mockReset());
	toast.success.mockReset();
	toast.error.mockReset();
	api.listHermesJobs.mockResolvedValue(JOBS.map((job) => ({ ...job })));
	(globalThis as any).localStorage.token = 'tok';
});

afterEach(() => {
	app?.$destroy();
	target?.remove();
	app = null;
});

const mount = async () => {
	const { writable } = await import('svelte/store');
	target = document.createElement('div');
	document.body.appendChild(target);
	app = new Page({ target, context: new Map([['i18n', writable({ t: (s: string) => s })]]) });
	await until(() => target.querySelectorAll('[data-schedule-job]').length > 0);
};
const card = (id: string) => target.querySelector(`[data-schedule-job="${id}"]`) as any;
const setValue = (el: any, value: string) => {
	if (el.tagName === 'SELECT') {
		// domino has no select.value: pick the option, as a click would
		for (const option of Array.from(el.querySelectorAll('option')) as any[]) {
			option.selected = option.getAttribute('value') === value || option.__value === value;
		}
	} else {
		el.value = value;
	}
	el.dispatchEvent(new (window as any).Event('input'));
	el.dispatchEvent(new (window as any).Event('change'));
};

describe('Schedules', () => {
	it('lists running jobs with their time in words, ended ones folded away', async () => {
		await mount();
		expect(target.querySelectorAll('[data-schedule-job]').length).toBe(2);
		expect(card('c5a0e24a8ec9').textContent).toContain('每周一 07:00');
		expect(card('c5a0e24a8ec9').textContent).toContain('weekly-cli-updates.sh');
		expect(card('c5a0e24a8ec9').textContent).toContain('发到 Telegram');
		expect(card('c5a0e24a8ec9').getAttribute('data-schedule-state')).toBe('scheduled');
		expect(card('aaaaaaaaaaaa').getAttribute('data-schedule-state')).toBe('paused');
		expect(card('aaaaaaaaaaaa').textContent).toContain('每 2 小时');
		expect(card('aaaaaaaaaaaa').querySelector('[data-schedule-toggle]').textContent.trim()).toBe('恢复');
		(target.querySelector('[data-schedule-show-ended]') as any).click();
		await sleep(10);
		expect(card('bbbbbbbbbbbb').textContent).toContain('已结束');
		expect(card('bbbbbbbbbbbb').querySelectorAll('[data-schedule-run]').length).toBe(0);
	});

	it('runs a job now and resumes a paused one', async () => {
		api.hermesJobAction.mockResolvedValue(JOBS[0]);
		await mount();
		card('c5a0e24a8ec9').querySelector('[data-schedule-run]').click();
		await until(() => api.hermesJobAction.mock.calls.length === 1);
		expect(api.hermesJobAction).toHaveBeenCalledWith('tok', 'c5a0e24a8ec9', 'run');
		card('aaaaaaaaaaaa').querySelector('[data-schedule-toggle]').click();
		await until(() => api.hermesJobAction.mock.calls.length === 2);
		expect(api.hermesJobAction.mock.calls[1]).toEqual(['tok', 'aaaaaaaaaaaa', 'resume']);
		await until(() => toast.success.mock.calls.length === 2);
		expect(toast.success.mock.calls[0][0]).toContain('已开始运行');
	});

	it('creates a job from the picker, delivered where the others go', async () => {
		api.createHermesJob.mockResolvedValue(JOBS[1]);
		await mount();
		(target.querySelector('[data-schedule-new]') as any).click();
		await until(() => !!target.querySelector('[data-schedule-form]'));
		setValue(target.querySelector('[data-schedule-name]'), '  工作日早报 ');
		setValue(target.querySelector('[data-schedule-prompt]'), '汇总 AI 新闻');
		setValue(target.querySelector('[data-schedule-frequency]'), 'weekdays');
		await sleep(10);
		setValue(target.querySelector('[data-schedule-time]'), '08:30');
		await sleep(10);
		expect(target.querySelector('[data-schedule-preview]').textContent).toContain('工作日 08:30');
		(target.querySelector('[data-schedule-form]') as any).dispatchEvent(
			new (window as any).Event('submit', { cancelable: true })
		);
		await until(() => api.createHermesJob.mock.calls.length === 1);
		expect(api.createHermesJob.mock.calls[0][1]).toEqual({
			name: '工作日早报',
			schedule: '30 8 * * 1-5',
			deliver: 'telegram:5231',
			prompt: '汇总 AI 新闻'
		});
		await until(() => !target.querySelector('[data-schedule-form]'));
	});

	it('edits a script job without sending a prompt', async () => {
		api.updateHermesJob.mockResolvedValue(JOBS[0]);
		await mount();
		card('c5a0e24a8ec9').querySelector('[data-schedule-edit]').click();
		await until(() => !!target.querySelector('[data-schedule-form]'));
		expect(target.querySelectorAll('[data-schedule-prompt]').length).toBe(0);
		const picked = Array.from(
			target.querySelectorAll('[data-schedule-frequency] option')
		).find((o: any) => o.selected) as any;
		expect(picked.textContent.trim()).toBe('每周');
		setValue(target.querySelector('[data-schedule-time]'), '06:00');
		await sleep(10);
		(target.querySelector('[data-schedule-form]') as any).dispatchEvent(
			new (window as any).Event('submit', { cancelable: true })
		);
		await until(() => api.updateHermesJob.mock.calls.length === 1);
		expect(api.updateHermesJob.mock.calls[0].slice(1)).toEqual([
			'c5a0e24a8ec9',
			{ name: '每周更新 CLI', schedule: '0 6 * * 1', deliver: 'telegram:5231' }
		]);
	});

	it('says why the list could not be read', async () => {
		api.listHermesJobs.mockRejectedValue('这个 Hermes 还不支持这项操作');
		const { writable } = await import('svelte/store');
		target = document.createElement('div');
		document.body.appendChild(target);
		app = new Page({ target, context: new Map([['i18n', writable({ t: (s: string) => s })]]) });
		await until(() => !!target.querySelector('[data-schedule-error]'));
		expect(target.querySelector('[data-schedule-error]').textContent).toContain('还不支持');
	});
});
