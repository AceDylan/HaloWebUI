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
});
