import { describe, expect, it } from 'vitest';
import { getUpstreamModelId, isHermesAgentModelId } from './hermes';

describe('isHermesAgentModelId', () => {
	it('matches the bare id, the selection id and the legacy prefixed id', () => {
		expect(isHermesAgentModelId('hermes-agent')).toBe(true);
		expect(isHermesAgentModelId('modelref::openai::personal::id:ee5e02db::hermes-agent')).toBe(
			true
		);
		expect(isHermesAgentModelId('ee5e02db.hermes-agent')).toBe(true);
	});

	it('rejects other models and empty values', () => {
		expect(isHermesAgentModelId('modelref::openai::personal::id:13c104eb::gpt-chat')).toBe(false);
		expect(isHermesAgentModelId('gpt-image')).toBe(false);
		expect(isHermesAgentModelId('')).toBe(false);
		expect(isHermesAgentModelId(undefined)).toBe(false);
	});

	it('honours the configured id list and falls back to the default when it is empty', () => {
		expect(isHermesAgentModelId('my-agent', ['my-agent'])).toBe(true);
		expect(isHermesAgentModelId('hermes-agent', ['my-agent'])).toBe(false);
		expect(isHermesAgentModelId('hermes-agent', [])).toBe(true);
	});

	it('extracts the upstream id from a selection id', () => {
		expect(getUpstreamModelId('modelref::openai::personal::id:ee5e02db::hermes-agent')).toBe(
			'hermes-agent'
		);
		expect(getUpstreamModelId('plain')).toBe('plain');
	});
});
