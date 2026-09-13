import { describe, expect, it } from 'vitest';

import {
	applyImageTemplateEdit,
	collectImageTemplateTags,
	describeImageTemplateSettings,
	filterImageTemplates,
	isJsonPromptTemplate,
	mergeImageTemplates,
	normalizeImportedImageTemplates,
	replaceImageTemplate,
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

describe('image-templates edits', () => {
	const saved: ImageTemplate = {
		id: 'template_1',
		name: '把结论生成图片',
		tags: ['图解'],
		createdAt: 10,
		updatedAt: 10,
		config: { prompt: '旧提示词', size: '1536x1024', aspectRatio: '3:2', quality: 'high' }
	};

	it('applies text edits in place and keeps id, createdAt and generation settings', () => {
		const updated = applyImageTemplateEdit(
			saved,
			{ name: '  架构图  ', tags: '运维, 架构,运维', prompt: '新提示词\n', negativePrompt: ' 模糊 ' },
			99
		);
		expect(updated).toEqual({
			id: 'template_1',
			name: '架构图',
			tags: ['运维', '架构'],
			createdAt: 10,
			updatedAt: 99,
			config: {
				prompt: '新提示词',
				negativePrompt: '模糊',
				size: '1536x1024',
				aspectRatio: '3:2',
				quality: 'high'
			}
		});
		// The original is untouched and the list keeps its order.
		expect(saved.name).toBe('把结论生成图片');
		expect(saved.config.prompt).toBe('旧提示词');
		const list = replaceImageTemplate([{ ...saved, id: 'other' }, saved], updated!);
		expect(list.map((template) => template.id)).toEqual(['other', 'template_1']);
		expect(list[1].name).toBe('架构图');
	});

	it('leaves untouched fields alone and clears emptied optional text', () => {
		const withNegative = { ...saved, config: { ...saved.config, negativePrompt: '水印' } };
		const updated = applyImageTemplateEdit(withNegative, { negativePrompt: '   ' }, 50);
		expect(updated?.name).toBe('把结论生成图片');
		expect(updated?.tags).toEqual(['图解']);
		expect(updated?.config.prompt).toBe('旧提示词');
		expect(updated?.config).not.toHaveProperty('negativePrompt');
		expect(updated?.updatedAt).toBe(50);
	});

	it('refuses an edit that removes both the name and the prompt', () => {
		expect(applyImageTemplateEdit(saved, { name: ' ', prompt: '' })).toBeNull();
		expect(applyImageTemplateEdit(saved, { name: '', prompt: '只有提示词' })?.name).toBe(
			'只有提示词'
		);
	});

	it('describes only the generation settings a template carries', () => {
		expect(describeImageTemplateSettings(saved.config)).toEqual([
			{ key: 'size', value: '1536x1024' },
			{ key: 'aspect', value: '3:2' },
			{ key: 'quality', value: 'high' }
		]);
		expect(describeImageTemplateSettings({ prompt: 'x' })).toEqual([]);
	});
});
