import { describe, expect, it } from 'vitest';

import { resolveModelIcon, applyModelIcon } from './model-icons';

describe('resolveModelIcon', () => {
	// 基础模型匹配
	it('gpt-4.1-mini direct match', () => {
		const result = resolveModelIcon({ id: 'openai/gpt-4.1-mini' } as any);
		expect(result).toBe('/static/model-icons/gpt-4.1-mini.png');
	});

	it('legacy OpenAI models: babbage-002 direct match', () => {
		const result = resolveModelIcon({ id: 'openai/babbage-002' } as any);
		expect(result).toBe('/static/model-icons/babbage-002.png');
	});

	it('legacy OpenAI models: davinci-002 direct match', () => {
		const result = resolveModelIcon({ id: 'openai/davinci-002' } as any);
		expect(result).toBe('/static/model-icons/davinci-002.png');
	});

	it('OpenAI embeddings: text-embedding-ada-002 direct match', () => {
		const result = resolveModelIcon({ id: 'openai/text-embedding-ada-002' } as any);
		expect(result).toBe('/static/model-icons/text-embedding-ada-002.png');
	});

	it('OpenAI audio: tts-1 direct match', () => {
		const result = resolveModelIcon({ id: 'openai/tts-1' } as any);
		expect(result).toBe('/static/model-icons/tts-1.png');
	});

	it('OpenAI audio: tts-1-hd direct match', () => {
		const result = resolveModelIcon({ id: 'openai/tts-1-hd' } as any);
		expect(result).toBe('/static/model-icons/tts-1-hd.png');
	});

	it('OpenAI audio: whisper-1 direct match', () => {
		const result = resolveModelIcon({ id: 'openai/whisper-1' } as any);
		expect(result).toBe('/static/model-icons/whisper-1.png');
	});

	it('Jev (TypeSafe) models get the TypeSafe mark, prefixed or versioned', () => {
		const icon = '/static/model-icons/jev-color.png';
		expect(resolveModelIcon({ id: '94dae559.jev-latest', name: 'jev-latest' } as any)).toBe(icon);
		expect(resolveModelIcon({ id: 'jev-1.14.0' } as any)).toBe(icon);
		expect(resolveModelIcon({ id: 'typesafe/jev-preview' } as any)).toBe(icon);
		expect(resolveModelIcon({ id: 'jevons-paradox' } as any)).not.toBe(icon);
	});

	it('gpt-4o-2024-05-13 fallback to gpt-4o', () => {
		const result = resolveModelIcon({ id: 'openai/gpt-4o-2024-05-13' } as any);
		expect(result).toBe('/static/model-icons/gpt-4o.png');
	});

	it('gpt-4o:extended match gpt-4o', () => {
		const result = resolveModelIcon({ id: 'openai/gpt-4o:extended' } as any);
		expect(result).toBe('/static/model-icons/gpt-4o.png');
	});

	it('gpt-4o direct match', () => {
		const result = resolveModelIcon({ id: 'openai/gpt-4o' } as any);
		expect(result).toBe('/static/model-icons/gpt-4o.png');
	});

	it('o4-mini direct match', () => {
		const result = resolveModelIcon({ id: 'o4-mini' } as any);
		expect(result).toBe('/static/model-icons/o4-mini.png');
	});

	it('o4-mini-2025-04-16 fallback to o4-mini', () => {
		const result = resolveModelIcon({ id: 'o4-mini-2025-04-16' } as any);
		expect(result).toBe('/static/model-icons/o4-mini.png');
	});

	it('omni-moderation-2024-09-26 fallback to omni-moderation-latest', () => {
		const result = resolveModelIcon({ id: 'omni-moderation-2024-09-26' } as any);
		expect(result).toBe('/static/model-icons/omni-moderation-latest.png');
	});

	// 真实模型结构测试
	it('realistic model: gpt-4.1-mini from OpenRouter', () => {
		const model = {
			id: 'openai/gpt-4.1-mini',
			name: 'OpenAI: GPT-4.1 Mini | openrouter',
			owned_by: 'openrouter',
			originalId: 'openai/gpt-4.1-mini'
		};
		const result = resolveModelIcon(model as any);
		expect(result).toBe('/static/model-icons/gpt-4.1-mini.png');
	});

	it('realistic model: gpt-4o-2024-05-13 from OpenRouter', () => {
		const model = {
			id: 'openai/gpt-4o-2024-05-13',
			name: 'OpenAI: GPT-4o (2024-05-13) | openrouter',
			owned_by: 'openrouter'
		};
		const result = resolveModelIcon(model as any);
		expect(result).toBe('/static/model-icons/gpt-4o.png');
	});

	// 厂商匹配测试
	it('prefers model segment over org token (exa/kimi-k2 -> kimi)', () => {
		expect(resolveModelIcon({ id: 'exa/kimi-k2' } as any)).toBe(
			'/static/model-icons/kimi-color.png'
		);
	});

	it('openrouter org token: aion-labs/* should map to aionlabs icon', () => {
		expect(resolveModelIcon({ id: 'aion-labs/aion-1.0' } as any)).toBe(
			'/static/model-icons/aionlabs-color.svg'
		);
	});

	it('openrouter org token: arcee-ai/* should map to arcee icon', () => {
		expect(resolveModelIcon({ id: 'arcee-ai/coder-large' } as any)).toBe(
			'/static/model-icons/arcee-color.svg'
		);
	});

	it('openrouter nested org/model resolves real brand, not openrouter', () => {
		expect(resolveModelIcon({ id: 'openrouter/anthropic/claude-3.7-sonnet' } as any)).toBe(
			'/static/model-icons/claude-color.svg'
		);
	});

	// Gemini 测试
	it('gemini rules: <3 uses gemini-color', () => {
		expect(resolveModelIcon({ id: 'google/gemini-2.0-flash' } as any)).toBe(
			'/static/model-icons/gemini-color.svg'
		);
	});

	it('gemini rules: >=3 uses gemini3 icon', () => {
		const result = resolveModelIcon({ id: 'google/gemini-3.0-pro' } as any);
		expect(result).toMatch(/gemini/i);
	});

	// 其他厂商
	it('tongyi maps to qwen', () => {
		expect(resolveModelIcon({ id: 'tongyi/qwen-plus' } as any)).toBe(
			'/static/model-icons/qwen-color.svg'
		);
	});

	it('handles parentheses suffix: kwai-kolors/kolors(free) -> kolors', () => {
		expect(resolveModelIcon({ id: 'kwai-kolors/kolors(free)' } as any)).toBe(
			'/static/model-icons/kolors-color.svg'
		);
	});

	it('microsoft models fall back to copilot icon', () => {
		expect(resolveModelIcon({ id: 'microsoft/phi-4' } as any)).toBe(
			'/static/model-icons/copilot-color.svg'
		);
	});

	it('ai21labs/* should use ai21 icon (even with connection label)', () => {
		const model = {
			id: 'ai21labs/jamba-1.5-large-instruct',
			name: 'ai21labs/jamba-1.5-large-instruct | 英伟达'
		};
		expect(resolveModelIcon(model as any)).toBe('/static/model-icons/ai21.svg');
	});

	it('bytedance/doubao-* should prefer doubao icon over bytedance', () => {
		expect(resolveModelIcon({ id: 'bytedance/doubao-seed-1.8' } as any)).toBe(
			'/static/model-icons/doubao-color.svg'
		);
	});

	it('writer/* should map to AWS icon (using nova)', () => {
		expect(resolveModelIcon({ id: 'writer/palmyra-x5' } as any)).toBe(
			'/static/model-icons/aws-color.svg'
		);
	});

	it('xiaomi/* should use xiaomimimo icon', () => {
		expect(resolveModelIcon({ id: 'xiaomi/mimo-v2-flash' } as any)).toBe(
			'/static/model-icons/xiaomimimo.svg'
		);
	});

	it('tencent/hunyuan-* should use hunyuan icon', () => {
		expect(resolveModelIcon({ id: 'tencent/hunyuan-a13b-instruct' } as any)).toBe(
			'/static/model-icons/hunyuan-color.svg'
		);
	});

	it('inclusion-ling should resolve to inclusion-ling.png', () => {
		expect(resolveModelIcon({ id: 'tongyi/inclusion-ling' } as any)).toBe(
			'/static/model-icons/inclusion-ling.png'
		);
	});

	it('inclusionAI/* should map to inclusion-ling icon', () => {
		expect(resolveModelIcon({ id: 'inclusionAI/Ling-flash-2.0' } as any)).toBe(
			'/static/model-icons/inclusion-ling.png'
		);
	});

	it('IndexTeam/* should fall back to connection icon (siliconcloud)', () => {
		expect(
			resolveModelIcon({ id: 'IndexTeam/IndexTTS-2', connection_name: '硅基流动' } as any)
		).toBe('/static/model-icons/siliconcloud-color.svg');
	});

	it('openrouter nested baai model should still use baai icon (not openrouter)', () => {
		expect(resolveModelIcon({ id: 'openrouter/baai/bge-m3' } as any)).toBe(
			'/static/model-icons/baai.svg'
		);
	});

	it('connection-prefixed baai token should still resolve baai icon (openai.baai/...)', () => {
		expect(resolveModelIcon({ id: 'openai.baai/bge-m3' } as any)).toBe(
			'/static/model-icons/baai.svg'
		);
	});

	it('bare bge-* model id should still resolve to baai icon', () => {
		expect(resolveModelIcon({ id: 'bge-reranker-v2-m3' } as any)).toBe(
			'/static/model-icons/baai.svg'
		);
	});

	it('deepcogito/* should use deepcogito icon', () => {
		expect(resolveModelIcon({ id: 'deepcogito/cogito-v2-preview-llama-70b' } as any)).toBe(
			'/static/model-icons/deepcogito-color.svg'
		);
	});

	it('liquid/* should use liquid icon', () => {
		expect(resolveModelIcon({ id: 'liquid/lfm2-2.6b' } as any)).toBe(
			'/static/model-icons/liquid.svg'
		);
	});

	it('netease-youdao/* should use netease-youdao icon', () => {
		expect(resolveModelIcon({ id: 'netease-youdao/bce-embedding-base_v1' } as any)).toBe(
			'/static/model-icons/netease-youdao.svg'
		);
	});

	it('stepfun-ai/* should use stepfun icon', () => {
		expect(resolveModelIcon({ id: 'stepfun-ai/step3' } as any)).toBe(
			'/static/model-icons/stepfun-color.svg'
		);
	});

	it('nousresearch/* should use nous icon', () => {
		expect(resolveModelIcon({ id: 'nousresearch/deephermes-3-mistral-24b-preview' } as any)).toBe(
			'/static/model-icons/noushermes.svg'
		);
	});

	it('unknown openrouter model falls back to openrouter icon', () => {
		expect(resolveModelIcon({ id: 'some-unknown-model', owned_by: 'openrouter' } as any)).toBe(
			'/static/model-icons/openrouter.svg'
		);
	});

	it('no match returns null', () => {
		expect(resolveModelIcon({ id: 'some-totally-unknown-model' } as any)).toBeNull();
	});
});

describe('applyModelIcon', () => {
	it('should set profile_image_url in meta', () => {
		const model = {
			id: 'openai/gpt-4.1-mini',
			meta: { profile_image_url: '/static/favicon.png' }
		};
		const result = applyModelIcon(model as any);
		expect(result.meta?.profile_image_url).toBe('/static/model-icons/gpt-4.1-mini.png');
	});

	it('should override existing local icon with resolved one', () => {
		const model = {
			id: 'openai/gpt-4o-2024-05-13',
			meta: { profile_image_url: '/static/model-icons/openai.svg' }
		};
		const result = applyModelIcon(model as any);
		expect(result.meta?.profile_image_url).toBe('/static/model-icons/gpt-4o.png');
	});

	it('should preserve user custom icon (data: URL)', () => {
		const model = {
			id: 'openai/gpt-4o',
			meta: { profile_image_url: 'data:image/png;base64,abc123' }
		};
		const result = applyModelIcon(model as any);
		expect(result.meta?.profile_image_url).toBe('data:image/png;base64,abc123');
	});
});
