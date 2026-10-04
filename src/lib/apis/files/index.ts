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
	onProgress: (progress: UploadProgress) => void
): Promise<unknown> =>
	new Promise((resolve, reject) => {
		const xhr = new XMLHttpRequest();
		let lastPercent = -1;
		const report = (loaded: number, total: number) => {
			const percent = Math.min(100, Math.floor((loaded / total) * 100));
			if (percent === lastPercent) return;
			lastPercent = percent;
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

export const uploadFile = async (
	token: string,
	file: File,
	options: {
		processingMode?: string;
		process?: boolean;
		/** Called as the file goes out, once per whole percent. */
		onProgress?: (progress: UploadProgress) => void;
	} = {}
) => {
	const data = new FormData();
	data.append('file', file);
	let error = null;
	const query = new URLSearchParams();
	if (options.processingMode) {
		query.set('processing_mode', options.processingMode);
	}
	if (typeof options.process === 'boolean') {
		query.set('process', String(options.process));
	}

	const url = `${WEBUI_API_BASE_URL}/files/${query.toString() ? `?${query}` : ''}`;
	const request =
		options.onProgress && typeof XMLHttpRequest !== 'undefined'
			? postFormWithProgress(url, token, data, options.onProgress)
			: fetch(url, {
					method: 'POST',
					headers: {
						Accept: 'application/json',
						authorization: `Bearer ${token}`
					},
					body: data
				}).then(parseJsonResponse);

	const res = await request
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
