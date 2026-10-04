// uploadFile with onProgress goes through XMLHttpRequest (fetch cannot report how much of
// the body has gone out) and must settle exactly like the fetch path.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { uploadFile } from './index';

type Listener = ((event: any) => void) | null;

class FakeXhr {
	static last: FakeXhr | null = null;
	method = '';
	url = '';
	headers: Record<string, string> = {};
	body: unknown = null;
	status = 0;
	statusText = '';
	responseText = '';
	upload: { onprogress: Listener; onload: Listener } = { onprogress: null, onload: null };
	onload: Listener = null;
	onerror: Listener = null;
	onabort: Listener = null;
	ontimeout: Listener = null;

	constructor() {
		FakeXhr.last = this;
	}
	open(method: string, url: string) {
		this.method = method;
		this.url = url;
	}
	setRequestHeader(name: string, value: string) {
		this.headers[name] = value;
	}
	send(body: unknown) {
		this.body = body;
	}
	// test helpers
	progress(loaded: number, total: number, lengthComputable = true) {
		this.upload.onprogress?.({ loaded, total, lengthComputable });
	}
	finish(status: number, body: string, statusText = '') {
		this.upload.onload?.({ loaded: 1000, total: 1000 });
		this.status = status;
		this.statusText = statusText;
		this.responseText = body;
		this.onload?.({});
	}
}

const file = () => new File([new Uint8Array(900)], 'cat.png', { type: 'image/png' });

describe('uploadFile progress', () => {
	beforeEach(() => {
		FakeXhr.last = null;
		vi.stubGlobal('XMLHttpRequest', FakeXhr);
	});
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('reports each whole percent once and resolves with the stored file', async () => {
		const seen: number[] = [];
		const pending = uploadFile('tok', file(), {
			process: false,
			onProgress: ({ percent }) => seen.push(percent)
		});
		const xhr = FakeXhr.last!;
		expect(xhr.method).toBe('POST');
		expect(xhr.url).toMatch(/\/files\/\?process=false$/);
		expect(xhr.headers.authorization).toBe('Bearer tok');
		expect(xhr.body).toBeInstanceOf(FormData);

		xhr.progress(0, 1000);
		xhr.progress(4, 1000); // still 0%
		xhr.progress(420, 1000);
		xhr.progress(425, 1000); // still 42%
		xhr.progress(10, 0, false); // unknown length: ignored
		xhr.finish(200, JSON.stringify({ id: 'f1', meta: { name: 'cat.png' } }));

		await expect(pending).resolves.toEqual({ id: 'f1', meta: { name: 'cat.png' } });
		expect(seen).toEqual([0, 42, 100]);
	});

	it('throws the server detail like the fetch path', async () => {
		const pending = uploadFile('tok', file(), { onProgress: () => {} });
		FakeXhr.last!.finish(413, JSON.stringify({ detail: 'File too large' }), 'Payload Too Large');
		await expect(pending).rejects.toBe('File too large');
	});

	it('falls back to the status text when the error body is not JSON', async () => {
		const pending = uploadFile('tok', file(), { onProgress: () => {} });
		FakeXhr.last!.finish(502, '', 'Bad Gateway');
		await expect(pending).rejects.toBe('Bad Gateway');
	});

	it('resolves null when the request never completes, as a failed fetch does', async () => {
		const pending = uploadFile('tok', file(), { onProgress: () => {} });
		FakeXhr.last!.onerror?.({});
		await expect(pending).resolves.toBeNull();
	});

	it('keeps using fetch when nobody asks for progress', async () => {
		const fetchMock = vi.fn(
			async () =>
				new Response(JSON.stringify({ id: 'f2' }), {
					status: 200,
					headers: { 'Content-Type': 'application/json' }
				})
		);
		vi.stubGlobal('fetch', fetchMock);
		await expect(uploadFile('tok', file())).resolves.toEqual({ id: 'f2' });
		expect(fetchMock).toHaveBeenCalledTimes(1);
		expect(FakeXhr.last).toBeNull();
	});
});
