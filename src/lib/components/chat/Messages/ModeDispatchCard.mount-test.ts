// 派发方式「精答」/「讨论」 in a chat, mounted in a DOM: the card follows the run live (who answers,
// which round, who speaks), links to its page, and once the result is written points to it in the
// chat — or offers to put it there when it did not arrive.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

const answers = vi.hoisted(() => ({
	getAnswer: vi.fn(),
	reportBackAnswer: vi.fn(),
	retryAnswer: vi.fn(),
	stopAnswer: vi.fn()
}));
vi.mock('$lib/apis/answers', () => answers);
const discussions = vi.hoisted(() => ({
	getDiscussion: vi.fn(),
	reportBackDiscussion: vi.fn(),
	resumeDiscussion: vi.fn(),
	stopDiscussion: vi.fn(),
	concludeDiscussion: vi.fn()
}));
vi.mock('$lib/apis/discussions', () => discussions);
vi.mock('svelte-sonner', () => ({ toast: { info: vi.fn(), error: vi.fn(), success: vi.fn() } }));

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
		expect(text('[data-mode-dispatch-done]')).toContain('结果已生成，正在同步到对话');
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

	it('精答 written, its picture still being drawn: a 配图 step, then on its way with the picture', async () => {
		const written = { status: 'done', endedAt: Date.now() - 30000, answer: { status: 'done', content: '30 天' } };
		const responses = [
			{
				id: 'run-3',
				run: run({
					...written,
					illustration: { status: 'generating', step: 'draw', template: '手绘万能图', startedAt: Date.now() - 12000 }
				})
			},
			{
				id: 'run-3',
				run: run({
					...written,
					illustration: { status: 'ready', url: '/api/v1/files/p1/content', startedAt: Date.now() - 12000, endedAt: Date.now() }
				})
			}
		];
		answers.getAnswer.mockImplementation(async () => responses.shift() ?? responses[0]);
		await mount({ kind: 'answer', chatId: 'run-3', history: { messages: {} } });
		await until(() => !!target.querySelector('[data-step="picture"]'), 'the picture step');
		const steps = () =>
			[...target.querySelectorAll('[data-step]')].map(
				(li: any) => `${li.getAttribute('data-step')}:${li.getAttribute('data-state')}`
			);
		// not finished yet: a halo, 配图中, and the report waits for the picture
		expect(steps()).toEqual(['pick:done', 'answer:done', 'picture:active', 'report:pending']);
		expect(text('[data-mode-dispatch-stage-label]')).toBe('配图中');
		expect(text('[data-mode-dispatch-line]')).toContain('正在配图 · 「手绘万能图」· 在画图');
		expect(text('[data-mode-dispatch-clock]')).toMatch(/^配图已用 1\ds$/);
		expect(target.querySelector('[data-mode-dispatch-stage]').className).toContain('tm-live');
		expect(target.querySelector('[data-mode-dispatch-drawing]')).toBeTruthy();
		expect(target.querySelector('[data-mode-dispatch-bring]')).toBeFalsy();
		expect(text('[data-mode-dispatch-card] .shrink-0')).toContain('配图中');

		// drawn: on its way into the chat, counted from the picture (the text ended 30s ago)
		await until(() => steps().includes('picture:done'), 'the picture drawn');
		expect(steps()).toEqual(['pick:done', 'answer:done', 'picture:done', 'report:active']);
		expect(text('[data-mode-dispatch-stage-label]')).toBe('发回中');
		expect(text('[data-mode-dispatch-done]')).toContain('结果已生成，正在同步到对话');
	}, 30000);

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

	it('精答 that stopped: the step it stopped at, why, and picks it up again in place', async () => {
		answers.retryAnswer.mockResolvedValue({});
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
		expect(text('[data-mode-dispatch-failure]')).toContain('结果照样发回这个对话');
		expect(text('[data-mode-dispatch-open]')).toBe('打开精答 ↗');
		expect(text('[data-mode-dispatch-facts]')).toBe('精答 · ⚖️合同审查 · 1 个来源');
		expect(target.querySelector('[data-mode-dispatch-done]')).toBeFalsy();
		expect(target.querySelector('[data-mode-dispatch-conclude]')).toBeFalsy();
		target.querySelector('[data-mode-dispatch-resume]').click();
		await until(() => answers.retryAnswer.mock.calls.length === 1, 'retry in place');
		expect(answers.retryAnswer.mock.calls[0].slice(1)).toEqual(['run-3']);
	});

	it('精答 at work stops from the card', async () => {
		answers.stopAnswer.mockResolvedValue({});
		answers.getAnswer.mockResolvedValue({
			id: 'run-4',
			run: run({ status: 'answering', answer: { status: 'streaming', content: '先看合同' } })
		});
		await mount({ kind: 'answer', chatId: 'run-4', history: { messages: {} } });
		await until(() => !!target.querySelector('[data-mode-dispatch-stop]'), 'the stop button');
		expect(text('[data-mode-dispatch-open]')).toBe('在精答看 ↗');
		target.querySelector('[data-mode-dispatch-stop]').click();
		await until(() => answers.stopAnswer.mock.calls.length === 1, 'stop');
		expect(answers.stopAnswer.mock.calls[0].slice(1)).toEqual(['run-4']);
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

	it('讨论 that stopped: resumes or concludes from the card, unless the room moved on', async () => {
		const seats = [{ id: 's1', model: 'a', name: 'a', label: 'a', role: '' }];
		const stopped = {
			id: 'm-1',
			question: '该用哪个库？',
			mode: 'roundtable',
			rounds: 2,
			round: 1,
			status: 'stopped',
			seats,
			turns: [{ id: 'r1-s1', round: 1, seat: 's1', status: 'done', content: 'x' }],
			conclusion: { status: 'waiting', content: '', model: 'c', name: 'c' },
			origin: { chatId: 'chat-1', messageId: 'r1' }
		};
		discussions.getDiscussion.mockResolvedValue({ id: 'room-2', asks: [stopped] });
		discussions.concludeDiscussion.mockResolvedValue({});
		await mount({ kind: 'discuss', chatId: 'room-2', history: { messages: {} } });
		await until(() => state() === 'stopped', 'the stopped discussion');
		expect(target.querySelector('[data-mode-dispatch-resume]')).toBeTruthy();
		target.querySelector('[data-mode-dispatch-conclude]').click();
		await until(() => discussions.concludeDiscussion.mock.calls.length === 1, 'conclude');
		expect(discussions.concludeDiscussion.mock.calls[0].slice(1)).toEqual(['room-2']);
		app.$destroy();
		target.remove();

		discussions.getDiscussion.mockResolvedValue({
			id: 'room-2',
			asks: [stopped, { ...stopped, id: 'm-2', question: '那性能呢？', origin: undefined }]
		});
		await mount({ kind: 'discuss', chatId: 'room-2', history: { messages: {} } });
		await until(() => state() === 'stopped', 'the stopped discussion');
		expect(target.querySelector('[data-mode-dispatch-resume]')).toBeFalsy();
		expect(text('[data-mode-dispatch-failure]')).toContain('到讨论台接着处理');
	});
});


it('shows a persisted delivery receipt even before local history has synchronized', async () => {
    answers.getAnswer.mockResolvedValue({ run: run({ status: 'done', endedAt: Date.now() - 60000 }),
        report: { run_id: 'm-1', message_id: 'delivered-reply', chat_id: 'chat-1' } });
    await mount({ kind: 'answer', chatId: 'run-1', history: { messages: {} } });
    await until(() => !!target.querySelector('[data-mode-dispatch-jump]'), 'delivery receipt');
    expect(target.querySelector('[data-mode-dispatch-bring]')).toBeFalsy();
    expect(target.textContent).toContain('已发回');
});
