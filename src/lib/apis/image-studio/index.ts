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
