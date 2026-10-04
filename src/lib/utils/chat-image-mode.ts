// Decides when a chat is "drawing" rather than talking, so the composer can
// offer image-studio prompt templates instead of the workspace chat prompts.
//
// Two signals, matching what Chat.svelte sends upstream as `image_generation`:
// the composer's image toggle, or a single selected model that is itself a
// dedicated image model (also when it is a workspace preset wrapping one).

import { isDedicatedImageGenerationModel } from './model-capabilities';
import { getModelCleanId, getModelSelectionId, parseModelSelectionId } from './model-identity';

// Structural on purpose: the chat passes `Model` objects whose `info` is typed
// tightly elsewhere, and only these fields matter here.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ChatModelLike = { id?: string; [key: string]: any };

const bareModelId = (candidate: unknown): string => {
	const raw = `${candidate ?? ''}`.trim();
	return parseModelSelectionId(raw)?.modelId ?? raw;
};

// The ids a chat model may be known by: its own, and the base model a
// workspace preset wraps.
const chatModelIdCandidates = (model: ChatModelLike | null | undefined): string[] =>
	model && typeof model === 'object'
		? [
				getModelCleanId(model),
				model.info?.base_model_id,
				model.info?.meta?.base_selection_id,
				model.id
			]
				.map(bareModelId)
				.filter(Boolean)
		: [];

/**
 * True when the selected chat model draws pictures itself. Workspace presets
 * are resolved through their base model, and `modelref::` selection ids and
 * the legacy `<connection>.<model>` prefix are stripped before matching.
 */
export const isDedicatedImageGenerationChatModel = (
	model: ChatModelLike | null | undefined
): boolean => chatModelIdCandidates(model).some(isDedicatedImageGenerationModel);

/** OpenAI's gpt-image family (gpt-image, gpt-image-2, chatgpt-image-latest …), resolved like above. */
export const isGptImageChatModel = (model: ChatModelLike | null | undefined): boolean =>
	chatModelIdCandidates(model).some((candidate) => candidate.toLowerCase().includes('gpt-image'));

/** The composer is in image mode: the image toggle is on or the model itself generates images. */
export const isChatImageMode = (
	imageGenerationEnabled: boolean,
	model: ChatModelLike | null | undefined
): boolean => Boolean(imageGenerationEnabled) || isDedicatedImageGenerationChatModel(model);

/**
 * The chat model an image from the image studio goes to: the visible dedicated
 * image model the studio used (`preferredId`, bare or as a selection id), else
 * the same model on another connection, else the first gpt-image one, else any
 * dedicated image model; null when the chat has none, and the image then joins
 * whatever model is selected.
 */
export const pickChatImageModel = <T extends ChatModelLike>(
	models: T[] | null | undefined,
	preferredId = ''
): T | null => {
	const candidates = (models ?? []).filter(
		(model) => !model?.info?.meta?.hidden && isDedicatedImageGenerationChatModel(model)
	);
	const exact = preferredId.trim();
	const preferred = bareModelId(exact).toLowerCase();
	return (
		(exact && candidates.find((model) => getModelSelectionId(model) === exact)) ||
		(preferred &&
			candidates.find((model) =>
				chatModelIdCandidates(model).some((candidate) => candidate.toLowerCase() === preferred)
			)) ||
		candidates.find(isGptImageChatModel) ||
		candidates[0] ||
		null
	);
};
