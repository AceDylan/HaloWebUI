import { describe, expect, it } from 'vitest';

import {
	IMAGE_STUDIO_HISTORY_LIMIT,
	normalizeGalleryImages,
	normalizeGenerationHistory,
	normalizeImageStudioData,
	parseImageStudioMigrationMarker,
	parseStoredImageStudioList,
	partitionImageStudioItems,
	planImageStudioLocalMigration,
	serializeImageStudioMigrationMarker,
	toImageStudioItemForms,
	type GalleryImage,
	type GenerationHistory
} from './image-studio-storage';
import type { ImageTemplate } from './image-templates';

const template = (overrides: Partial<ImageTemplate>): ImageTemplate => ({
	id: 'template_1',
	name: 'Poster',
	tags: [],
	createdAt: 1,
	updatedAt: 1,
	config: { prompt: 'a poster' },
	...overrides
});

const gallery = (overrides: Partial<GalleryImage>): GalleryImage => ({
	id: 'gallery_1',
	url: '/api/v1/files/abc/content',
	prompt: 'a cat',
	model: 'gpt-image',
	size: '1024x1024',
	createdAt: 10,
	...overrides
});

const history = (overrides: Partial<GenerationHistory>): GenerationHistory => ({
	id: 'history_1',
	prompt: 'a cat',
	model: 'gpt-image',
	parameters: { size: '1024x1024' },
	status: 'success',
	createdAt: 10,
	...overrides
});

