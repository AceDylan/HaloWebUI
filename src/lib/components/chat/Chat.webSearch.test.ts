import { readFileSync } from 'node:fs';
import { parse, preprocess } from 'svelte/compiler';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import { beforeAll, describe, expect, it } from 'vitest';

import {
	getModelWebSearchPreference,
	resolveModelBuiltinWebSearchState
} from '$lib/utils/model-web-search-preference';
import {
	buildWebSearchModeOptions,
	resolveConfiguredDefaultWebSearchMode
} from '$lib/utils/native-web-search';
import { normalizeWebSearchMode } from '$lib/utils/web-search-mode';

// Runs the real web search helpers out of Chat.svelte (the composer's mode for the
// current selection, and the mode a request is sent with) against a fake component
// state. Same technique as Chat.initNewChat.test.ts.

let code: string;
let sourceOf: (name: string) => string;

beforeAll(async () => {
	const filename = process.env.HALO_CHAT_COMPONENT_SOURCE ?? 'src/lib/components/chat/Chat.svelte';
	({ code } = await preprocess(readFileSync(filename, 'utf8'), vitePreprocess(), { filename }));
	const ast = parse(code);
	const declarations = ast.instance!.content.body.flatMap((node: any) => node.declarations ?? []);
	sourceOf = (name) => {
		const declaration = declarations.find((node: any) => node.id.name === name);
		if (!declaration) {
			throw new Error(`Chat.svelte no longer declares ${name}`);
		}
		return code.slice(declaration.init.start, declaration.init.end);
	};
});

const GPT_CHAT = {
	id: 'modelref::openai::personal::id:13c104eb::gpt-chat',
	name: 'gpt-chat',
	model_id: 'gpt-chat',
	owned_by: 'openai',
	model_ref: { provider: 'openai', source: 'personal', connection_id: '13c104eb' }
};
const HERMES_AGENT = {
	id: 'modelref::openai::personal::id:ee5e02db::hermes-agent',
	name: 'hermes-agent',
	model_id: 'hermes-agent',
	owned_by: 'openai',
	model_ref: { provider: 'openai', source: 'personal', connection_id: 'ee5e02db' }
};
const MODELS = [GPT_CHAT, HERMES_AGENT];

// The production web search settings: HaloWebUI search (tavily) and native search on,
// new chats defaulting to HaloWebUI search.
const chat = (selectedModelIds: string[], overrides: Record<string, any> = {}) => {
	const context: Record<string, any> = {
		$config: {
			features: {
				enable_halo_web_search: true,
				enable_native_web_search: true,
				default_web_search_mode: 'halo'
			},
			hermes_agent_model_ids: ['hermes-agent']
		},
		$user: { role: 'admin' },
		i18n: {},
		get: () => ({ t: (key: string) => key }),
		selectedModelIds,
		webSearchMode: 'off',
		getModelById: (id: string) => MODELS.find((model) => model.id === id),
		buildWebSearchModeOptions,
		resolveConfiguredDefaultWebSearchMode,
		resolveModelBuiltinWebSearchState,
		getModelWebSearchPreference,
		normalizeWebSearchMode,
		...overrides
	};
	for (const name of [
		'getResolvedSelectedModelIds',
		'getResolvedSelectedWebSearchModels',
		'pickModelDefaultWebSearchMode',
		'isChatWebSearchFeatureEnabled',
		'canUseChatWebSearch',
		'getPreferredDefaultWebSearchMode',
		'getSelectionDrivenWebSearchState',
		'getRequestWebSearchMode'
	]) {
		context[name] = new Function('context', `with (context) { return ${sourceOf(name)}; }`)(
			context
		);
	}
	return context;
};

describe('web search defaults per model', () => {
	it('starts other models on HaloWebUI search', () => {
		expect(chat([GPT_CHAT.id]).getSelectionDrivenWebSearchState()).toEqual({
			mode: 'halo',
			source: 'default'
		});
	});

	it('keeps hermes-agent off, alone or next to another model', () => {
		expect(chat([HERMES_AGENT.id]).getSelectionDrivenWebSearchState()).toEqual({
			mode: 'off',
			source: 'model'
		});
		expect(chat([GPT_CHAT.id, HERMES_AGENT.id]).getSelectionDrivenWebSearchState()).toEqual({
			mode: 'off',
			source: 'model'
		});
	});

	it('follows the hermes model ids the server lists', () => {
		const state = chat([HERMES_AGENT.id], {
			$config: {
				features: {
					enable_halo_web_search: true,
					enable_native_web_search: true,
					default_web_search_mode: 'halo'
				},
				hermes_agent_model_ids: ['another-agent']
			}
		}).getSelectionDrivenWebSearchState();
		expect(state).toEqual({ mode: 'halo', source: 'default' });
	});
});

describe('the web search mode a request carries', () => {
	it('is the composer mode for other models', () => {
		expect(chat([GPT_CHAT.id], { webSearchMode: 'halo' }).getRequestWebSearchMode(GPT_CHAT)).toBe(
			'halo'
		);
	});

	it('is off for hermes-agent even when the composer still shows a mode', () => {
		expect(
			chat([HERMES_AGENT.id], { webSearchMode: 'halo' }).getRequestWebSearchMode(HERMES_AGENT)
		).toBe('off');
	});

	it('is off when the user may not search the web', () => {
		expect(
			chat([GPT_CHAT.id], {
				webSearchMode: 'halo',
				$user: { role: 'user', permissions: { features: { web_search: false } } }
			}).getRequestWebSearchMode(GPT_CHAT)
		).toBe('off');
	});
});
