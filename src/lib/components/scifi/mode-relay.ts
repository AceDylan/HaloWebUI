/**
 * The chat and its modes — 精答, 讨论台, 协作台, 生图工作台 — as one system: a dock on every mode page
 * (ModeDock.svelte) that switches between them and carries what you were writing along, a live
 * count of the work under way in each, and a flash of light when work is relayed from one to
 * another (RelayFlash.svelte, fed by handOff in $lib/utils/handoff).
 */
import { get, writable } from 'svelte/store';
import type { HandoffFile, HandoffOrigin } from '$lib/utils/handoff';

export type ModeKey = 'chat' | 'answer' | 'discuss' | 'teams' | 'studio';

/** What the page on screen is writing: switching mode in the dock takes it along. */
export type ModeDraft = {
	mode: ModeKey;
	text: string;
	/** Background that came with it (an earlier conversation, a conclusion). */
	context: string;
	from: HandoffOrigin | null;
	files: HandoffFile[];
};

export const modeDraft = writable<ModeDraft | null>(null);

const sameDraft = (a: ModeDraft | null, b: ModeDraft) =>
	!!a &&
	a.mode === b.mode &&
	a.text === b.text &&
	a.context === b.context &&
	JSON.stringify(a.from) === JSON.stringify(b.from) &&
	JSON.stringify(a.files) === JSON.stringify(b.files);

/**
 * A mode page says what it is writing. Pages call it from afterUpdate, not from a `$:` line: a
 * draft filled in by another reactive block (a handoff taken once the models are known) would
 * not re-run a `$:` line in the same update, and the dock would carry an empty draft.
 */
export const setModeDraft = (
	mode: ModeKey,
	text: string,
	extra: { context?: string; from?: HandoffOrigin | null; files?: HandoffFile[] } = {}
) => {
	const next: ModeDraft = {
		mode,
		text: text ?? '',
		context: extra.context ?? '',
		from: extra.from ?? null,
		files: extra.files ?? []
	};
	if (!sameDraft(get(modeDraft), next)) modeDraft.set(next);
};

/** On leaving the page: its draft no longer travels (another page's is left alone). */
export const clearModeDraft = (mode: ModeKey) => {
	if (get(modeDraft)?.mode === mode) modeDraft.set(null);
};

/** Whether a draft has anything to carry. */
export const carries = (draft: ModeDraft | null | undefined): boolean =>
	!!draft && (!!draft.text.trim() || draft.files.length > 0);

/** Work under way in each mode (filled by the sidebar's badges, which already follow it). */
export const modeLive = writable<Record<ModeKey, number>>({
	chat: 0,
	answer: 0,
	discuss: 0,
	teams: 0,
	studio: 0
});

export const setModeLive = (mode: ModeKey, count: number) =>
	modeLive.update((live) => (live[mode] === count ? live : { ...live, [mode]: count }));

/** The names the dock and the relay flash use. */
export const MODE_LABEL: Record<ModeKey, string> = {
	chat: '对话',
	answer: '精答',
	discuss: '讨论台',
	teams: '协作台',
	studio: '生图工作台'
};
