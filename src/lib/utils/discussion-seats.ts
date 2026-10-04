// Which models can take a seat in a 讨论台 discussion. One rule for every place that offers it:
// the discussion page's seat picker and the chat's model menu (its tick boxes start a discussion).
import { isHermesAgentModel } from '$lib/utils/hermes';
import { isDedicatedImageGenerationModel } from '$lib/utils/model-capabilities';

type SeatModel = {
	id?: string;
	owned_by?: string;
	info?: { meta?: { hidden?: boolean } | null } | null;
	[key: string]: unknown;
};

/** Text models only: not Hermes (an agent: minutes per turn, writes its own memory), not image
 * models, not hidden or arena entries. */
export const canJoinDiscussion = (
	model: SeatModel | null | undefined,
	hermesModelIds?: readonly string[] | null
): boolean =>
	!!model?.id &&
	!model?.info?.meta?.hidden &&
	model?.owned_by !== 'arena' &&
	!isHermesAgentModel(model as any, hermesModelIds) &&
	!isDedicatedImageGenerationModel(String(model.id));

export const discussionSeatModels = <T extends SeatModel>(
	models: T[] | null | undefined,
	hermesModelIds?: readonly string[] | null
): T[] => (models ?? []).filter((m) => canJoinDiscussion(m, hermesModelIds));

/**
 * The model menu's tick boxes: ticking a box adds the model, unticking removes it; the second
 * tick means "discuss these" (`discuss` is then the ticked models and the ticks reset).
 */
export const tickModel = (
	picked: string[],
	value: string
): { picked: string[]; discuss: string[] | null } => {
	if (picked.includes(value)) return { picked: picked.filter((v) => v !== value), discuss: null };
	const next = [...picked, value];
	return next.length >= 2 ? { picked: [], discuss: next } : { picked: next, discuss: null };
};
