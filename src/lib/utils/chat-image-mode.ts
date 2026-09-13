// Decides when a chat is "drawing" rather than talking, so the composer can
// offer image-studio prompt templates instead of the workspace chat prompts.
//
// Two signals, matching what Chat.svelte sends upstream as `image_generation`:
// the composer's image toggle, or a single selected model that is itself a
// dedicated image model (also when it is a workspace preset wrapping one).

import { isDedicatedImageGenerationModel } from './model-capabilities';
import { getModelCleanId, parseModelSelectionId } from './model-identity';

// Structural on purpose: the chat passes `Model` objects whose `info` is typed
// tightly elsewhere, and only these fields matter here.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ChatModelLike = { id?: string; [key: string]: any };

const bareModelId = (candidate: unknown): string => {
	const raw = `${candidate ?? ''}`.trim();
	return parseModelSelectionId(raw)?.modelId ?? raw;
};

/**
 * True when the selected chat model draws pictures itself. Workspace presets
 * are resolved through their base model, and `modelref::` selection ids and
 * the legacy `<connection>.<model>` prefix are stripped before matching.
 */
export const isDedicatedImageGenerationChatModel = (
	model: ChatModelLike | null | undefined
): boolean => {
	if (!model || typeof model !== 'object') {
		return false;
	}
	const candidates = [
		getModelCleanId(model),
		model.info?.base_model_id,
		model.info?.meta?.base_selection_id,
		model.id
	].map(bareModelId);
	return candidates.some((candidate) => candidate && isDedicatedImageGenerationModel(candidate));
};

/** The composer is in image mode: the image toggle is on or the model itself generates images. */
export const isChatImageMode = (
	imageGenerationEnabled: boolean,
	model: ChatModelLike | null | undefined
): boolean => Boolean(imageGenerationEnabled) || isDedicatedImageGenerationChatModel(model);
