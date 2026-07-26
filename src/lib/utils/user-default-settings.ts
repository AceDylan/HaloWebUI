import type { NewUserDefaultSettingsPayload } from '$lib/apis/users';
import { normalizeHtmlVisualMode, type HtmlVisualMode } from '$lib/utils/html-visual-mode';

type UserDefaultUiTemplate = {
	models: string[];
	showFeaturedAssistantsOnHome: boolean;
	showChatTitleInTab: boolean;
	chatBubble: boolean;
	showUsername: boolean;
	widescreenMode: boolean;
	notificationSound: boolean;
	enableAutoScrollOnStreaming: boolean;
	richTextInput: boolean;
	promptAutocomplete: boolean;
	showFormattingToolbar: boolean;
	insertPromptAsRichText: boolean;
	largeTextAsFile: boolean;
	copyFormatted: boolean;
	copyFormattedUserSet: boolean;
	ctrlEnterToSend: boolean;
	system: string;
	title: { auto: boolean };
	autoTags: boolean;
	autoFollowUps: boolean;
	detectArtifacts: boolean;
	svgPreviewAutoOpen: boolean;
	htmlVisualArtifacts: HtmlVisualMode;
	hideHtmlArtifactCodeBlocks: boolean;
	responseAutoCopy: boolean;
	temporaryChatByDefault: boolean;
	newChatInheritsPreviousState: boolean;
	collapseCodeBlocks: boolean;
	collapseHistoricalLongResponses: boolean;
	showInlineCitations: boolean;
	showMessageOutline: boolean;
	expandDetails: boolean;
	insertSuggestionPrompt: boolean;
	keepFollowUpPrompts: boolean;
	insertFollowUpPrompt: boolean;
	displayMultiModelResponsesInTabs: boolean;
	showFloatingActionButtons: boolean;
	floatingActionButtons:
		| {
				id: string;
				label: string;
				input: boolean;
				prompt: string;
		  }[]
		| null;
};

export type UserDefaultUiBoolKey = {
	[K in keyof UserDefaultUiTemplate]: UserDefaultUiTemplate[K] extends boolean ? K : never;
}[keyof UserDefaultUiTemplate];

export const DEFAULT_USER_DEFAULT_UI_TEMPLATE: UserDefaultUiTemplate = {
	models: [],
	showFeaturedAssistantsOnHome: true,
	showChatTitleInTab: true,
	chatBubble: true,
	showUsername: false,
	widescreenMode: false,
	notificationSound: true,
	enableAutoScrollOnStreaming: true,
	richTextInput: true,
	promptAutocomplete: false,
	showFormattingToolbar: false,
	insertPromptAsRichText: false,
	largeTextAsFile: false,
	copyFormatted: true,
	copyFormattedUserSet: false,
	ctrlEnterToSend: false,
	system: '',
	title: { auto: true },
	autoTags: true,
	autoFollowUps: true,
	detectArtifacts: true,
	svgPreviewAutoOpen: true,
	htmlVisualArtifacts: 'force',
	hideHtmlArtifactCodeBlocks: true,
	responseAutoCopy: false,
	temporaryChatByDefault: false,
	newChatInheritsPreviousState: false,
	collapseCodeBlocks: false,
	collapseHistoricalLongResponses: true,
	showInlineCitations: true,
	showMessageOutline: true,
	expandDetails: false,
	insertSuggestionPrompt: false,
	keepFollowUpPrompts: false,
	insertFollowUpPrompt: false,
	displayMultiModelResponsesInTabs: false,
	showFloatingActionButtons: true,
	floatingActionButtons: null
};

