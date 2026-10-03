import { describe, expect, it } from 'vitest';

import { classifyImageGenerationError, imageRequestHadReferences } from './image-generation-errors';

describe('classifyImageGenerationError', () => {
	it('recognises the relay text that hides the upstream cause', () => {
		expect(classifyImageGenerationError('请求格式非法，请检查请求结构是否符合 API 规范')).toBe(
			'relay_hidden'
		);
		expect(classifyImageGenerationError('400: 请求参数验证失败，请检查请求格式是否正确')).toBe(
			'relay_hidden'
		);
	});

	it('names the causes a person can act on', () => {
		expect(
			classifyImageGenerationError('Your request was rejected by the safety system.')
		).toBe('moderation');
		expect(classifyImageGenerationError('403 insufficient_user_quota')).toBe('quota');
		expect(classifyImageGenerationError('Rate limit reached for images')).toBe('rate_limit');
		expect(classifyImageGenerationError('Request timed out')).toBe('timeout');
		expect(classifyImageGenerationError('Invalid image file or mode for image 1')).toBe(
			'reference'
		);
	});

	it('leaves anything else to the raw text', () => {
		expect(classifyImageGenerationError('Upstream did not return this image.')).toBeNull();
		expect(classifyImageGenerationError('')).toBeNull();
		expect(classifyImageGenerationError(undefined)).toBeNull();
	});
});

describe('imageRequestHadReferences', () => {
	const image = { type: 'image', url: '/api/v1/files/a/content' };

	it('counts the uploads and kept references of the message answered', () => {
		expect(imageRequestHadReferences({ u: { files: [image] } }, 'u')).toBe(true);
		expect(imageRequestHadReferences({ u: { imageReferences: [image] } }, 'u')).toBe(true);
	});

	it('trusts a recorded empty reference list over earlier images', () => {
		const messages = {
			a: { files: [image] },
			u: { parentId: 'a', imageReferences: [] }
		};
		expect(imageRequestHadReferences(messages, 'u')).toBe(false);
	});

	it('looks back for messages from before references were recorded', () => {
		const messages = {
			first: { files: [] },
			a: { parentId: 'first', files: [image] },
			u: { parentId: 'a' }
		};
		expect(imageRequestHadReferences(messages, 'u')).toBe(true);
		expect(imageRequestHadReferences({ u: { parentId: 'first' }, first: {} }, 'u')).toBe(false);
	});

	it('handles a missing parent and a cycle', () => {
		expect(imageRequestHadReferences({}, 'nope')).toBe(false);
		expect(imageRequestHadReferences(null, 'u')).toBe(false);
		expect(imageRequestHadReferences({ u: { parentId: 'u' } }, 'u')).toBe(false);
	});
});
