import { describe, expect, it } from 'vitest';
import { getUpstreamModelId, isHermesAgentModelId, isHermesRunSteerable } from './hermes';

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

describe('isHermesRunSteerable', () => {
	const running = { role: 'assistant', done: false, model: 'ee5e02db.hermes-agent' };

	it('offers to steer an unfinished hermes reply', () => {
		expect(isHermesRunSteerable(running)).toBe(true);
		expect(
			isHermesRunSteerable({ role: 'assistant', done: false }, undefined, 'hermes-agent')
		).toBe(true);
	});

	it('stops once the backend says the run ended, even though the message still streams', () => {
		expect(isHermesRunSteerable({ ...running, hermesRun: { active: false } })).toBe(false);
		expect(
			isHermesRunSteerable({ ...running, hermesRun: { active: false, reason: 'steer_rejected' } })
		).toBe(false);
		expect(isHermesRunSteerable({ ...running, hermesRun: { active: true } })).toBe(true);
	});

	it('never offers to steer a finished reply, a user message or another model', () => {
		expect(isHermesRunSteerable({ ...running, done: true })).toBe(false);
		expect(isHermesRunSteerable({ ...running, role: 'user' })).toBe(false);
		expect(isHermesRunSteerable({ ...running, model: 'gpt-chat' })).toBe(false);
		expect(isHermesRunSteerable(null)).toBe(false);
	});
});
