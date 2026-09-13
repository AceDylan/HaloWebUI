import { describe, expect, it } from 'vitest';

import { isChatImageMode, isDedicatedImageGenerationChatModel } from './chat-image-mode';

const GPT_IMAGE_SELECTION = 'modelref::openai::personal::id:c153e2d2::gpt-image';

describe('chat-image-mode', () => {
	it('recognizes a dedicated image model selected through a modelref id', () => {
		expect(
			isDedicatedImageGenerationChatModel({
				id: GPT_IMAGE_SELECTION,
				model_id: 'gpt-image',
				original_id: 'gpt-image'
			})
		).toBe(true);
	});

	it('resolves workspace presets through their base model', () => {
		expect(
			isDedicatedImageGenerationChatModel({
				id: 'my-drawing-assistant',
				info: { base_model_id: GPT_IMAGE_SELECTION, meta: { base_selection_id: null } }
			})
		).toBe(true);
		expect(
			isDedicatedImageGenerationChatModel({
				id: 'my-drawing-assistant',
				info: { base_model_id: 'gpt-4o', meta: { base_selection_id: GPT_IMAGE_SELECTION } }
			})
		).toBe(true);
	});

	it('keeps text and vision models out of image mode', () => {
		expect(isDedicatedImageGenerationChatModel({ id: 'gpt-4o' })).toBe(false);
		expect(isDedicatedImageGenerationChatModel({ id: 'llama-3.2-11b-vision' })).toBe(false);
		expect(isDedicatedImageGenerationChatModel({ id: 'hermes-agent' })).toBe(false);
		expect(isDedicatedImageGenerationChatModel({ id: 'veo-3-video' })).toBe(false);
		expect(isDedicatedImageGenerationChatModel(null)).toBe(false);
		expect(isDedicatedImageGenerationChatModel(undefined)).toBe(false);
	});

	it('treats the image toggle as image mode regardless of the model', () => {
		expect(isChatImageMode(true, { id: 'gpt-4o' })).toBe(true);
		expect(isChatImageMode(true, null)).toBe(true);
		expect(isChatImageMode(false, { id: 'gpt-4o' })).toBe(false);
		expect(isChatImageMode(false, null)).toBe(false);
		expect(isChatImageMode(false, { id: GPT_IMAGE_SELECTION })).toBe(true);
	});
});