describe('image-studio-storage', () => {
	it('reads legacy localStorage lists defensively', () => {
		expect(parseStoredImageStudioList(null)).toEqual([]);
		expect(parseStoredImageStudioList('not json')).toEqual([]);
		expect(parseStoredImageStudioList('{"a":1}')).toEqual([]);
		expect(parseStoredImageStudioList('[{"id":"x"}]')).toEqual([{ id: 'x' }]);
	});

	it('normalizes gallery images and drops entries without id or url', () => {
		const images = normalizeGalleryImages(
			[
				{
					id: 'a',
					url: '/img/a',
					prompt: 'p',
					model: 'm',
					size: 's',
					createdAt: 5,
					favorite: true
				},
				{ id: 'b', url: '/img/b', favorite: 'yes', tags: ['x', '', 3] },
				{ id: '', url: '/img/c' },
				{ id: 'd' },
				'junk',
				{ id: 'a', url: '/img/dup' }
			],
			99
		);
		expect(images).toEqual([
			{ id: 'a', url: '/img/a', prompt: 'p', model: 'm', size: 's', createdAt: 5, favorite: true },
			{ id: 'b', url: '/img/b', prompt: '', model: '', size: '', createdAt: 99, tags: ['x', '3'] }
		]);
	});

	it('normalizes generation history and coerces unknown status to failed', () => {
		const items = normalizeGenerationHistory(
			[
				{ id: 'h1', prompt: 'p', status: 'success', images: ['/a', ''], parameters: null },
				{ id: 'h2', prompt: 'q', status: 'weird', error: 'boom', completedAt: 12, createdAt: 11 },
				{ prompt: 'no id' }
			],
			7
		);
		expect(items).toEqual([
			{
				id: 'h1',
				prompt: 'p',
				model: '',
				parameters: {},
				status: 'success',
				createdAt: 7,
				images: ['/a']
			},
			{
				id: 'h2',
				prompt: 'q',
				model: '',
				parameters: {},
				status: 'failed',
				createdAt: 11,
				error: 'boom',
				completedAt: 12
			}
		]);
	});

	it('sorts newest first and caps history when normalizing a full data set', () => {
		const data = normalizeImageStudioData({
			templates: [{ name: 'T', prompt: 'x' }],
			gallery: [gallery({ id: 'g1', createdAt: 1 }), gallery({ id: 'g2', createdAt: 2 })],
			history: Array.from({ length: IMAGE_STUDIO_HISTORY_LIMIT + 5 }, (_, index) =>
				history({ id: `h${index}`, createdAt: index + 1 })
			)
		});
		expect(data.templates).toHaveLength(1);
		expect(data.gallery.map((image) => image.id)).toEqual(['g2', 'g1']);
		expect(data.history).toHaveLength(IMAGE_STUDIO_HISTORY_LIMIT);
		expect(data.history[0].id).toBe(`h${IMAGE_STUDIO_HISTORY_LIMIT + 4}`);
	});

	it('partitions server rows by kind and trusts the row id over the payload id', () => {
		const data = partitionImageStudioItems([
			{ id: 't1', kind: 'template', data: { id: 'stale', name: 'T', config: { prompt: 'x' } } },
			{ id: 'g1', kind: 'gallery', data: gallery({ id: 'g1' }) },
			{ id: 'h1', kind: 'history', data: history({ id: 'h1' }) },
			{ id: 'x', kind: 'unknown', data: {} },
			{ id: 'y', kind: 'gallery', data: null },
			null
		]);
		expect(data.templates.map((item) => item.id)).toEqual(['t1']);
		expect(data.gallery.map((item) => item.id)).toEqual(['g1']);
		expect(data.history.map((item) => item.id)).toEqual(['h1']);
	});

	it('wraps items into upsert forms without sharing the object', () => {
		const image = gallery({ id: 'g1' });
		const [form] = toImageStudioItemForms('gallery', [image]);
		expect(form).toEqual({ id: 'g1', kind: 'gallery', data: image });
		expect(form.data).not.toBe(image);
	});

	it('uploads only what the server is missing and never overwrites server rows', () => {
		const local = normalizeImageStudioData({
			templates: [
				template({ id: 'dup_by_identity', name: 'Poster', config: { prompt: 'a poster' } }),
				template({ id: 'server_t', name: 'Different', config: { prompt: 'other' } }),
				template({ id: 'fresh_t', name: 'Fresh', config: { prompt: 'fresh' } })
			],
			gallery: [gallery({ id: 'g_shared', prompt: 'local version' }), gallery({ id: 'g_local' })],
			history: [history({ id: 'h_shared' }), history({ id: 'h_local', createdAt: 3 })]
		});
		const server = normalizeImageStudioData({
			templates: [template({ id: 'server_t', name: 'Poster', config: { prompt: 'a poster' } })],
			gallery: [gallery({ id: 'g_shared', prompt: 'server version' })],
			history: [history({ id: 'h_shared' })]
		});

		const plan = planImageStudioLocalMigration(local, server, 1234);

		expect(plan.counts).toEqual({ templates: 2, gallery: 1, history: 1 });
		const uploadedTemplates = plan.forms.filter((form) => form.kind === 'template');
		expect(uploadedTemplates.map((form) => form.data.name)).toEqual(['Different', 'Fresh']);
		// The id clash with a different server template gets a new id instead of overwriting it.
		expect(uploadedTemplates[0].id).not.toBe('server_t');
		expect(plan.forms.filter((form) => form.kind === 'gallery').map((form) => form.id)).toEqual([
			'g_local'
		]);
		expect(plan.forms.filter((form) => form.kind === 'history').map((form) => form.id)).toEqual([
			'h_local'
		]);
		expect(plan.merged.gallery.find((image) => image.id === 'g_shared')?.prompt).toBe(
			'server version'
		);
		expect(plan.merged.templates).toHaveLength(3);
		expect(plan.merged.history.map((item) => item.id)).toEqual(['h_shared', 'h_local']);
	});

	it('does not upload local history that would fall outside the retention window', () => {
		const server = normalizeImageStudioData({
			history: Array.from({ length: IMAGE_STUDIO_HISTORY_LIMIT }, (_, index) =>
				history({ id: `s${index}`, createdAt: 1000 + index })
			)
		});
		const local = normalizeImageStudioData({
			history: [history({ id: 'old', createdAt: 1 }), history({ id: 'new', createdAt: 5000 })]
		});
		const plan = planImageStudioLocalMigration(local, server);
		expect(plan.forms.map((form) => form.id)).toEqual(['new']);
		expect(plan.merged.history).toHaveLength(IMAGE_STUDIO_HISTORY_LIMIT);
		expect(plan.merged.history[0].id).toBe('new');
	});

	it('returns an empty plan when nothing is stored locally', () => {
		const plan = planImageStudioLocalMigration(
			normalizeImageStudioData({}),
			normalizeImageStudioData({ gallery: [gallery({})] })
		);
		expect(plan.forms).toEqual([]);
		expect(plan.merged.gallery).toHaveLength(1);
	});

	it('round-trips the migration marker and rejects garbage', () => {
		const marker = { userId: 'u1', migratedAt: 42, uploaded: 3 };
		expect(parseImageStudioMigrationMarker(serializeImageStudioMigrationMarker(marker))).toEqual(
			marker
		);
		expect(parseImageStudioMigrationMarker('nope')).toBeNull();
		expect(parseImageStudioMigrationMarker('[]')).toBeNull();
		expect(parseImageStudioMigrationMarker(null)).toBeNull();
	});
});
