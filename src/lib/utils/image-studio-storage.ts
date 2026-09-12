// The image studio's prompt templates, gallery and generation history are
// stored per user on the server (`/api/v1/image-studio`). Before that they only
// lived in this browser's localStorage. These helpers turn server rows back
// into the item shapes the studio renders, and work out what a browser still
// has to upload the first time it sees the server-side store.

import {
	mergeImageTemplates,
	normalizeImportedImageTemplates,
	type ImageTemplate
} from './image-templates';

export type ImageStudioKind = 'template' | 'gallery' | 'history';

export const IMAGE_STUDIO_KINDS: ImageStudioKind[] = ['template', 'gallery', 'history'];

// Keep in sync with IMAGE_STUDIO_HISTORY_LIMIT in backend/open_webui/models/image_studio.py.
export const IMAGE_STUDIO_HISTORY_LIMIT = 200;

// Marks that this browser's localStorage copy has already been uploaded, so a
// second account on the same device never receives the first one's data.
export const IMAGE_STUDIO_MIGRATION_MARKER_KEY = 'workspace:image-studio:server-migration:v1';

export type GalleryImage = {
	id: string;
	url: string;
	prompt: string;
	negativePrompt?: string;
	model: string;
	size: string;
	createdAt: number;
	favorite?: boolean;
	tags?: string[];
};

export type GenerationHistory = {
	id: string;
	prompt: string;
	negativePrompt?: string;
	model: string;
	parameters: Record<string, any>;
	status: 'success' | 'failed';
	images?: string[];
	error?: string;
	createdAt: number;
	completedAt?: number;
};

export type ImageStudioItemForm = {
	id: string;
	kind: ImageStudioKind;
	data: Record<string, unknown>;
};

export type ImageStudioServerItem = ImageStudioItemForm & {
	user_id?: string;
	created_at?: number;
	updated_at?: number;
};

export type ImageStudioData = {
	templates: ImageTemplate[];
	gallery: GalleryImage[];
	history: GenerationHistory[];
};

export type ImageStudioMigrationMarker = {
	userId: string;
	migratedAt: number;
	uploaded: number;
};

const asText = (value: unknown): string =>
	(typeof value === 'string' ? value : typeof value === 'number' ? String(value) : '').trim();

const asTimestamp = (value: unknown, fallback: number): number => {
	const parsed = Number(value);
	return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
};

const asStringList = (value: unknown): string[] =>
	Array.isArray(value) ? value.map(asText).filter(Boolean) : [];

const asRecord = (value: unknown): Record<string, unknown> | null =>
	value && typeof value === 'object' && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: null;

export const emptyImageStudioData = (): ImageStudioData => ({
	templates: [],
	gallery: [],
	history: []
});

/** Safely reads a JSON array that an older build wrote to localStorage. */
export const parseStoredImageStudioList = (raw: string | null | undefined): unknown[] => {
	if (!raw) {
		return [];
	}
	try {
		const parsed = JSON.parse(raw);
		return Array.isArray(parsed) ? parsed : [];
	} catch {
		return [];
	}
};

export const normalizeGalleryImages = (raw: unknown, now: number = Date.now()): GalleryImage[] => {
	if (!Array.isArray(raw)) {
		return [];
	}
	const images: GalleryImage[] = [];
	const seen = new Set<string>();
	for (const entry of raw) {
		const item = asRecord(entry);
		if (!item) continue;
		const id = asText(item.id);
		const url = asText(item.url);
		if (!id || !url || seen.has(id)) continue;
		seen.add(id);
		const image: GalleryImage = {
			id,
			url,
			prompt: asText(item.prompt),
			model: asText(item.model),
			size: asText(item.size),
			createdAt: asTimestamp(item.createdAt, now)
		};
		const negativePrompt = asText(item.negativePrompt);
		if (negativePrompt) image.negativePrompt = negativePrompt;
		if (item.favorite === true) image.favorite = true;
		const tags = asStringList(item.tags);
		if (tags.length) image.tags = tags;
		images.push(image);
	}
	return images;
};

export const normalizeGenerationHistory = (
	raw: unknown,
	now: number = Date.now()
): GenerationHistory[] => {
	if (!Array.isArray(raw)) {
		return [];
	}
	const history: GenerationHistory[] = [];
	const seen = new Set<string>();
	for (const entry of raw) {
		const item = asRecord(entry);
		if (!item) continue;
		const id = asText(item.id);
		if (!id || seen.has(id)) continue;
		seen.add(id);
		const createdAt = asTimestamp(item.createdAt, now);
		const record: GenerationHistory = {
			id,
			prompt: asText(item.prompt),
			model: asText(item.model),
			parameters: asRecord(item.parameters) ?? {},
			status: item.status === 'success' ? 'success' : 'failed',
			createdAt
		};
		const negativePrompt = asText(item.negativePrompt);
		if (negativePrompt) record.negativePrompt = negativePrompt;
		const images = asStringList(item.images);
		if (images.length) record.images = images;
		const error = asText(item.error);
		if (error) record.error = error;
		const completedAt = Number(item.completedAt);
		if (Number.isFinite(completedAt) && completedAt > 0) record.completedAt = completedAt;
		history.push(record);
	}
	return history;
};

