import type { Model } from '$lib/stores';
import { chatModelIdCandidates, isGptImageChatModel } from './chat-image-mode';
import { isHermesAgentModel } from './hermes';
import type { WebSearchMode, WebSearchModeSource } from './web-search-mode';

export type ModelWebSearchState = {
	mode: WebSearchMode;
	source: WebSearchModeSource;
};

export const getModelBuiltinWebSearchPreference = (
	model: Model | Record<string, any> | null | undefined
): boolean | null => {
	const value =
		(model as any)?.info?.meta?.builtin_tool_config?.ENABLE_WEB_SEARCH_TOOL ??
		(model as any)?.meta?.builtin_tool_config?.ENABLE_WEB_SEARCH_TOOL;

	return typeof value === 'boolean' ? value : null;
};

// Jev (TypeSafe) judges the message itself: search results would only bury the
// material it is asked to judge. Matches jev-latest, 94dae559.jev-latest, typesafe/jev-1.14.
const isJevChatModel = (model: unknown): boolean =>
	chatModelIdCandidates(model as any).some((id) => /(?:^|[/.])jev(?:$|[-_.:@])/i.test(id));

/**
 * The model's explicit ENABLE_WEB_SEARCH_TOOL takes precedence. gpt-image only
 * draws and Jev only judges, so neither searches. Hermes uses its own tools
 * unless Smart Search is selected for Halo's shared search path.
 */
export const getModelWebSearchPreference = (
	model: Model | Record<string, any> | null | undefined,
	hermesModelIds?: readonly string[] | null,
	webSearchEngine?: string | null
): boolean | null =>
	getModelBuiltinWebSearchPreference(model) ??
	(isGptImageChatModel(model as any) ||
	isJevChatModel(model) ||
	(isHermesAgentModel(model as any, hermesModelIds) && webSearchEngine !== 'smart_search')
		? false
		: null);

export const resolveModelBuiltinWebSearchState = (
	selectedModels: (Model | Record<string, any>)[],
	fallbackMode: WebSearchMode,
	pickEnabledMode: (selectedModels: Model[]) => WebSearchMode,
	hermesModelIds?: readonly string[] | null,
	webSearchEngine?: string | null
): ModelWebSearchState => {
	if (selectedModels.length === 0) {
		return { mode: fallbackMode, source: 'default' };
	}

	const preferences = selectedModels.map((model) =>
		getModelWebSearchPreference(model, hermesModelIds, webSearchEngine)
	);
	if (preferences.some((value) => value === false)) {
		return { mode: 'off', source: 'model' };
	}

	if (preferences.some((value) => value === true)) {
		return {
			mode: pickEnabledMode(selectedModels as Model[]),
			source: 'model'
		};
	}

	return { mode: fallbackMode, source: 'default' };
};
