import type { Model } from '$lib/stores';
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

/**
 * The model's explicit ENABLE_WEB_SEARCH_TOOL, else off for hermes agent
 * models (hermes searches with its own tools), else no preference.
 */
export const getModelWebSearchPreference = (
	model: Model | Record<string, any> | null | undefined,
	hermesModelIds?: readonly string[] | null
): boolean | null =>
	getModelBuiltinWebSearchPreference(model) ??
	(isHermesAgentModel(model as any, hermesModelIds) ? false : null);

export const resolveModelBuiltinWebSearchState = (
	selectedModels: (Model | Record<string, any>)[],
	fallbackMode: WebSearchMode,
	pickEnabledMode: (selectedModels: Model[]) => WebSearchMode,
	hermesModelIds?: readonly string[] | null
): ModelWebSearchState => {
	if (selectedModels.length === 0) {
		return { mode: fallbackMode, source: 'default' };
	}

	const preferences = selectedModels.map((model) =>
		getModelWebSearchPreference(model, hermesModelIds)
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
