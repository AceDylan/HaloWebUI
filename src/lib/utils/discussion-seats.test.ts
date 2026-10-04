import { describe, expect, it } from 'vitest';

import { canJoinDiscussion, discussionSeatModels, tickModel } from './discussion-seats';

const hermesIds = ['hermes-agent'];
const models = [
	{ id: 'a.gpt-chat', name: 'gpt-chat' },
	{ id: 'h.hermes-agent', original_id: 'hermes-agent', name: 'hermes-agent' },
	{ id: 'a.gpt-image', name: 'gpt-image' },
	{ id: 'b.deepseek-chat', name: 'deepseek-chat' },
	{ id: 'x.secret', name: 'secret', info: { meta: { hidden: true } } },
	{ id: 'arena-model', owned_by: 'arena' },
	{ id: 'c.qwen-vl-vision', name: 'vision reader' }
];

describe('canJoinDiscussion', () => {
	it('keeps text models and leaves out Hermes, image, hidden and arena models', () => {
		expect(discussionSeatModels(models, hermesIds).map((m) => m.id)).toEqual([
			'a.gpt-chat',
			'b.deepseek-chat',
			'c.qwen-vl-vision'
		]);
	});

	it('refuses an empty entry', () => {
		expect(canJoinDiscussion(null, hermesIds)).toBe(false);
		expect(canJoinDiscussion({}, hermesIds)).toBe(false);
	});
});

describe('tickModel', () => {
	it('starts a discussion on the second tick', () => {
		expect(tickModel(['gpt'], 'deepseek')).toEqual({ picked: [], discuss: ['gpt', 'deepseek'] });
	});
	it('collects the first tick and unticks', () => {
		expect(tickModel([], 'gpt')).toEqual({ picked: ['gpt'], discuss: null });
		expect(tickModel(['gpt'], 'gpt')).toEqual({ picked: [], discuss: null });
	});
});
