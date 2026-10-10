// The new-chat landing page deals the models out as cards (Placeholder/ModelDeck.svelte):
// the same models the menu lists, pinned ones first, so a handful of models can be picked
// without opening the menu.

import { isDedicatedImageGenerationChatModel } from './chat-image-mode';
import { isHermesAgentModel } from './hermes';
import { getModelSelectionId } from './model-identity';

// Structural: the store's `Model` is typed tightly elsewhere; only these fields matter here.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type DeckModel = { id?: string; owned_by?: string; info?: any; [key: string]: any };

export type DeckKind = 'agent' | 'image' | 'chat';

/** More than this and the menu is the better place; the deck shows the first ones. */
export const MODEL_DECK_MAX = 8;

/** Visible models in menu order with the pinned ones first; none when there is nothing to pick. */
export const modelDeck = <T extends DeckModel>(
	models: T[] | null | undefined,
	pinned: readonly string[] | null | undefined = [],
	max = MODEL_DECK_MAX
): T[] => {
	const visible = (models ?? []).filter(
		(model) => !!model?.id && !model?.info?.meta?.hidden && model?.owned_by !== 'arena'
	);
	const pinnedOrder = new Map((pinned ?? []).map((id, index) => [id, index]));
	const rank = (model: T) => pinnedOrder.get(getModelSelectionId(model as any)) ?? Infinity;
	// Array sort is stable, so unpinned models keep the menu's order.
	const deck = [...visible].sort((a, b) => rank(a) - rank(b)).slice(0, max);
	return deck.length > 1 ? deck : [];
};

export const modelDeckKind = (
	model: DeckModel | null | undefined,
	hermesModelIds?: readonly string[] | null
): DeckKind =>
	isHermesAgentModel(model as any, hermesModelIds)
		? 'agent'
		: isDedicatedImageGenerationChatModel(model)
			? 'image'
			: 'chat';
