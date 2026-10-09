import { describe, it, expect } from 'vitest';
import { branchAnswers, chatAnswers, comparisonPair, type CompareHistory } from './branch-compare';

const history = (): CompareHistory => ({
	currentId: 'a3',
	messages: {
		u1: {
			id: 'u1',
			role: 'user',
			parentId: null,
			childrenIds: ['a1', 'a2', 'missing'],
			content: '原问题'
		},
		a1: { id: 'a1', role: 'assistant', parentId: 'u1', content: '原回答', childrenIds: ['u3'] },
		a2: { id: 'a2', role: 'assistant', parentId: 'u1', content: '另一个模型的回答' },
		u2: { id: 'u2', role: 'user', parentId: null, childrenIds: ['a3'], content: '编辑后的问题' },
		a3: {
			id: 'a3',
			role: 'assistant',
			parentId: 'u2',
			content: '讨论结果',
			discussion: { enabled: true }
		},
		u3: { id: 'u3', role: 'user', parentId: 'a1', childrenIds: ['a4'], content: '后续问题' },
		a4: { id: 'a4', role: 'assistant', parentId: 'u3', content: '后续回答' }
	}
});

describe('branch comparison', () => {
	it('compares reanswers and edited questions with their own prompts, without changing selection', () => {
		const h = history();
		const before = JSON.stringify(h);
		const answers = branchAnswers(h, 'a3');
		expect(answers.map((a) => [a.message.id, a.prompt?.content])).toEqual([
			['a1', '原问题'],
			['a2', '原问题'],
			['a3', '编辑后的问题']
		]);
		expect(comparisonPair(answers, 'a3')).toEqual(['a3', 'a1']);
		expect(comparisonPair(answers, 'u2')).toEqual(['a3', 'a1']);
		expect(JSON.stringify(h)).toBe(before);
	});
	it('offers returned precision answers and discussion conclusions from other turns', () => {
		const h = history();
		h.messages.notice = {
			id: 'notice',
			role: 'user',
			parentId: 'a4',
			content: '精答结果通知',
			childrenIds: ['result']
		};
		h.messages.result = {
			id: 'result',
			role: 'assistant',
			parentId: 'notice',
			content: '精答结论'
		};
		const candidates = chatAnswers(h);
		expect(candidates.find((a) => a.message.id === 'result')?.prompt?.content).toBe('精答结果通知');
		expect(candidates.find((a) => a.message.id === 'a3')?.message.content).toBe('讨论结果');
	});

	it('limits later-turn comparisons to sibling questions and tolerates missing branches', () => {
		const h = history();
		expect(branchAnswers(h, 'a4').map((a) => a.message.id)).toEqual(['a4']);
		expect(branchAnswers(h, 'missing')).toEqual([]);
		h.messages.a1.childrenIds?.push('u4');
		h.messages.u4 = { id: 'u4', role: 'user', parentId: 'a1', childrenIds: ['a5', 'a5', 'a2'] };
		h.messages.a5 = { id: 'a5', role: 'assistant', parentId: 'u4', content: '编辑后续问题的回答' };
		expect(branchAnswers(h, 'u4').map((a) => a.message.id)).toEqual(['a4', 'a5']);
	});
});
