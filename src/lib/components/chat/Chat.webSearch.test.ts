import { readFileSync } from 'node:fs';
import { compile, parse, preprocess } from 'svelte/compiler';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import { beforeAll, describe, expect, it, vi } from 'vitest';

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

let filename: string;
let code: string;
let sourceOf: (name: string) => string;

beforeAll(async () => {
	filename = process.env.HALO_CHAT_COMPONENT_SOURCE ?? 'src/lib/components/chat/Chat.svelte';
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

// The production web search settings: HaloWebUI search and native search on,
// new chats defaulting to Smart Web Search.
const chat = (selectedModelIds: string[], overrides: Record<string, any> = {}) => {
	const context: Record<string, any> = {
		$config: {
			features: {
				enable_halo_web_search: true,
				enable_native_web_search: true,
				default_web_search_mode: 'auto'
			},
			hermes_agent_model_ids: ['hermes-agent']
		},
		$user: { role: 'admin' },
		i18n: {},
		get: () => ({ t: (key: string) => key }),
		selectedModelIds,
		webSearchMode: 'off',
		webSearchModeSource: 'default',
		webSearchSelectionSyncReady: true,
		webSearchStateBeforeModelOff: null,
		persistChatComposerState: vi.fn(),
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
		'getRequestWebSearchMode',
		'syncWebSearchModeWithSelection'
	]) {
		context[name] = new Function('context', `with (context) { return ${sourceOf(name)}; }`)(
			context
		);
	}
	return context;
};

describe('web search defaults per model', () => {
	it('starts other models on Smart Web Search', () => {
		expect(chat([GPT_CHAT.id]).getSelectionDrivenWebSearchState()).toEqual({
			mode: 'auto',
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
					default_web_search_mode: 'auto'
				},
				hermes_agent_model_ids: ['another-agent']
			}
		}).getSelectionDrivenWebSearchState();
		expect(state).toEqual({ mode: 'auto', source: 'default' });
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

describe('switching models', () => {
	const composer = (state: Record<string, any>) => ({
		mode: state.webSearchMode,
		source: state.webSearchModeSource
	});
	const select = (state: Record<string, any>, ids: string[]) => {
		state.selectedModelIds = ids;
		state.syncWebSearchModeWithSelection();
		return composer(state);
	};

	// The bug 757c3a4 shipped with: the block that applies these states named none of
	// the selection, so Svelte never re-ran it when the user picked another model.
	it('re-runs the composer sync when the selection, the model list or the config changes', () => {
		const { js } = compile(code, { filename, generate: 'dom' });
		const update = js.code.slice(js.code.indexOf('$$self.$$.update = () =>'));
		const call = update.search(/^\s*syncWebSearchModeWithSelection\(\);$/m);
		expect(call).toBeGreaterThan(-1);
		const guard = update
			.slice(update.lastIndexOf('if ($$self.$$.dirty', call), call)
			.split('\n')[0];
		const dependencies = [...guard.matchAll(/\/\*([^*]*)\*\//g)].flatMap(([, names]) =>
			names.split(',').map((name) => name.trim())
		);
		expect(dependencies).toEqual(
			expect.arrayContaining([
				'selectedModelIds',
				'modelsMap',
				'$config',
				'$user',
				'webSearchSelectionSyncReady',
				'webSearchMode',
				'webSearchModeSource'
			])
		);
	});

	it('turns Smart Web Search on when leaving hermes-agent for another model', () => {
		const state = chat([HERMES_AGENT.id], { webSearchMode: 'auto' });
		expect(select(state, [HERMES_AGENT.id])).toEqual({ mode: 'off', source: 'model' });
		expect(select(state, [GPT_CHAT.id])).toEqual({ mode: 'auto', source: 'default' });
		expect(select(state, [HERMES_AGENT.id])).toEqual({ mode: 'off', source: 'model' });
		expect(state.persistChatComposerState).toHaveBeenCalledTimes(3);
	});

	it('keeps what the user picked across other models', () => {
		const state = chat([GPT_CHAT.id], { webSearchMode: 'off', webSearchModeSource: 'user' });
		expect(select(state, [GPT_CHAT.id])).toEqual({ mode: 'off', source: 'user' });
		expect(select(state, [])).toEqual({ mode: 'off', source: 'user' });
		expect(state.persistChatComposerState).not.toHaveBeenCalled();
	});

	it('brings the user pick back after hermes-agent switched it off', () => {
		for (const mode of ['off', 'native']) {
			const state = chat([GPT_CHAT.id], { webSearchMode: mode, webSearchModeSource: 'user' });
			expect(select(state, [HERMES_AGENT.id])).toEqual({ mode: 'off', source: 'model' });
			expect(select(state, [GPT_CHAT.id, HERMES_AGENT.id])).toEqual({
				mode: 'off',
				source: 'model'
			});
			expect(select(state, [GPT_CHAT.id])).toEqual({ mode, source: 'user' });
			expect(state.webSearchStateBeforeModelOff).toBe(null);
		}
	});

	it('does not let the user turn it on for hermes-agent', () => {
		const state = chat([HERMES_AGENT.id], { webSearchMode: 'halo', webSearchModeSource: 'user' });
		expect(select(state, [HERMES_AGENT.id])).toEqual({ mode: 'off', source: 'model' });
	});

	it('waits for the chat to be ready and for the selected models to load', () => {
		const loading = chat([HERMES_AGENT.id], {
			webSearchMode: 'halo',
			webSearchSelectionSyncReady: false
		});
		expect(select(loading, [HERMES_AGENT.id])).toEqual({ mode: 'halo', source: 'default' });

		const modelsPending = chat([HERMES_AGENT.id], {
			webSearchMode: 'halo',
			getModelById: () => undefined
		});
		expect(select(modelsPending, [HERMES_AGENT.id])).toEqual({ mode: 'halo', source: 'default' });
	});
});
