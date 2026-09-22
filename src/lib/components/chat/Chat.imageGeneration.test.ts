import { readFileSync } from 'node:fs';
import { compile, parse, preprocess } from 'svelte/compiler';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import { beforeAll, describe, expect, it, vi } from 'vitest';

import { isChatImageMode, isDedicatedImageGenerationChatModel } from '$lib/utils/chat-image-mode';
import { getModelSelectionId } from '$lib/utils/model-identity';

// Runs the real image generation helpers out of Chat.svelte (the image toggle a
// selected model switches on or off, and whether a request asks for an image)
// against a fake component state. Same technique as Chat.webSearch.test.ts.

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

const modelRef = (name: string, connection: string) => ({
	id: `modelref::openai::personal::id:${connection}::${name}`,
	name,
	model_id: name,
	original_id: name,
	owned_by: 'openai',
	model_ref: { provider: 'openai', source: 'personal', connection_id: connection }
});
const GPT_IMAGE = modelRef('gpt-image', 'c153e2d2');
const SEEDREAM = modelRef('seedream-4', 'c153e2d2');
const GPT_CHAT = modelRef('gpt-chat', '13c104eb');
const MODELS = [GPT_IMAGE, SEEDREAM, GPT_CHAT];

const chat = (selectedModelIds: string[], overrides: Record<string, any> = {}) => {
	const context: Record<string, any> = {
		$config: { features: { enable_image_generation: true } },
		$user: { role: 'admin' },
		selectedModelIds,
		imageGenerationEnabled: false,
		imageGenerationOptions: {},
		lastAutoImageGenerationSelectionKey: '',
		composerStateSyncReady: true,
		persistChatComposerState: vi.fn(),
		getModelById: (id: string) => MODELS.find((model) => model.id === id),
		getModelRequestId: (model: any) => getModelSelectionId(model) || model.id,
		isDedicatedImageGenerationChatModel,
		...overrides
	};
	for (const name of [
		'getResolvedSelectedModelIds',
		'getSingleSelectedReasoningModel',
		'getSingleSelectedDedicatedImageModel',
		'canUseChatImageGeneration',
		'isImageGenerationActiveForRequest',
		'syncImageGenerationForDedicatedModel'
	]) {
		context[name] = new Function('context', `with (context) { return ${sourceOf(name)}; }`)(
			context
		);
	}
	return context;
};

// What MessageInput shows for this state: the image chip and its settings button
// (`imageGenerationEnabled`), and whether the quick commands offer image templates.
const composer = (state: Record<string, any>) => ({
	imageGenerationEnabled: state.imageGenerationEnabled,
	imagePromptTemplates: isChatImageMode(
		state.imageGenerationEnabled,
		state.getSingleSelectedReasoningModel()
	),
	imageRequest: state.isImageGenerationActiveForRequest()
});
const IMAGE_ON = { imageGenerationEnabled: true, imagePromptTemplates: true, imageRequest: true };
const IMAGE_OFF = {
	imageGenerationEnabled: false,
	imagePromptTemplates: false,
	imageRequest: false
};

const select = (state: Record<string, any>, ids: string[]) => {
	state.selectedModelIds = ids;
	state.syncImageGenerationForDedicatedModel();
	return composer(state);
};

describe('switching between image and chat models', () => {
	it('re-runs the image sync when the selection, the model list or the config changes', () => {
		const { js } = compile(code, { filename, generate: 'dom' });
		const update = js.code.slice(js.code.indexOf('$$self.$$.update = () =>'));
		const call = update.search(/^\s*syncImageGenerationForDedicatedModel\(\);$/m);
		expect(call).toBeGreaterThan(-1);
		const guard = update
			.slice(update.lastIndexOf('if ($$self.$$.dirty', call), call)
			.split('\n')[0];
		const dependencies = [...guard.matchAll(/\/\*([^*]*)\*\//g)].flatMap(([, names]) =>
			names.split(',').map((name) => name.trim())
		);
		expect(dependencies).toEqual(
			expect.arrayContaining(['selectedModelIds', 'modelsMap', '$config', '$user'])
		);
	});

	it('shows the image menus for an image model', () => {
		const state = chat([]);
		expect(select(state, [GPT_IMAGE.id])).toEqual(IMAGE_ON);
	});

	it('takes the image menus away when switching to a chat model', () => {
		const state = chat([]);
		select(state, [GPT_IMAGE.id]);
		expect(select(state, [GPT_CHAT.id])).toEqual(IMAGE_OFF);
		expect(state.persistChatComposerState).toHaveBeenCalledTimes(1);
	});

	it('brings them back, with the chosen options, when switching back', () => {
		const state = chat([]);
		select(state, [GPT_IMAGE.id]);
		state.imageGenerationOptions = { aspect_ratio: '16:9', n: 2 };
		select(state, [GPT_CHAT.id]);
		expect(select(state, [GPT_IMAGE.id])).toEqual(IMAGE_ON);
		expect(state.imageGenerationOptions).toEqual({ aspect_ratio: '16:9', n: 2 });
		expect(select(state, [GPT_CHAT.id])).toEqual(IMAGE_OFF);
	});

	it('keeps them on across image models', () => {
		const state = chat([]);
		select(state, [GPT_IMAGE.id]);
		expect(select(state, [SEEDREAM.id])).toEqual(IMAGE_ON);
		expect(state.persistChatComposerState).not.toHaveBeenCalled();
	});

	it('takes them away when a chat model joins the image model or the selection is cleared', () => {
		const multi = chat([]);
		select(multi, [GPT_IMAGE.id]);
		expect(select(multi, [GPT_IMAGE.id, GPT_CHAT.id]).imageGenerationEnabled).toBe(false);

		const cleared = chat([]);
		select(cleared, [GPT_IMAGE.id]);
		expect(select(cleared, ['']).imageGenerationEnabled).toBe(false);
	});

	it('leaves image generation the user turned on for a chat model alone', () => {
		const state = chat([GPT_CHAT.id], { imageGenerationEnabled: true });
		expect(select(state, [GPT_CHAT.id]).imageGenerationEnabled).toBe(true);
		expect(select(state, [modelRef('another-chat', '13c104eb').id]).imageGenerationEnabled).toBe(
			true
		);
		expect(state.persistChatComposerState).not.toHaveBeenCalled();
	});

	it('does not touch the toggle a chat being opened restores', () => {
		const state = chat([]);
		select(state, [GPT_IMAGE.id]);
		// loadChat / initNewChat: the composer is not ready while the other chat's
		// models and its own image toggle come in.
		state.composerStateSyncReady = false;
		state.imageGenerationEnabled = true;
		expect(select(state, [GPT_CHAT.id]).imageGenerationEnabled).toBe(true);
		state.composerStateSyncReady = true;
		expect(select(state, [GPT_CHAT.id]).imageGenerationEnabled).toBe(true);
		expect(state.persistChatComposerState).not.toHaveBeenCalled();
	});
});
