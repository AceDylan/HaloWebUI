import { WEBUI_API_BASE_URL } from '$lib/constants';
import {
	createResponseError,
	parseBlobResponse,
	parseJsonResponse,
	parseResponseText
} from '../response';

export type UploadProgress = {
	/** Bytes sent so far. */
	loaded: number;
	/** Bytes to send (the whole form, a little more than the file). */
	total: number;
	/** 0–100, rounded down. 100 once every byte is out; the server may still be working. */
	percent: number;
};

// fetch cannot tell how much of a request body has gone out; XMLHttpRequest can. Resolves
// and rejects like `fetch(...).then(parseJsonResponse)`: the parsed body, a response error
// carrying `detail`, or a TypeError without one when the request never completed.
const postFormWithProgress = (
	url: string,
	token: string,
	body: FormData,
	onProgress: (progress: UploadProgress) => void,
	signal?: AbortSignal
): Promise<unknown> =>
	new Promise((resolve, reject) => {
		const xhr = new XMLHttpRequest();
		if (signal?.aborted) return reject(new TypeError('Upload aborted'));
		signal?.addEventListener('abort', () => xhr.abort(), { once: true });
		let lastPercent = -1;
		let lastReport = 0;
		const report = (loaded: number, total: number) => {
			const percent = Math.min(100, Math.floor((loaded / total) * 100));
			// Also once a second within a percent: a slow upload of a big file is still moving.
			if (percent === lastPercent && Date.now() - lastReport < 1000) return;
			lastPercent = percent;
			lastReport = Date.now();
			onProgress({ loaded, total, percent });
		};

		xhr.open('POST', url);
		xhr.setRequestHeader('Accept', 'application/json');
		xhr.setRequestHeader('authorization', `Bearer ${token}`);
		xhr.upload.onprogress = (event) => {
			if (event.lengthComputable && event.total > 0) report(event.loaded, event.total);
		};
		xhr.upload.onload = (event) => {
			const total = event.total > 0 ? event.total : 1;
			report(total, total);
		};
		xhr.onload = () => {
			const payload = parseResponseText(xhr.responseText);
			if (xhr.status >= 200 && xhr.status < 300) {
				resolve(payload);
			} else {
				reject(createResponseError({ status: xhr.status, statusText: xhr.statusText }, payload));
			}
		};
		xhr.onerror = () => reject(new TypeError('Failed to fetch'));
		xhr.onabort = () => reject(new TypeError('Upload aborted'));
		xhr.ontimeout = () => reject(new TypeError('Upload timed out'));
		xhr.send(body);
	});

type UploadOptions = {
	processingMode?: string;
	process?: boolean;
	/** Called as the file goes out: each whole percent, and at least once a second while bytes move. */
	onProgress?: (progress: UploadProgress) => void;
	/** Record the file's SHA-256 once stored, so getReusableFile can find it later. */
	reuse?: boolean;
	signal?: AbortSignal;
};

// POST /files/. Rejects with the raw error: a response error (with `status` and `detail`)
// or a TypeError when the request never completed.
export const sendUpload = (token: string, file: File, options: UploadOptions = {}) => {
	const data = new FormData();
	data.append('file', file);
	const query = new URLSearchParams();
	if (options.processingMode) {
		query.set('processing_mode', options.processingMode);
	}
	if (typeof options.process === 'boolean') {
		query.set('process', String(options.process));
	}
	if (options.reuse) {
		query.set('reuse', 'true');
	}

	const url = `${WEBUI_API_BASE_URL}/files/${query.toString() ? `?${query}` : ''}`;
	return options.onProgress && typeof XMLHttpRequest !== 'undefined'
		? postFormWithProgress(url, token, data, options.onProgress, options.signal)
		: fetch(url, {
				method: 'POST',
				headers: {
					Accept: 'application/json',
					authorization: `Bearer ${token}`
				},
				body: data,
				signal: options.signal
			}).then(parseJsonResponse);
};

export const uploadFile = async (token: string, file: File, options: UploadOptions = {}) => {
	let error = null;

	const res = await sendUpload(token, file, options).catch((err) => {
		error = err.detail;
		console.log(err);
		return null;
	});

	if (error) {
		throw error;
	}

	return res;
};

/** The caller's finished earlier upload (`reuse: true`) of the same bytes, stored the
 * same way; null when there is none or the lookup fails. */
export const getReusableFile = async (
	token: string,
	query: {
		sha256: string;
		size: number;
		name?: string;
		process?: boolean;
		processingMode?: string;
	}
): Promise<any | null> => {
	const params = new URLSearchParams({ sha256: query.sha256, size: String(query.size) });
	if (query.name) params.set('name', query.name);
	if (typeof query.process === 'boolean') params.set('process', String(query.process));
	if (query.processingMode) params.set('processing_mode', query.processingMode);

	return fetch(`${WEBUI_API_BASE_URL}/files/reusable?${params}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(parseJsonResponse)
		.then((json: any) => (json?.id ? json : null))
		.catch(() => null);
};

export const uploadDir = async (token: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/files/upload/dir`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(parseJsonResponse)
		.catch((err) => {
			error = err.detail;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getFiles = async (token: string = '') => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/files/`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(parseJsonResponse)
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getFileById = async (token: string, id: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/files/${id}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(parseJsonResponse)
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const updateFileDataContentById = async (token: string, id: string, content: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/files/${id}/data/content/update`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			content: content
		})
	})
		.then(parseJsonResponse)
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getFileContentById = async (id: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/files/${id}/content`, {
		method: 'GET',
		headers: {
			Accept: 'application/json'
		},
		credentials: 'include'
	})
		.then(parseBlobResponse)
		.catch((err) => {
			error = err.detail;
			console.log(err);

			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const deleteFileById = async (token: string, id: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/files/${id}`, {
		method: 'DELETE',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(parseJsonResponse)
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const deleteAllFiles = async (token: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/files/all`, {
		method: 'DELETE',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(parseJsonResponse)
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};
