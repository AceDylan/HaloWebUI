import { describe, expect, it } from 'vitest';

import { modelDeck, modelDeckKind } from './model-deck';

const model = (name: string, extra: Record<string, any> = {}) => ({
	id: `c1.${name}`,
	name,
	owned_by: 'openai',
	selection_id: `modelref::openai::personal::id:c1::${name}`,
	...extra
});

const ids = (models: { name: string }[]) => models.map((m) => m.name);

describe('modelDeck', () => {
	const models = [
		model('gpt-chat'),
		model('deepseek-chat'),
		model('gpt-image'),
		model('hermes-agent'),
		model('gemini-chat'),
		model('claude-chat'),
		model('answer-1', { info: { meta: { hidden: true } } }),
		model('arena', { owned_by: 'arena' })
	];

	it('keeps visible models in menu order, pinned first in pin order', () => {
		const pinned = [
			'modelref::openai::personal::id:c1::hermes-agent',
			'modelref::openai::personal::id:c1::claude-chat'
		];
		expect(ids(modelDeck(models, pinned))).toEqual([
			'hermes-agent',
			'claude-chat',
			'gpt-chat',
			'deepseek-chat',
			'gpt-image',
			'gemini-chat'
		]);
	});

	it('ignores stale pins and caps the deck', () => {
		expect(ids(modelDeck(models, ['gone'], 3))).toEqual(['gpt-chat', 'deepseek-chat', 'gpt-image']);
	});

	it('has nothing to offer with one model or none', () => {
		expect(modelDeck([model('gpt-chat')])).toEqual([]);
		expect(modelDeck(undefined)).toEqual([]);
	});
});

describe('modelDeckKind', () => {
	it('tells the agent, the image model and chat models apart', () => {
		expect(modelDeckKind(model('hermes-agent', { original_id: 'hermes-agent' }), ['hermes-agent'])).toBe(
			'agent'
		);
		expect(modelDeckKind(model('gpt-image', { model_id: 'gpt-image' }))).toBe('image');
		expect(modelDeckKind(model('claude-chat', { model_id: 'claude-chat' }))).toBe('chat');
	});
});
