import { describe, expect, it } from 'vitest';

import {
	collectImageTemplateTags,
	filterImageTemplates,
	isJsonPromptTemplate,
	mergeImageTemplates,
	normalizeImportedImageTemplates,
	serializeImageTemplates,
	sortImageTemplates,
	type ImageTemplate
} from './image-templates';

const template = (overrides: Partial<ImageTemplate>): ImageTemplate => ({
	id: 'id',
	name: 'name',
	tags: [],
	createdAt: 1,
	updatedAt: 1,
	config: {},
	...overrides
});

describe('image-templates', () => {
	it('normalizes bare arrays, export envelopes and single objects with aliases', () => {
		const fromArray = normalizeImportedImageTemplates(
			[
				{ name: '海报 · 常规', tags: 'awesome, 海报, 海报', prompt: '设计一张海报', createdAt: 5 },
				{ title: 'UI 截图', category: ['UI'], content: '{"type": "UI Screenshot"}' },
				{ name: '   ', prompt: '' },
				'junk',
				null
			],
			100
		);
		expect(fromArray).toHaveLength(2);
		expect(fromArray[0]).toMatchObject({
			name: '海报 · 常规',
			tags: ['awesome', '海报'],
			createdAt: 5,
			updatedAt: 5,
			config: { prompt: '设计一张海报' }
		});
		expect(fromArray[0].id).toMatch(/^template_100_/);
		expect(fromArray[1]).toMatchObject({
			name: 'UI 截图',
			tags: ['UI'],
			createdAt: 100,
			config: { prompt: '{"type": "UI Screenshot"}' }
		});

		const fromEnvelope = normalizeImportedImageTemplates({
			version: 1,
			templates: [{ id: 'keep', name: 'x', config: { prompt: 'p', quality: 'low', steps: '20' } }]
		});
		expect(fromEnvelope).toHaveLength(1);
		expect(fromEnvelope[0].id).toBe('keep');
		expect(fromEnvelope[0].config).toEqual({ prompt: 'p', quality: 'low', steps: 20 });

		expect(normalizeImportedImageTemplates({ name: 'solo', prompt: 'one' })).toHaveLength(1);
		expect(normalizeImportedImageTemplates('nope')).toEqual([]);
		expect(normalizeImportedImageTemplates({ templates: 'nope' })).toEqual([]);
	});

	it('keeps templates loaded from storage intact when they are already well-formed', () => {
		const stored = template({
			id: 'template_1',
			name: 'kept',
			tags: ['a'],
			createdAt: 10,
			updatedAt: 12,
			config: { prompt: 'p', background: 'transparent' }
		});
		expect(normalizeImportedImageTemplates([stored])).toEqual([stored]);
	});

	it('merges imports ahead of existing templates, skipping duplicates and colliding ids', () => {
		const existing = [template({ id: 'a', name: 'Poster', config: { prompt: 'make a poster' } })];
		const incoming = [
			template({ id: 'a', name: 'New', config: { prompt: 'fresh' } }),
			template({ id: 'b', name: 'poster', config: { prompt: 'make a poster' } }),
			template({ id: 'c', name: 'Third', config: { prompt: 'third' } })
		];

		const merged = mergeImageTemplates(existing, incoming, 7);

		expect(merged.added).toBe(2);
		expect(merged.skipped).toBe(1);
		expect(merged.templates.map((entry) => entry.name)).toEqual(['New', 'Third', 'Poster']);
		expect(merged.templates[0].id).not.toBe('a');
		expect(merged.templates[1].id).toBe('c');
	});

	it('counts tags, filters by query or tag and sorts by recency or name', () => {
		const templates = [
			template({ id: '1', name: 'Beta poster', tags: ['海报', 'json'], updatedAt: 2, config: { prompt: 'x' } }),
			template({ id: '2', name: 'alpha ui', tags: ['UI'], updatedAt: 5, config: { prompt: 'screen' } }),
			template({ id: '3', name: 'Gamma', tags: ['海报'], updatedAt: 3, config: { prompt: 'Movie POSTER' } })
		];

		// ties fall back to locale order, which is case-insensitive: json < UI
		expect(collectImageTemplateTags(templates)).toEqual([
			{ tag: '海报', count: 2 },
			{ tag: 'json', count: 1 },
			{ tag: 'UI', count: 1 }
		]);
		expect(filterImageTemplates(templates, { tag: '海报' }).map((t) => t.id)).toEqual(['1', '3']);
		expect(filterImageTemplates(templates, { query: 'poster' }).map((t) => t.id)).toEqual(['1', '3']);
		expect(filterImageTemplates(templates, { query: 'UI', tag: '海报' })).toEqual([]);
		expect(sortImageTemplates(templates, 'recent').map((t) => t.id)).toEqual(['2', '3', '1']);
		expect(sortImageTemplates(templates, 'name').map((t) => t.id)).toEqual(['2', '1', '3']);
	});

	it('recognizes JSON prompts and serializes an export envelope', () => {
		expect(isJsonPromptTemplate('{"type": "poster"}')).toBe(true);
		expect(isJsonPromptTemplate('  {"broken": ')).toBe(false);
		expect(isJsonPromptTemplate('plain prompt')).toBe(false);

		const payload = JSON.parse(serializeImageTemplates([template({ id: 'z', name: 'z' })]));
		expect(payload.version).toBe(1);
		expect(payload.templates).toHaveLength(1);
		expect(typeof payload.exportedAt).toBe('string');
	});
});
