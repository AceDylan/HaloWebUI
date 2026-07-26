import { describe, expect, it } from 'vitest';

import {
	buildNewUserDefaultSettingsPayload,
	normalizeNewUserDefaultSettings,
	pickUserDefaultUiFields
} from './user-default-settings';

describe('user default settings helpers', () => {
	it('picks only template-safe user settings from current preferences', () => {
		const picked = pickUserDefaultUiFields({
			models: ['gpt-4o'],
			temporaryChatByDefault: true,
			showInlineCitations: false,
			system: 'You are helpful.',
			title: { auto: false, prompt: 'private title prompt' },
			imageCompressionSize: { width: 1600, height: 900 },
			highlighterTheme: 'github-dark',
			mermaidTheme: 'lobe-theme',
			chatDirection: 'RTL',
			transitionMode: 'smooth',
			textScale: 1.2,
			scrollOnBranchChange: true,
			enableMessageQueue: true,
			svgPreviewAutoOpen: false,
			htmlVisualArtifacts: 'auto',
			hideHtmlArtifactCodeBlocks: true,
			responseAutoCopy: true,
			showFormulaQuickCopyButton: true,
			regenerateMenu: true,
			renderMarkdownInPreviews: true,
			stylizedPdfExport: true,
			memory: true,
			imageCompression: true,
			imageCompressionInChannels: true,
			landingPageMode: 'chat',
			pinnedModels: ['gpt-4.1'],
			modelSelectorTagOrder: ['OpenAI'],
			connections: { openai: { OPENAI_API_KEYS: ['secret'] } },
			notifications: { webhook_url: 'https://example.test/hook' },
			userLocation: true,
			notificationEnabled: true,
			audio: {
				stt: { engine: 'web', language: 'zh-CN' },
				tts: { voice: 'personal' }
			}
		});

		expect(picked).toMatchObject({
			models: ['gpt-4o'],
			temporaryChatByDefault: true,
			showInlineCitations: false,
			svgPreviewAutoOpen: false,
			htmlVisualArtifacts: 'auto',
			hideHtmlArtifactCodeBlocks: true,
			responseAutoCopy: true,
			system: 'You are helpful.',
			title: { auto: false }
		});
		expect(picked).not.toHaveProperty('imageCompressionSize');
		expect(picked).not.toHaveProperty('highlighterTheme');
		expect(picked).not.toHaveProperty('mermaidTheme');
		expect(picked).not.toHaveProperty('chatDirection');
		expect(picked).not.toHaveProperty('transitionMode');
		expect(picked).not.toHaveProperty('textScale');
		expect(picked).not.toHaveProperty('scrollOnBranchChange');
		expect(picked).not.toHaveProperty('enableMessageQueue');
		expect(picked).not.toHaveProperty('showFormulaQuickCopyButton');
		expect(picked).not.toHaveProperty('regenerateMenu');
		expect(picked).not.toHaveProperty('renderMarkdownInPreviews');
		expect(picked).not.toHaveProperty('stylizedPdfExport');
		expect(picked).not.toHaveProperty('memory');
		expect(picked).not.toHaveProperty('imageCompression');
		expect(picked).not.toHaveProperty('imageCompressionInChannels');
		expect(picked).not.toHaveProperty('landingPageMode');
		expect(picked).not.toHaveProperty('pinnedModels');
		expect(picked).not.toHaveProperty('modelSelectorTagOrder');
		expect(picked).not.toHaveProperty('connections');
		expect(picked).not.toHaveProperty('notifications');
		expect(picked).not.toHaveProperty('userLocation');
		expect(picked).not.toHaveProperty('notificationEnabled');
		expect(picked).not.toHaveProperty('audio');
	});

	it('turns sampled preferences into a saveable draft without unsafe fields', () => {
		const draft = normalizeNewUserDefaultSettings({
			enabled: false,
			roles: ['user', 'pending'],
			ui: pickUserDefaultUiFields({
				models: ['gpt-4o'],
				temporaryChatByDefault: true,
				landingPageMode: 'chat',
				connections: { openai: { OPENAI_API_KEYS: ['secret'] } }
			}),
			tools: {
				native_tools: {
					TOOL_CALLING_MODE: 'native',
					ENABLE_WEB_SEARCH_TOOL: false
				}
			}
		});

		const payload = buildNewUserDefaultSettingsPayload(draft);

		expect(payload.ui).toEqual({
			models: ['gpt-4o'],
			temporaryChatByDefault: true
		});
		expect(payload.tools.native_tools).toEqual({});
	});

	it('preserves the configured marker for an intentionally empty preset', () => {
		const draft = normalizeNewUserDefaultSettings({
			configured: true,
			enabled: false,
			roles: ['user', 'pending'],
			ui: {},
			tools: { native_tools: {} }
		});

		const payload = buildNewUserDefaultSettingsPayload(draft);

		expect(payload).toEqual({
			configured: true,
			enabled: false,
			roles: ['user', 'pending'],
			ui: {},
			tools: { native_tools: {} }
		});
	});

	it('marks disabled formatted copy as an explicit default preference', () => {
		const draft = normalizeNewUserDefaultSettings({
			enabled: true,
			roles: ['user'],
			ui: {
				copyFormatted: false
			},
			tools: { native_tools: {} }
		});

		const payload = buildNewUserDefaultSettingsPayload(draft);

		expect(payload.ui).toEqual({
			copyFormatted: false,
			copyFormattedUserSet: true
		});
	});

	it.each([
		[true, 'force'],
		[false, 'off'],
		['auto', 'auto'],
		['force', 'force'],
		['off', 'off'],
		['unexpected', 'off']
	] as const)('migrates and preserves HTML-Visual user defaults from %s', (value, expected) => {
		const draft = normalizeNewUserDefaultSettings({
			enabled: true,
			roles: ['user'],
			ui: { htmlVisualArtifacts: value },
			tools: { native_tools: {} }
		});

		expect(draft.ui.htmlVisualArtifacts).toBe(expected);
	});

	it('uses force as the default without serializing a redundant override', () => {
		const defaultDraft = normalizeNewUserDefaultSettings({
			enabled: true,
			roles: ['user'],
			ui: {},
			tools: { native_tools: {} }
		});
		const autoDraft = normalizeNewUserDefaultSettings({
			enabled: true,
			roles: ['user'],
			ui: { htmlVisualArtifacts: 'auto' },
			tools: { native_tools: {} }
		});

		expect(defaultDraft.ui.htmlVisualArtifacts).toBe('force');
		expect(buildNewUserDefaultSettingsPayload(defaultDraft).ui).not.toHaveProperty(
			'htmlVisualArtifacts'
		);
		expect(buildNewUserDefaultSettingsPayload(autoDraft).ui.htmlVisualArtifacts).toBe('auto');
	});
});
