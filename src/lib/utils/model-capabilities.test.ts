import { describe, expect, it } from 'vitest';

import { inferModelCapabilities, isDedicatedImageGenerationModel } from './model-capabilities';

describe('image generation model capability inference', () => {
	it('does not classify grok imagine video as image generation', () => {
		expect(isDedicatedImageGenerationModel('grok-imagine-video')).toBe(false);
		expect(inferModelCapabilities('grok-imagine-video').imageGen).toBe(false);
	});

	it('still classifies grok imagine image as image generation', () => {
		expect(isDedicatedImageGenerationModel('grok-imagine-image')).toBe(true);
		expect(inferModelCapabilities('grok-imagine-image').imageGen).toBe(true);
	});

	it('classifies Gemini 3 image preview models as dedicated image generation', () => {
		for (const modelId of [
			'google/gemini-3-pro-image-preview',
			'gemini-3.1-flash-image-preview',
			'gemini-3.0-pro-image-4k'
		]) {
			expect(isDedicatedImageGenerationModel(modelId)).toBe(true);
			expect(inferModelCapabilities(modelId).imageGen).toBe(true);
		}
	});

	it('does not classify non-image Gemini 3 models as dedicated image generation', () => {
		expect(isDedicatedImageGenerationModel('google/gemini-3-pro-preview')).toBe(false);
		expect(isDedicatedImageGenerationModel('gemini-3-pro-vision')).toBe(false);
	});
});
