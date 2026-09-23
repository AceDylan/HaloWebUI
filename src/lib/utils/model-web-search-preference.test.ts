import { describe, expect, it } from 'vitest';

import {
	getModelBuiltinWebSearchPreference,
	getModelWebSearchPreference,
	resolveModelBuiltinWebSearchState
} from './model-web-search-preference';

const GPT_CHAT = {
	id: 'modelref::openai::personal::id:13c104eb::gpt-chat',
	model_id: 'gpt-chat'
};
const HERMES_AGENT = {
	id: 'modelref::openai::personal::id:ee5e02db::hermes-agent',
	model_id: 'hermes-agent'
};

describe('model builtin web search preference', () => {
	it('reads explicit preferences from model meta and info meta', () => {
		expect(
			getModelBuiltinWebSearchPreference({
				meta: { builtin_tool_config: { ENABLE_WEB_SEARCH_TOOL: false } }
			})
		).toBe(false);
		expect(
			getModelBuiltinWebSearchPreference({
				info: { meta: { builtin_tool_config: { ENABLE_WEB_SEARCH_TOOL: true } } }
			})
		).toBe(true);
		expect(getModelBuiltinWebSearchPreference({ meta: {} })).toBe(null);
	});

	it('lets a single model explicitly disable web search', () => {
		expect(
			resolveModelBuiltinWebSearchState(
				[{ meta: { builtin_tool_config: { ENABLE_WEB_SEARCH_TOOL: false } } }],
				'native',
				() => 'native'
			)
		).toEqual({ mode: 'off', source: 'model' });
	});

	it('lets any selected model explicitly disable web search', () => {
		expect(
			resolveModelBuiltinWebSearchState(
				[
					{ meta: { builtin_tool_config: { ENABLE_WEB_SEARCH_TOOL: true } } },
					{ info: { meta: { builtin_tool_config: { ENABLE_WEB_SEARCH_TOOL: false } } } }
				],
				'halo',
				() => 'auto'
			)
		).toEqual({ mode: 'off', source: 'model' });
	});

	it('uses the enabled mode picker when a model explicitly enables web search', () => {
		expect(
			resolveModelBuiltinWebSearchState(
				[{ info: { meta: { builtin_tool_config: { ENABLE_WEB_SEARCH_TOOL: true } } } }],
				'off',
				() => 'auto'
			)
		).toEqual({ mode: 'auto', source: 'model' });
	});

	it('keeps hermes agent models off and other models on the default mode', () => {
		expect(resolveModelBuiltinWebSearchState([HERMES_AGENT], 'halo', () => 'auto')).toEqual({
			mode: 'off',
			source: 'model'
		});
		expect(resolveModelBuiltinWebSearchState([GPT_CHAT], 'halo', () => 'auto')).toEqual({
			mode: 'halo',
			source: 'default'
		});
		expect(
			resolveModelBuiltinWebSearchState([GPT_CHAT, HERMES_AGENT], 'halo', () => 'auto')
		).toEqual({ mode: 'off', source: 'model' });
	});

	it('matches hermes against the configured id list', () => {
		const myAgent = {
			id: 'modelref::openai::personal::id:ee5e02db::my-agent',
			model_id: 'my-agent'
		};
		expect(
			resolveModelBuiltinWebSearchState([myAgent], 'halo', () => 'auto', ['my-agent'])
		).toEqual({ mode: 'off', source: 'model' });
		expect(
			resolveModelBuiltinWebSearchState([HERMES_AGENT], 'halo', () => 'auto', ['my-agent'])
		).toEqual({ mode: 'halo', source: 'default' });
	});

	it('lets a hermes model turn web search on through its own settings', () => {
		const hermesWithSearch = {
			...HERMES_AGENT,
			info: { meta: { builtin_tool_config: { ENABLE_WEB_SEARCH_TOOL: true } } }
		};
		expect(getModelWebSearchPreference(hermesWithSearch)).toBe(true);
		expect(getModelWebSearchPreference(HERMES_AGENT)).toBe(false);
		expect(getModelWebSearchPreference(GPT_CHAT)).toBe(null);
		expect(resolveModelBuiltinWebSearchState([hermesWithSearch], 'halo', () => 'auto')).toEqual({
			mode: 'auto',
			source: 'model'
		});
	});

	it('offers Halo Smart Search to Hermes without overriding an explicit model opt-out', () => {
		expect(getModelWebSearchPreference(HERMES_AGENT, undefined, 'smart_search')).toBe(null);
		expect(
			resolveModelBuiltinWebSearchState(
				[HERMES_AGENT],
				'halo',
				() => 'auto',
				undefined,
				'smart_search'
			)
		).toEqual({ mode: 'halo', source: 'default' });
		expect(
			getModelWebSearchPreference(
				{ ...HERMES_AGENT, meta: { builtin_tool_config: { ENABLE_WEB_SEARCH_TOOL: false } } },
				undefined,
				'smart_search'
			)
		).toBe(false);
	});
});
