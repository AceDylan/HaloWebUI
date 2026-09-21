import { describe, expect, it } from 'vitest';

import {
	resolveAvailableChatModelSelectionValues,
	resolveChatModelSelection
} from './chat-model-recovery';

// A chat model and an agent model on two different connections, shaped like the
// entries /api/models returns.
const GPT_CHAT = {
	id: 'modelref::openai::personal::id:13c104eb::gpt-chat',
	name: 'gpt-chat',
	model_id: 'gpt-chat',
	model_ref: { provider: 'openai', source: 'personal', connection_id: '13c104eb' }
};
const HERMES_AGENT = {
	id: 'modelref::openai::personal::id:ee5e02db::hermes-agent',
	name: 'hermes-agent',
	model_id: 'hermes-agent',
	model_ref: { provider: 'openai', source: 'personal', connection_id: 'ee5e02db' }
};

describe('resolveAvailableChatModelSelectionValues', () => {
	it('drops stale persisted model ids instead of preserving unavailable selections', () => {
		const result = resolveAvailableChatModelSelectionValues(
			[
				{
					id: 'pipe_a.model_id_1',
					name: 'model_1',
					selection_id: 'modelref::pipe::function::id:pipe_a::model_id_1',
					model_id: 'model_id_1',
					model_ref: {
						provider: 'pipe',
						source: 'function',
						connection_id: 'pipe_a'
					}
				}
			],
			['modelref::pipe::function::id:old_pipe::model_id_1', 'pipe_a.model_id_1']
		);

		expect(result.values).toEqual(['modelref::pipe::function::id:pipe_a::model_id_1']);
		expect(result.droppedUnavailable).toBe(true);
		expect(result.resolutions.map((resolution) => resolution.status)).toEqual([
			'stale',
			'resolved'
		]);
	});
});

describe('a model named in the URL (?models=)', () => {
	it('resolves a bare name to the connection it is served from', () => {
		// The Bookmark Hub may send `models=gpt-chat` rather than the full
		// selection id; one model of that name means one unambiguous answer.
		const resolution = resolveChatModelSelection([GPT_CHAT, HERMES_AGENT], 'gpt-chat');

		expect(resolution.status).toBe('resolved');
		expect(resolution.value).toBe('modelref::openai::personal::id:13c104eb::gpt-chat');
	});

	it('resolves the connection-qualified id as itself', () => {
		const resolution = resolveChatModelSelection(
			[GPT_CHAT, HERMES_AGENT],
			'modelref::openai::personal::id:13c104eb::gpt-chat'
		);

		expect(resolution.status).toBe('resolved');
		expect(resolution.value).toBe('modelref::openai::personal::id:13c104eb::gpt-chat');
		expect(resolution.model).toBe(GPT_CHAT);
	});

	it('calls a bare name ambiguous when two connections serve it', () => {
		// Why a deployment that serves one model from several connections should send
		// the full `modelref::…` id instead of the bare name.
		const other = {
			...GPT_CHAT,
			id: 'modelref::openai::personal::id:c153e2d2::gpt-chat',
			model_ref: { provider: 'openai', source: 'personal', connection_id: 'c153e2d2' }
		};
		expect(resolveChatModelSelection([GPT_CHAT, other], 'gpt-chat').status).toBe('ambiguous');
	});

	it('is stale while the model list is still empty — which is why ?q= has to wait for it', () => {
		// The bug behind "模型连接不可用，请重新选择模型" on a question sent from the
		// Hub: the landing page auto-submitted before /api/models came back, and
		// every selection — the account default included — resolves to `stale`
		// against an empty list. Chat.svelte now awaits the list before submitting.
		for (const value of [
			'gpt-chat',
			'modelref::openai::personal::id:13c104eb::gpt-chat',
			'modelref::openai::personal::id:ee5e02db::hermes-agent'
		]) {
			expect(resolveChatModelSelection([], value).status).not.toBe('resolved');
		}

		const empty = resolveAvailableChatModelSelectionValues([], ['gpt-chat']);
		expect(empty.values).toEqual([]);
		expect(empty.droppedUnavailable).toBe(true);
	});

	it('leaves every other selection alone', () => {
		// Naming a model for one question must not disturb the account default:
		// resolution is per value, nothing global is written here.
		const result = resolveAvailableChatModelSelectionValues(
			[GPT_CHAT, HERMES_AGENT],
			['gpt-chat', 'modelref::openai::personal::id:ee5e02db::hermes-agent']
		);

		expect(result.values).toEqual([
			'modelref::openai::personal::id:13c104eb::gpt-chat',
			'modelref::openai::personal::id:ee5e02db::hermes-agent'
		]);
		expect(result.droppedUnavailable).toBe(false);
	});
});
