// 派发方式「精答」/「讨论」 in a chat, mounted in a DOM: the card follows the run live (who answers,
// which round, who speaks), links to its page, and once the result is written points to it in the
// chat — or offers to put it there when it did not arrive.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

const answers = vi.hoisted(() => ({ getAnswer: vi.fn(), reportBackAnswer: vi.fn() }));
vi.mock('$lib/apis/answers', () => answers);
const discussions = vi.hoisted(() => ({ getDiscussion: vi.fn(), reportBackDiscussion: vi.fn() }));
vi.mock('$lib/apis/discussions', () => discussions);
vi.mock('svelte-sonner', () => ({ toast: { info: vi.fn(), error: vi.fn() } }));

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const until = async (check: () => boolean, label: string) => {
	const end = Date.now() + 15000;
	while (!check()) {
		if (Date.now() > end) throw new Error(`timed out waiting for ${label}`);
		await sleep(20);
	}
};

let app: any;
let target: any;

const mount = async (props: { kind: 'answer' | 'discuss'; chatId: string; history?: any }) => {
	const { default: ModeDispatchCard } = await import('./ModeDispatchCard.svelte');
	target = document.createElement('div');
	document.body.appendChild(target);
	(globalThis as any).localStorage.token = 'tok';
	app = new ModeDispatchCard({ target, props });
};
const text = (sel: string) =>
	(target.querySelector(sel)?.textContent ?? '').replace(/\s+/g, ' ').trim();
const state = () =>
	target.querySelector('[data-mode-dispatch-card]')?.getAttribute('data-mode-dispatch-state');

afterEach(() => {
	app?.$destroy();
	app = null;
	target?.remove();
	vi.clearAllMocks();
});

const run = (over: Record<string, unknown> = {}) => ({
	id: 'm-1',
	userMessageId: 'u-1',
	question: '押金多久退？',
	lang: 'zh',
	status: 'answering',
	planner: { model: 'gpt-chat', name: 'gpt-chat' },
	webAllowed: true,
	plan: { status: 'done', action: 'create' },
	assistant: { id: 'law', name: '合同审查', emoji: '⚖️', action: 'create', saved: true },
	research: null,
	answer: { status: 'streaming', content: '一般在退租后 30 天内', startedAt: Date.now() },
	startedAt: Date.now(),
	origin: { chatId: 'chat-1', messageId: 'r1' },
	...over
});

