import { describe, expect, it } from 'vitest';

import { getModelChatDisplayName, getModelDisplayParts } from './model-display';

describe('getModelChatDisplayName', () => {
	it('shows function pipe models with the connection suffix', () => {
		expect(
			getModelChatDisplayName({
				id: 'official_pipe.model_id_1',
				name: 'model_1',
				connection_name: 'Official Pipe'
			})
		).toBe('model_1 | Official Pipe');
	});
});

describe('getModelDisplayParts', () => {
	it('separates the base name from the connection tag', () => {
		expect(
			getModelDisplayParts({ id: 'a.b', name: 'gpt-4o | Proxy A', connection_name: 'Proxy A' })
		).toEqual({ base: 'gpt-4o', connection: 'Proxy A', full: 'gpt-4o | Proxy A' });
	});

	it('has no tag without a connection and falls back to the connection as the base', () => {
		expect(getModelDisplayParts({ id: 'm', name: 'Local' })).toEqual({
			base: 'Local',
			connection: null,
			full: 'Local'
		});
		expect(getModelDisplayParts({ id: 'm', name: '', connection_name: 'Only' })).toEqual({
			base: 'Only',
			connection: null,
			full: 'Only'
		});
		expect(getModelDisplayParts(null)).toEqual({ base: '', connection: null, full: '' });
	});
});
