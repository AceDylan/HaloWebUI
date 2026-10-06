import { describe, expect, it } from 'vitest';

import type { AnswerRun } from '$lib/apis/answers';
import { actionSentence, answerContext, applyEvent, isLive, stagesOf } from './model';

const run = (over: Partial<AnswerRun> = {}): AnswerRun => ({
	id: 'm1',
	userMessageId: 'u1',
	question: '押金条款有什么风险？',
	lang: 'zh',
	status: 'routing',
	planner: { model: 'conn.gpt-chat', name: 'gpt-chat' },
	webAllowed: true,
	plan: { status: 'running', startedAt: 1 },
	assistant: null,
	research: null,
	answer: { status: 'waiting', content: '' },
	startedAt: 1,
	...over
});

describe('stagesOf', () => {
	it('starts with the dispatcher reading the library', () => {
		const stages = stagesOf(run());
		expect(stages.map((s) => [s.key, s.state])).toEqual([
			['route', 'active'],
			['assistant', 'waiting'],
			['answer', 'waiting']
		]);
		expect(stages[0].note).toContain('gpt-chat');
	});

	it('names what was done to the assistant and shows the web step only when planned', () => {
		const going = run({
			status: 'researching',
			plan: { status: 'done', action: 'create', webSearch: true },
			assistant: { id: 'a1', name: '合同审查', action: 'create', saved: true },
			research: { status: 'running', queries: [], sources: [] }
		});
		expect(stagesOf(going).map((s) => [s.key, s.state, s.label])).toEqual([
			['route', 'done', '理解问题'],
			['assistant', 'done', '新建助手'],
			['research', 'active', '联网查资料'],
			['answer', 'waiting', '作答']
		]);
		const done = run({
			status: 'done',
			plan: { status: 'done', action: 'update', webSearch: true },
			assistant: { id: 'a1', name: '合同审查', action: 'update', saved: true },
			research: { status: 'done', queries: [], sources: [{ n: 1, title: 'x', url: 'https://x', excerpt: '' }] },
			answer: { status: 'done', content: '答' }
		});
		const stages = stagesOf(done);
		expect(stages[1].label).toBe('升级助手');
		expect(stages[2].note).toBe('1 个来源');
		expect(stages[3].state).toBe('done');
	});

	it('marks the steps a stopped run never reached as skipped', () => {
		const stopped = run({ status: 'stopped', plan: { status: 'stopped' } });
		expect(stagesOf(stopped).map((s) => s.state)).toEqual(['stopped', 'skipped', 'skipped']);
		const failed = run({
			status: 'error',
			plan: { status: 'error', action: 'direct' },
			assistant: { id: 'p', name: 'gpt-chat', action: 'direct', saved: true },
			answer: { status: 'error', content: '', startedAt: 2, error: 'boom' }
		});
		expect(stagesOf(failed).map((s) => s.state)).toEqual(['error', 'done', 'error']);
		expect(isLive('answering')).toBe(true);
		expect(isLive('interrupted')).toBe(false);
	});
});

describe('applyEvent', () => {
	it('appends deltas at their offset and asks for a reload when it fell behind', () => {
		let current = run({ status: 'answering', answer: { status: 'streaming', content: '' } });
		current = applyEvent(current, { kind: 'delta', chatId: 'c', runId: 'm1', offset: 0, text: '押金' }).run!;
		current = applyEvent(current, { kind: 'delta', chatId: 'c', runId: 'm1', offset: 2, text: '要写清' }).run!;
		expect(current.answer.content).toBe('押金要写清');
		// a replay from the start replaces
		current = applyEvent(current, { kind: 'delta', chatId: 'c', runId: 'm1', offset: 0, text: '重来' }).run!;
		expect(current.answer.content).toBe('重来');
		expect(applyEvent(current, { kind: 'delta', chatId: 'c', runId: 'm1', offset: 9, text: 'x' }).stale).toBe(true);
		expect(applyEvent(null, { kind: 'delta', chatId: 'c', offset: 0, text: 'x' }).stale).toBe(true);
	});

	it('takes whole states, answer flags and the end', () => {
		const next = run({ status: 'answering' });
		expect(applyEvent(run(), { kind: 'state', chatId: 'c', run: next }).run).toBe(next);
		const thinking = applyEvent(next, { kind: 'answer', chatId: 'c', runId: 'm1', answer: { thinking: true } }).run!;
		expect(thinking.answer.thinking).toBe(true);
		expect(applyEvent(thinking, { kind: 'end', chatId: 'c', runId: 'm1', status: 'done' }).run!.status).toBe('done');
		// another run's events change nothing
		expect(applyEvent(next, { kind: 'end', chatId: 'c', runId: 'other', status: 'done' }).run!.status).toBe('answering');
	});
});

describe('texts', () => {
	it('says what happened and hands the answer on with its sources', () => {
		expect(actionSentence('create', '合同审查')).toBe('新建了「合同审查」');
		expect(actionSentence('direct', 'gpt-chat')).toBe('由 gpt-chat 直接回答');
		const done = run({
			assistant: { id: 'a1', name: '合同审查', action: 'use', saved: true },
			research: { status: 'done', queries: [], sources: [{ n: 1, title: '押金规定', url: 'https://law.example', excerpt: '' }] },
			answer: { status: 'done', content: '要写清退还期限 [1]' }
		});
		expect(answerContext(done)).toBe('问题：押金条款有什么风险？\n\n「合同审查」的回答：\n要写清退还期限 [1]\n\n资料：\n[1] 押金规定 https://law.example');
	});
});
