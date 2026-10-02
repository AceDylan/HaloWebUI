// 协作台 stage rail, mounted in a DOM: every stage says where the team is (计划 → 批准 → 执行 →
// 整理结果 → 验收), what is happening right now, how long it has taken and about how long is left.
import { afterEach, describe, expect, it } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const nowTs = () => Math.floor(Date.now() / 1000);

let app: any;
let target: any;

const mount = async (props: Record<string, unknown>) => {
	const { default: StageRail } = await import('./StageRail.svelte');
	target = document.createElement('div');
	document.body.appendChild(target);
	app = new StageRail({ target, props });
	await sleep(5);
	return app;
};

const steps = (active: number) =>
	['plan', 'approve', 'run', 'conclude', 'check'].map((key, i) => ({
		key,
		state: i < active ? 'done' : i === active ? 'active' : 'pending'
	}));

const text = (sel: string) => (target.querySelector(sel)?.textContent ?? '').replace(/\s+/g, ' ').trim();

afterEach(() => {
	app?.$destroy();
	app = null;
	target?.remove();
});

describe('StageRail', () => {
	it('planning: the lead’s current step, time spent and about how long is left', async () => {
		const at = nowTs();
		await mount({
			stage: {
				key: 'planning',
				label: '负责人制定计划',
				now: '负责人（gpt-chat）在理解目标、挑选成员、拆分带依赖的任务',
				started_at: at - 12,
				at,
				eta: { seconds: 33, high: 60, basis: '按本机最近 10 次做计划的用时估算' },
				steps: steps(0)
			}
		});
		const rail = target.querySelector('[data-stage]');
		expect(rail.getAttribute('data-stage')).toBe('planning');
		expect(rail.classList.contains('tm-live')).toBe(true);
		expect(target.querySelector('[data-step="plan"]').getAttribute('aria-current')).toBe('step');
		expect(target.querySelector('[data-step="run"]').getAttribute('data-state')).toBe('pending');
		expect(text('[data-stage-now]')).toContain('gpt-chat');
		expect(text('[data-stage-clock]')).toMatch(/^已用 1\ds · 预计还要约 1 分钟$/);
		expect(text('[data-stage-basis]')).toContain('本机最近 10 次');
	});

	it('running: each member at work, its time against what such tasks usually take', async () => {
		const at = nowTs();
		await mount({
			stage: {
				key: 'running',
				label: '成员执行中',
				now: '#T1 researcher：搜索 · 看板工具（另有 1 个成员在并行）',
				started_at: at - 200,
				at,
				eta: { seconds: 420, high: 600, basis: '按本机最近 8 次 hermes 调研任务的用时估算' },
				steps: steps(2),
				done: 1,
				total: 4,
				running: [
					{ key: 'T1', member: 'researcher', text: '搜索 · 看板工具', since: at - 150, typical: 500, typical_high: 600 },
					{ key: 'T2', member: 'writer', text: '写文件 · advice.md', since: at - 30, typical: 120 }
				]
			}
		});
		expect(text('[data-step="run"]')).toContain('执行1/4');
		expect(text('[data-stage-eta]')).toBe('预计还要约 7–10 分钟');
		const lines = target.querySelectorAll('[data-stage-lines] li');
		expect(lines.length).toBe(2);
		expect(lines[0].textContent).toContain('搜索 · 看板工具');
		expect(lines[0].textContent).toContain('通常 8–10 分钟');
		expect(text('[data-stage-basis]')).toContain('含整理结果和验收');
	});

	it('approval: no clock, but how long the plan takes once approved', async () => {
		await mount({
			stage: {
				key: 'approval',
				label: '等你批准',
				now: '计划好了：看一下成员和任务，批准后才开始执行',
				at: nowTs(),
				after_approval: { seconds: 540, high: 760, basis: '按本机最近 8 次 hermes 调研任务的用时估算' },
				steps: steps(1)
			}
		});
		const rail = target.querySelector('[data-stage]');
		expect(rail.classList.contains('tm-live')).toBe(false);
		expect(rail.getAttribute('data-tone')).toBe('waiting');
		expect(text('[data-stage-clock]')).toBe('批准后预计 约 9–13 分钟 出结果');
		expect(text('[data-stage-clock]')).not.toContain('已用');
	});

	it('a member needs you: says who and why, promises no time', async () => {
		await mount({
			stage: {
				key: 'attention',
				label: '需要你处理',
				now: '#T2 writer 停下来问你：要不要附上来源',
				at: nowTs(),
				steps: steps(2),
				done: 1,
				total: 3
			}
		});
		expect(target.querySelector('[data-stage]').getAttribute('data-tone')).toBe('attention');
		expect(text('[data-stage-now]')).toContain('停下来问你');
		expect(target.querySelector('[data-stage-clock]')).toBeFalsy();
	});

	it('writing the result past its usual time says so instead of counting below zero', async () => {
		const at = nowTs() - 400;
		await mount({
			stage: {
				key: 'concluding',
				label: '整理完整结果',
				now: '负责人（gpt-chat）在把 3 个任务的成果整合成完整结果',
				started_at: at,
				at,
				eta: { seconds: 40, high: 60 },
				steps: steps(3)
			}
		});
		expect(text('[data-stage-eta]')).toBe('比平时久一些，应该快好了');
	});
});
