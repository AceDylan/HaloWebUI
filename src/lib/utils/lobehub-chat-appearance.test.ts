import { describe, expect, it } from 'vitest';

import {
	DEFAULT_CHAT_TRANSITION_MODE,
	DEFAULT_MERMAID_THEME,
	createMermaidConfig,
	resolveChatTransitionMode
} from './lobehub-chat-appearance';

describe('resolveChatTransitionMode', () => {
	it('prefers the explicit transition mode', () => {
		expect(resolveChatTransitionMode({ transitionMode: 'smooth', chatFadeStreamingText: false })).toBe(
			'smooth'
		);
	});

	it('maps legacy enabled fade toggle to fadeIn', () => {
		expect(resolveChatTransitionMode({ chatFadeStreamingText: true })).toBe('fadeIn');
	});

	it('maps legacy disabled fade toggle to none', () => {
		expect(resolveChatTransitionMode({ chatFadeStreamingText: false })).toBe('none');
	});

	it('falls back to the default mode when no value is present', () => {
		expect(resolveChatTransitionMode({})).toBe(DEFAULT_CHAT_TRANSITION_MODE);
	});
});

describe('createMermaidConfig', () => {
	it('draws labels as SVG text so the svg sanitizer keeps them', () => {
		// DOMPurify's svg profile (SVGPanZoom) drops <foreignObject>, where HTML labels live.
		for (const isDark of [false, true]) {
			expect(createMermaidConfig(DEFAULT_MERMAID_THEME, isDark).htmlLabels).toBe(false);
			expect(createMermaidConfig('forest', isDark).htmlLabels).toBe(false);
		}
	});
});
