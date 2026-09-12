import { WEBUI_API_BASE_URL } from '$lib/constants';
import type {
	ImageStudioItemForm,
	ImageStudioKind,
	ImageStudioServerItem
} from '$lib/utils/image-studio-storage';
import { parseJsonResponse } from '../response';

const IMAGE_STUDIO_API_BASE_URL = `${WEBUI_API_BASE_URL}/image-studio`;

const headers = (token: string, json = false) => ({
	Accept: 'application/json',
	...(json ? { 'Content-Type': 'application/json' } : {}),
	authorization: `Bearer ${token}`
});

export const getImageStudioItems = async (
	token: string,
	kind?: ImageStudioKind
): Promise<ImageStudioServerItem[]> => {
	const query = kind ? `?kind=${encodeURIComponent(kind)}` : '';
	const res = await fetch(`${IMAGE_STUDIO_API_BASE_URL}/items${query}`, {
		method: 'GET',
		headers: headers(token)
	}).then(parseJsonResponse<ImageStudioServerItem[]>);
	return Array.isArray(res) ? res : [];
};

export const upsertImageStudioItems = async (
	token: string,
	items: ImageStudioItemForm[]
): Promise<ImageStudioServerItem[]> => {
	if (items.length === 0) {
		return [];
	}
	const res = await fetch(`${IMAGE_STUDIO_API_BASE_URL}/items/upsert`, {
		method: 'POST',
		headers: headers(token, true),
		body: JSON.stringify({ items })
	}).then(parseJsonResponse<ImageStudioServerItem[]>);
	return Array.isArray(res) ? res : [];
};

export const deleteImageStudioItem = async (token: string, id: string): Promise<boolean> => {
	const res = await fetch(`${IMAGE_STUDIO_API_BASE_URL}/items/${encodeURIComponent(id)}`, {
		method: 'DELETE',
		headers: headers(token)
	}).then(parseJsonResponse<boolean>);
	return res === true;
};

export const clearImageStudioItems = async (
	token: string,
	kind: ImageStudioKind
): Promise<boolean> => {
	const res = await fetch(`${IMAGE_STUDIO_API_BASE_URL}/items/clear`, {
		method: 'POST',
		headers: headers(token, true),
		body: JSON.stringify({ kind })
	}).then(parseJsonResponse<boolean>);
	return res === true;
};

export type ImageStudioMigrationRecord = {
	user_id: string;
	source: string;
	uploaded: number;
	migrated_at: number;
};

export type ImageStudioLegacyImportResult = {
	accepted: boolean;
	uploaded: number;
	migration: ImageStudioMigrationRecord | null;
};

/**
 * Uploads what this browser still holds only in localStorage. The server
 * accepts this once per account and refuses it (nothing stored) once the
 * account has server data or deleted items, so a browser without a local
 * migration marker can never bring deleted templates back.
 */
export const importLegacyImageStudioItems = async (
	token: string,
	items: ImageStudioItemForm[]
): Promise<ImageStudioLegacyImportResult> => {
	const res = await fetch(`${IMAGE_STUDIO_API_BASE_URL}/legacy-migration`, {
		method: 'POST',
		headers: headers(token, true),
		body: JSON.stringify({ items })
	}).then(parseJsonResponse<Partial<ImageStudioLegacyImportResult> | null>);
	const uploaded = Number(res?.uploaded);
	return {
		accepted: res?.accepted === true,
		uploaded: Number.isFinite(uploaded) && uploaded > 0 ? Math.floor(uploaded) : 0,
		migration: res?.migration ?? null
	};
};