const UI_BOOL_KEYS: UserDefaultUiBoolKey[] = [
	'showFeaturedAssistantsOnHome',
	'showChatTitleInTab',
	'chatBubble',
	'showUsername',
	'widescreenMode',
	'notificationSound',
	'enableAutoScrollOnStreaming',
	'richTextInput',
	'promptAutocomplete',
	'showFormattingToolbar',
	'insertPromptAsRichText',
	'largeTextAsFile',
	'copyFormatted',
	'copyFormattedUserSet',
	'ctrlEnterToSend',
	'autoTags',
	'autoFollowUps',
	'detectArtifacts',
	'svgPreviewAutoOpen',
	'hideHtmlArtifactCodeBlocks',
	'responseAutoCopy',
	'temporaryChatByDefault',
	'newChatInheritsPreviousState',
	'collapseCodeBlocks',
	'collapseHistoricalLongResponses',
	'showInlineCitations',
	'showMessageOutline',
	'expandDetails',
	'insertSuggestionPrompt',
	'keepFollowUpPrompts',
	'insertFollowUpPrompt',
	'displayMultiModelResponsesInTabs',
	'showFloatingActionButtons'
];

const UI_STRING_KEYS = ['system'];

const UI_ARRAY_KEYS = ['models'];

const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value));
const asRecord = (value: unknown): Record<string, any> =>
	value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, any>) : {};

const isEqual = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

export const createEmptyNewUserDefaultSettings = (): NewUserDefaultSettingsPayload => ({
	configured: false,
	enabled: false,
	roles: ['user', 'pending'],
	ui: {},
	tools: { native_tools: {} }
});

export const normalizeNewUserDefaultSettings = (
	value: Partial<NewUserDefaultSettingsPayload> | null | undefined
) => {
	const raw = asRecord(value);
	const rawUi = asRecord(raw.ui);
	const defaults = clone(DEFAULT_USER_DEFAULT_UI_TEMPLATE);

	return {
		configured: Boolean(raw.configured),
		enabled: Boolean(raw.enabled),
		roles: Array.isArray(raw.roles)
			? raw.roles.filter((role: unknown) => role === 'user' || role === 'pending')
			: ['user', 'pending'],
		ui: {
			...defaults,
			...rawUi,
			htmlVisualArtifacts: normalizeHtmlVisualMode(rawUi.htmlVisualArtifacts),
			models: Array.isArray(rawUi.models) ? rawUi.models : [],
			title: {
				...defaults.title,
				...asRecord(rawUi.title)
			}
		},
		tools: { native_tools: {} }
	};
};

export const pickUserDefaultUiFields = (ui: Record<string, any>) => {
	const source = asRecord(ui);
	const picked: Record<string, any> = {};

	for (const key of UI_BOOL_KEYS) {
		if (typeof source[key] === 'boolean') picked[key] = source[key];
	}

	for (const key of UI_STRING_KEYS) {
		if (typeof source[key] === 'string') picked[key] = source[key];
	}

	if ('htmlVisualArtifacts' in source) {
		picked.htmlVisualArtifacts = normalizeHtmlVisualMode(source.htmlVisualArtifacts);
	}

	for (const key of UI_ARRAY_KEYS) {
		if (Array.isArray(source[key]))
			picked[key] = source[key].filter((item) => typeof item === 'string');
	}

	if (source.title && typeof source.title.auto === 'boolean') {
		picked.title = { auto: source.title.auto };
	}

	if ('floatingActionButtons' in source) {
		picked.floatingActionButtons =
			source.floatingActionButtons === null
				? null
				: Array.isArray(source.floatingActionButtons)
					? source.floatingActionButtons
					: null;
	}

	return picked;
};

export const buildNewUserDefaultSettingsPayload = (
	value: ReturnType<typeof normalizeNewUserDefaultSettings>
): NewUserDefaultSettingsPayload => {
	const pickedUi = pickUserDefaultUiFields(value.ui);
	const defaultUi = pickUserDefaultUiFields(clone(DEFAULT_USER_DEFAULT_UI_TEMPLATE));
	const ui: Record<string, any> = {};

	for (const [key, nextValue] of Object.entries(pickedUi)) {
		if (!isEqual(nextValue, defaultUi[key])) {
			ui[key] = nextValue;
		}
	}

	if ('copyFormatted' in ui) {
		ui.copyFormattedUserSet = true;
	}

	return {
		configured: Boolean(value.configured),
		enabled: Boolean(value.enabled),
		roles: value.roles.filter((role) => role === 'user' || role === 'pending'),
		ui,
		tools: { native_tools: {} }
	};
};
