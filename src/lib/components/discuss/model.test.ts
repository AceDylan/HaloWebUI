import { describe, expect, it } from 'vitest';

import type { DiscussAsk } from '$lib/apis/discussions';
import {
	applyEvent,
	conclusionAnswer,
	discussionMarkdown,
	modelById,
	modeSpec,
	parseSections,
	roundsOf,
	sectionKind,
	tokens
} from './model';

const ask = (over: Partial<DiscussAsk> = {}): DiscussAsk => ({
	id: 'm1',
	userMessageId: 'u1',
	question: '用哪个数据库？',
	lang: 'zh',
	mode: 'roundtable',
	rounds: 2,
	seats: [
		{ id: 's1', model: 'a', name: 'a', label: 'a', role: '' },
		{ id: 's2', model: 'b', name: 'b', label: 'b', role: '怀疑派' }
	],
	moderator: { model: 'c', name: 'c' },
	status: 'running',
	round: 1,
	turns: [
		{ id: 'r1-s2', round: 1, seat: 's2', status: 'streaming', content: '' },
		{ id: 'r1-s1', round: 1, seat: 's1', status: 'streaming', content: 'Post' }
	],
	interjections: [],
	conclusion: { status: 'waiting', content: '', model: 'c', name: 'c' },
	previousConclusions: [],
	startedAt: 1,
	usage: {},
	...over
});

describe('applyEvent', () => {
	it('appends text at the offset it was sent for', () => {
		const { asks, stale } = applyEvent([ask()], {
			kind: 'delta',
			chatId: 'c',
			askId: 'm1',
			v: 2,
			parts: [
				{ t: 'r1-s1', o: 4, x: 'gres' },
				{ t: 'r1-s2', o: 0, x: '不' }
			]
		});
		expect(stale).toBe(false);
		expect(asks[0].turns.find((t) => t.id === 'r1-s1')!.content).toBe('Postgres');
		expect(asks[0].turns.find((t) => t.id === 'r1-s2')!.content).toBe('不');
	});

	it('rewrites from an earlier offset and flags a gap as stale', () => {
		const rewritten = applyEvent([ask()], { kind: 'delta', chatId: 'c', askId: 'm1', v: 2, parts: [{ t: 'r1-s1', o: 0, x: 'My' }] });
		expect(rewritten.asks[0].turns[1].content).toBe('My');
		const gap = applyEvent([ask()], { kind: 'delta', chatId: 'c', askId: 'm1', v: 2, parts: [{ t: 'r1-s1', o: 9, x: 'x' }] });
		expect(gap.stale).toBe(true);
		expect(gap.asks[0].turns[1].content).toBe('Post');
	});

	it('does not mutate the asks it was given', () => {
		const before = [ask()];
		applyEvent(before, { kind: 'delta', chatId: 'c', askId: 'm1', v: 2, parts: [{ t: 'r1-s1', o: 4, x: '!' }] });
		expect(before[0].turns[1].content).toBe('Post');
	});

	it('streams the conclusion and takes turn results and the end status', () => {
		let asks = [ask({ status: 'concluding' })];
		asks = applyEvent(asks, { kind: 'delta', chatId: 'c', askId: 'm1', v: 3, parts: [{ t: 'conclusion', o: 0, x: '## 结论' }] }).asks;
		expect(asks[0].conclusion.content).toBe('## 结论');
		expect(asks[0].conclusion.status).toBe('streaming');
		asks = applyEvent(asks, {
			kind: 'turn',
			chatId: 'c',
			askId: 'm1',
			v: 4,
			turn: { id: 'r1-s2', status: 'error', error: 'quota', content: '' }
		}).asks;
		expect(asks[0].turns[0]).toMatchObject({ status: 'error', error: 'quota' });
		asks = applyEvent(asks, { kind: 'end', chatId: 'c', askId: 'm1', v: 5, status: 'done' }).asks;
		expect(asks[0].status).toBe('done');
	});

	it('takes whole states and adds asks it has not seen', () => {
		const second = ask({ id: 'm2', question: '那备份呢？' });
		const { asks } = applyEvent([ask()], { kind: 'state', chatId: 'c', askId: 'm2', v: 1, ask: second });
		expect(asks.map((a) => a.id)).toEqual(['m1', 'm2']);
		const unknown = applyEvent([ask()], { kind: 'delta', chatId: 'c', askId: 'zz', v: 1, parts: [] });
		expect(unknown.stale).toBe(true);
	});
});

describe('conclusions', () => {
	const content = '## 结论\n用 **Postgres**。\n\n## 共识\n- 备份\n\n## 分歧\n- 是否分库\n## 各方立场\n- **a** — 支持\n## 下一步\n- 压测';

	it('splits sections and knows their kinds', () => {
		const sections = parseSections(content);
		expect(sections.map((s) => s.title)).toEqual(['结论', '共识', '分歧', '各方立场', '下一步']);
		expect(sections.map((s, i) => sectionKind(s.title, i))).toEqual(['answer', 'agree', 'disagree', 'positions', 'next']);
		expect(sectionKind('Disagreements', 2)).toBe('disagree');
		expect(sectionKind('随便', 0)).toBe('answer');
		expect(conclusionAnswer(content)).toBe('用 **Postgres**。');
		expect(conclusionAnswer('没有标题')).toBe('没有标题');
	});
});

describe('helpers', () => {
	it('orders rounds and seats, names rounds by format', () => {
		const rounds = roundsOf(ask());
		expect(rounds).toHaveLength(1);
		expect(rounds[0].turns.map((t) => t.seat)).toEqual(['s1', 's2']);
		expect(modeSpec('debate').roundName(1, 3)).toBe('立论');
		expect(modeSpec('debate').roundName(3, 3)).toBe('总结陈词');
		expect(modeSpec('nope').value).toBe('roundtable');
	});

	it('finds models by selection id or id and formats tokens', () => {
		const models = [{ id: 'x.gpt', selection_id: 'modelref::gpt' }];
		expect(modelById(models, 'modelref::gpt')?.id).toBe('x.gpt');
		expect(modelById(models, 'x.gpt')?.id).toBe('x.gpt');
		expect(tokens(950)).toBe('950');
		expect(tokens(12345)).toBe('12k');
		expect(tokens(1500)).toBe('1.5k');
	});

	it('exports a whole discussion as Markdown', () => {
		const done = ask({
			status: 'done',
			turns: [
				{ id: 'r1-s1', round: 1, seat: 's1', status: 'done', content: '用 Postgres' },
				{ id: 'r1-s2', round: 1, seat: 's2', status: 'error', content: '', error: 'quota' }
			],
			conclusion: { status: 'done', content: '## 结论\n好', model: 'c', name: 'c' }
		});
		const md = discussionMarkdown('数据库', [done]);
		expect(md).toContain('# 数据库');
		expect(md).toContain('### 第 1 轮 · 各自作答');
		expect(md).toContain('**a**\n\n用 Postgres');
		expect(md).toContain('（未能发言：quota）');
		expect(md).toContain('### 主持人结论（c）');
		expect(md).toContain('b（怀疑派）');
	});
});
