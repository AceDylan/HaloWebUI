import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('$lib/constants', () => ({ WEBUI_API_BASE_URL: '/api/v1' }));

import { importLegacyImageStudioItems } from './index';

const jsonResponse = (body: unknown, status = 200) =>
	new Response(JSON.stringify(body), {
		status,
		headers: { 'Content-Type': 'application/json' }
	});

describe('importLegacyImageStudioItems', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('posts the browser copy to the legacy-migration endpoint', async () => {
		const fetchMock = vi.fn(async () =>
			jsonResponse({
				accepted: true,
				uploaded: 2,
				migration: { user_id: 'u1', source: 'legacy-upload', uploaded: 2, migrated_at: 1 }
			})
		);
		vi.stubGlobal('fetch', fetchMock);

		const items = [
			{ id: 'template_1', kind: 'template' as const, data: { id: 'template_1', name: 'A' } },
			{ id: 'gallery_1', kind: 'gallery' as const, data: { id: 'gallery_1', url: '/x' } }
		];
		const result = await importLegacyImageStudioItems('tok', items);

		expect(fetchMock).toHaveBeenCalledTimes(1);
		const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
		expect(url).toBe('/api/v1/image-studio/legacy-migration');
		expect(init.method).toBe('POST');
		expect((init.headers as Record<string, string>).authorization).toBe('Bearer tok');
		expect(JSON.parse(init.body as string)).toEqual({ items });
		expect(result).toEqual({
			accepted: true,
			uploaded: 2,
			migration: { user_id: 'u1', source: 'legacy-upload', uploaded: 2, migrated_at: 1 }
		});
	});

	it('reports a refused upload as not accepted with nothing uploaded', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(async () =>
				jsonResponse({
					accepted: false,
					uploaded: 0,
					migration: { user_id: 'u1', source: 'curated', uploaded: 0, migrated_at: 5 }
				})
			)
		);

		const result = await importLegacyImageStudioItems('tok', [
			{ id: 'template_1', kind: 'template', data: {} }
		]);
		expect(result.accepted).toBe(false);
		expect(result.uploaded).toBe(0);
		expect(result.migration?.source).toBe('curated');
	});

	it('normalizes malformed bodies and throws on HTTP errors', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => jsonResponse({ accepted: 'yes', uploaded: '3x' }))
		);
		const result = await importLegacyImageStudioItems('tok', [
			{ id: 'template_1', kind: 'template', data: {} }
		]);
		expect(result).toEqual({ accepted: false, uploaded: 0, migration: null });

		vi.stubGlobal(
			'fetch',
			vi.fn(async () => jsonResponse({ detail: 'nope' }, 500))
		);
		await expect(
			importLegacyImageStudioItems('tok', [{ id: 'template_1', kind: 'template', data: {} }])
		).rejects.toBeTruthy();
	});
});
