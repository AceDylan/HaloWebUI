// Helpers for the assistant library on the page side: reading the library record of a workspace
// model row, the `model:<id>` / `builtin:<id>` refs, the links into the workbenches and the
// version timeline. The record itself is the server's (backend/open_webui/utils/assistant_library.py).
import type { AssistantVersions } from '$lib/apis/assistant-library';
import { sourceLabel } from '$lib/apis/assistant-library';

export type AssistantSourceKind = 'manual' | 'answer' | 'team' | 'discuss' | 'builtin';

export const ASSISTANT_SOURCE_KINDS: AssistantSourceKind[] = [
	'manual',
	'answer',
	'team',
	'discuss',
	'builtin'
];

export const modelRef = (id: string) => `model:${id}`;
export const builtinRef = (id: string) => `builtin:${id}`;

/** The meta of a workspace row: the list API puts it at the top level, models from the store
 * keep it under `info`. */
export const rowMeta = (row: any): Record<string, any> => ({
	...(row?.meta ?? {}),
	...(row?.info?.meta ?? {})
});

const record = (meta: Record<string, any>) =>
	meta?.assistant && typeof meta.assistant === 'object' ? meta.assistant : null;

const legacy = (meta: Record<string, any>) =>
	meta?.answer_desk && typeof meta.answer_desk === 'object' ? meta.answer_desk : null;

/** `manual` | `answer` | `team` | `discuss` | `builtin:<id>`; an assistant 精答 made before the
 * library existed (`meta.answer_desk`) counts as 精答's. */
export const assistantSource = (meta: Record<string, any>): string => {
	const lib = record(meta);
	if (lib?.source) return String(lib.source);
	if (legacy(meta)) return 'answer';
	return 'manual';
};

export const assistantSourceKind = (meta: Record<string, any>): AssistantSourceKind => {
	const source = assistantSource(meta);
	if (source.startsWith('builtin:')) return 'builtin';
	return (ASSISTANT_SOURCE_KINDS as string[]).includes(source)
		? (source as AssistantSourceKind)
		: 'manual';
};

export const assistantVersion = (meta: Record<string, any>): number => {
	const lib = record(meta);
	const value = Number(lib?.version);
	if (Number.isFinite(value) && value >= 1) return Math.floor(value);
	const old = legacy(meta);
	if (!lib && old && Array.isArray(old.revisions)) return old.revisions.length + 1;
	return 1;
};

export const assistantArchived = (meta: Record<string, any>) => Boolean(record(meta)?.archived);

export const assistantEmoji = (meta: Record<string, any>) =>
	String(record(meta)?.emoji ?? legacy(meta)?.emoji ?? '').trim();

export type WorkbenchTarget = 'answer' | 'teams' | 'discuss';

/** 「用于精答 / 协作 / 讨论」: the workbench opens with this assistant picked. */
export const workbenchHref = (target: WorkbenchTarget, ref: string) =>
	`/${target}?assistant=${encodeURIComponent(ref)}`;

/** 「开始对话」 with a workspace assistant: a new chat on that model. */
export const startChatHref = (id: string) => `/?models=${encodeURIComponent(id)}`;

/** Where the run that changed an assistant can be seen (`answer:<chat>`, `discuss:<chat>:<ask>`). */
export const runHref = (runRef: string | null | undefined): string | null => {
	const value = String(runRef ?? '');
	const [kind, chatId] = value.split(':');
	if (!chatId) return null;
	if (kind === 'answer') return `/answer/${encodeURIComponent(chatId)}`;
	if (kind === 'discuss') return `/discuss/${encodeURIComponent(chatId)}`;
	return null;
};

/** Label of a change's source; `undo` is a run's upgrade taken back. */
export const changeSourceLabel = (source: string | null | undefined) =>
	source === 'undo' ? '撤销' : sourceLabel(source);

export type VersionEntry = {
	version: number;
	current: boolean;
	name: string;
	system: string;
	description: string;
	/** When this version was made (ms), if known. */
	at: number | null;
	/** What made it: manual / answer / team / discuss / undo / builtin:<id>. */
	source: string;
	change: string;
	runRef: string | null;
};

/** The versions newest first, each with what made it. A revision keeps a version's settings and
 * the change that replaced it, so version N is described by the record of version N − 1; the
 * first version kept is described by how the assistant was created when that is version 1. */
export const versionTimeline = (data: AssistantVersions | null | undefined): VersionEntry[] => {
	if (!data) return [];
	const revisions = [...(data.revisions ?? [])].sort((a, b) => b.version - a.version);
	const byVersion = new Map(revisions.map((r) => [Number(r.version), r]));
	const madeBy = (version: number) => {
		const before = byVersion.get(version - 1);
		if (before) {
			return {
				at: before.at ?? null,
				source: before.source || 'manual',
				change: before.change || '',
				runRef: before.runRef ?? null
			};
		}
		if (version === 1) {
			return {
				at: data.createdFor?.at ?? null,
				source: data.source || 'manual',
				change: '创建',
				runRef: data.createdFor?.runRef ?? null
			};
		}
		return { at: null, source: '', change: '', runRef: null };
	};

	const current = data.current;
	const entries: VersionEntry[] = [
		{
			version: current.version,
			current: true,
			name: current.name,
			system: current.system ?? '',
			description: current.description ?? '',
			...madeBy(current.version)
		}
	];
	if (entries[0].at === null && current.at) entries[0].at = current.at;
	for (const revision of revisions) {
		if (Number(revision.version) >= current.version) continue;
		entries.push({
			version: Number(revision.version),
			current: false,
			name: revision.name ?? current.name,
			system: revision.system ?? '',
			description: revision.description ?? '',
			...madeBy(Number(revision.version))
		});
	}
	return entries;
};