describe('ModeDispatchCard', () => {
	it('精答: the assistant at work and its answer as it comes, then where the answer is in the chat', async () => {
		const responses = [
			{
				id: 'run-1',
				run: run({ status: 'routing', assistant: null, answer: { status: 'waiting', content: '' } })
			},
			{ id: 'run-1', run: run() },
			{
				id: 'run-1',
				run: run({
					status: 'done',
					startedAt: Date.now() - 42000,
					endedAt: Date.now(),
					answer: { status: 'done', content: '30 天' }
				})
			}
		];
		answers.getAnswer.mockImplementation(async () => responses.shift() ?? responses[0]);
		const history = { messages: {} as Record<string, any> };
		await mount({ kind: 'answer', chatId: 'run-1', history });
		await until(() => state() === 'routing', 'the dispatcher at work');
		expect(text('[data-mode-dispatch-line]')).toContain('gpt-chat 在从助手库挑最合适的助手');
		// one card with the steps, a halo on it while it works
		const steps = () =>
			[...target.querySelectorAll('[data-step]')].map(
				(li: any) => `${li.getAttribute('data-step')}:${li.getAttribute('data-state')}`
			);
		expect(steps()).toEqual(['pick:active', 'answer:pending', 'report:pending']);
		expect(target.querySelector('[data-mode-dispatch-stage]').className).toContain('tm-live');
		expect(text('[data-mode-dispatch-stage-label]')).toBe('挑助手');
		expect(text('[data-mode-dispatch-clock]')).toMatch(/^已用 \d+s$/);
		expect(target.querySelector('[data-mode-dispatch-open]').getAttribute('href')).toBe(
			'/answer/run-1'
		);
		expect(answers.getAnswer.mock.calls[0].slice(1)).toEqual(['run-1']);

		await until(() => state() === 'answering', 'the answer streaming');
		expect(text('[data-mode-dispatch-line]')).toContain('合同审查 在回答');
		expect(text('[data-mode-dispatch-preview]')).toContain('一般在退租后 30 天内');
		expect(text('[data-mode-dispatch-facts]')).toBe('精答 · ⚖️合同审查');
		expect(steps()).toEqual(['pick:done', 'answer:active', 'report:pending']);

		await until(() => state() === 'done', 'the answer written');
		// just finished: on its way into the chat
		expect(text('[data-mode-dispatch-done]')).toContain('正在发回这个对话');
		app.$set({
			history: {
				messages: {
					n1: {
						id: 'n1',
						role: 'user',
						childrenIds: ['a1'],
						hermes_notice: { source: 'answer', run_id: 'answer:run-1:m-1' }
					}
				}
			}
		});
		await until(() => !!target.querySelector('[data-mode-dispatch-jump]'), 'the way to the answer');
		expect(text('[data-mode-dispatch-done]')).toContain('已发回这个对话');
		expect(text('[data-mode-dispatch-line]')).toContain('新建了「合同审查」');
		expect(steps()).toEqual(['pick:done', 'answer:done', 'report:done']);
		expect(target.querySelector('[data-mode-dispatch-stage]').className).not.toContain('tm-live');
		expect(text('[data-mode-dispatch-stage-label]')).toBe('已发回');
		expect(text('[data-mode-dispatch-clock]')).toBe('用时 42s');
	});

	it('精答 that never arrived: one click puts it into the chat', async () => {
		answers.getAnswer.mockResolvedValue({
			id: 'run-2',
			run: run({ status: 'done', endedAt: Date.now() - 600000 })
		});
		answers.reportBackAnswer.mockResolvedValue({
			chat_id: 'chat-1',
			posted: true,
			duplicate: false
		});
		await mount({ kind: 'answer', chatId: 'run-2', history: { messages: {} } });
		await until(() => !!target.querySelector('[data-mode-dispatch-bring]'), 'the bring button');
		target.querySelector('[data-mode-dispatch-bring]').click();
		await until(() => answers.reportBackAnswer.mock.calls.length === 1, 'report back');
		expect(answers.reportBackAnswer.mock.calls[0].slice(1)).toEqual(['run-2']);
	});

	it('精答 that stopped: the step it stopped at, why, and the way to retry it', async () => {
		answers.getAnswer.mockResolvedValue({
			id: 'run-3',
			run: run({
				status: 'error',
				error: '上游超时',
				plan: { status: 'done', action: 'create', webSearch: true },
				research: { status: 'done', queries: ['押金'], sources: [{ n: 1, url: 'https://a.cn' }] },
				answer: { status: 'error', content: '' },
				endedAt: Date.now()
			})
		});
		await mount({ kind: 'answer', chatId: 'run-3', history: { messages: {} } });
		await until(() => state() === 'error', 'the failed run');
		expect(
			[...target.querySelectorAll('[data-step]')].map(
				(li: any) => `${li.getAttribute('data-step')}:${li.getAttribute('data-state')}`
			)
		).toEqual(['pick:done', 'research:done', 'answer:failed', 'report:pending']);
		expect(text('[data-mode-dispatch-line]')).toBe('上游超时');
		expect(text('[data-mode-dispatch-stage-label]')).toBe('出错');
		expect(text('[data-mode-dispatch-failure]')).toContain('到精答页可以从停下的地方接着来');
		expect(text('[data-mode-dispatch-open]')).toBe('去重试');
		expect(text('[data-mode-dispatch-facts]')).toBe('精答 · ⚖️合同审查 · 1 个来源');
		expect(target.querySelector('[data-mode-dispatch-done]')).toBeFalsy();
	});

	it('讨论: the table, the round and who speaks; deleted on its page, a quiet line', async () => {
		const seats = [
			{ id: 's1', model: 'a', name: 'a', label: 'a', role: '' },
			{ id: 's2', model: 'b', name: 'b', label: 'b', role: '' }
		];
		discussions.getDiscussion.mockResolvedValue({
			id: 'room-1',
			asks: [
				{
					id: 'm-1',
					question: '该用哪个库？',
					mode: 'roundtable',
					rounds: 2,
					round: 1,
					status: 'running',
					seats,
					turns: [
						{ id: 'r1-s1', round: 1, seat: 's1', status: 'done', content: 'x' },
						{ id: 'r1-s2', round: 1, seat: 's2', status: 'streaming', content: 'y' }
					],
					conclusion: { status: 'waiting', content: '', model: 'c', name: 'c' },
					origin: { chatId: 'chat-1', messageId: 'r1' }
				}
			]
		});
		await mount({ kind: 'discuss', chatId: 'room-1', history: { messages: {} } });
		await until(() => state() === 'running', 'the discussion');
		expect(text('[data-mode-dispatch-facts]')).toBe('讨论台 · 圆桌讨论 · 2 个模型 · 2 轮');
		expect(text('[data-mode-dispatch-line]')).toBe('b 在发言');
		expect(
			[...target.querySelectorAll('[data-step]')].map(
				(li: any) => `${li.getAttribute('data-step')}:${li.getAttribute('data-state')}`
			)
		).toEqual(['talk:active', 'conclude:pending', 'report:pending']);
		expect(text('[data-step="talk"]')).toBe('讨论 1/2');
		// each seat and what it is doing, the moderator last
		expect(
			[...target.querySelectorAll('[data-mode-dispatch-seats] li')].map((li: any) => [
				li.getAttribute('data-state'),
				li.textContent.replace(/\s+/g, ' ').trim()
			])
		).toEqual([
			['done', 'a 第 1 轮已发言'],
			['streaming', 'b 发言中'],
			['waiting', 'c 主持']
		]);
		expect(target.querySelector('[data-mode-dispatch-open]').getAttribute('href')).toBe(
			'/discuss/room-1'
		);
		expect(target.querySelectorAll('.dc-ring')).toHaveLength(2);
		app.$destroy();
		target.remove();

		discussions.getDiscussion.mockRejectedValue(
			Object.assign(new Error('讨论不存在'), { status: 404 })
		);
		await mount({ kind: 'discuss', chatId: 'room-1', history: { messages: {} } });
		await until(() => state() === 'gone', 'gone');
		expect(text('[data-mode-dispatch-gone]')).toContain('这个讨论已经删除了');
	});
});