const byCreatedAtDesc = <T extends { createdAt: number }>(items: T[]): T[] =>
	[...items].sort((left, right) => right.createdAt - left.createdAt);

/** Normalizes the three localStorage lists an older build may have left behind. */
export const normalizeImageStudioData = (
	raw: { templates?: unknown; gallery?: unknown; history?: unknown },
	now: number = Date.now()
): ImageStudioData => ({
	templates: normalizeImportedImageTemplates(raw.templates ?? [], now),
	gallery: byCreatedAtDesc(normalizeGalleryImages(raw.gallery, now)),
	history: byCreatedAtDesc(normalizeGenerationHistory(raw.history, now)).slice(
		0,
		IMAGE_STUDIO_HISTORY_LIMIT
	)
});

/** Splits `/image-studio/items` rows into the lists the studio renders. */
export const partitionImageStudioItems = (
	items: unknown,
	now: number = Date.now()
): ImageStudioData => {
	const buckets: Record<ImageStudioKind, Record<string, unknown>[]> = {
		template: [],
		gallery: [],
		history: []
	};
	if (Array.isArray(items)) {
		for (const entry of items) {
			const row = asRecord(entry);
			const data = row ? asRecord(row.data) : null;
			const kind = row ? asText(row.kind) : '';
			if (!row || !data || !(kind in buckets)) continue;
			const id = asText(row.id) || asText(data.id);
			if (!id) continue;
			buckets[kind as ImageStudioKind].push({ ...data, id });
		}
	}
	return normalizeImageStudioData(
		{ templates: buckets.template, gallery: buckets.gallery, history: buckets.history },
		now
	);
};

export const toImageStudioItemForms = <T extends { id: string }>(
	kind: ImageStudioKind,
	items: T[]
): ImageStudioItemForm[] =>
	items.map((item) => ({ id: item.id, kind, data: { ...(item as Record<string, unknown>) } }));

export type ImageStudioMigrationPlan = {
	/** Items this browser has that the server does not; upload these. */
	forms: ImageStudioItemForm[];
	/** What the studio should show once the upload succeeded. */
	merged: ImageStudioData;
	counts: { templates: number; gallery: number; history: number };
};

/**
 * Works out what a browser still holds only locally. Templates are matched the
 * same way imports are (same name + prompt is a duplicate); gallery and history
 * entries are matched by id. Local entries never overwrite server ones.
 */
export const planImageStudioLocalMigration = (
	local: ImageStudioData,
	server: ImageStudioData,
	now: number = Date.now()
): ImageStudioMigrationPlan => {
	const templateMerge = mergeImageTemplates(server.templates, local.templates, now);
	const addedTemplates = templateMerge.templates.slice(0, templateMerge.added);

	const serverGalleryIds = new Set(server.gallery.map((image) => image.id));
	const addedGallery = local.gallery.filter((image) => !serverGalleryIds.has(image.id));

	const serverHistoryIds = new Set(server.history.map((item) => item.id));
	const candidateHistory = local.history.filter((item) => !serverHistoryIds.has(item.id));
	const mergedHistory = byCreatedAtDesc([...server.history, ...candidateHistory]).slice(
		0,
		IMAGE_STUDIO_HISTORY_LIMIT
	);
	const keptHistoryIds = new Set(mergedHistory.map((item) => item.id));
	const addedHistory = candidateHistory.filter((item) => keptHistoryIds.has(item.id));

	return {
		forms: [
			...toImageStudioItemForms('template', addedTemplates),
			...toImageStudioItemForms('gallery', addedGallery),
			...toImageStudioItemForms('history', addedHistory)
		],
		merged: {
			templates: templateMerge.templates,
			gallery: byCreatedAtDesc([...server.gallery, ...addedGallery]),
			history: mergedHistory
		},
		counts: {
			templates: addedTemplates.length,
			gallery: addedGallery.length,
			history: addedHistory.length
		}
	};
};

export const parseImageStudioMigrationMarker = (
	raw: string | null | undefined
): ImageStudioMigrationMarker | null => {
	if (!raw) {
		return null;
	}
	try {
		const marker = asRecord(JSON.parse(raw));
		if (!marker) return null;
		return {
			userId: asText(marker.userId),
			migratedAt: asTimestamp(marker.migratedAt, 0),
			uploaded: Math.max(0, Math.floor(asTimestamp(marker.uploaded, 0)))
		};
	} catch {
		return null;
	}
};

export const serializeImageStudioMigrationMarker = (marker: ImageStudioMigrationMarker): string =>
	JSON.stringify(marker);
