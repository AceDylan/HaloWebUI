// How full a chat's context is: what the next request will carry against what
// the model takes. The count comes from the last reply's usage (what the
// provider actually billed for the conversation so far) plus anything sent
// after it; a chat without usage falls back to counting characters.

export type ContextWindowSource = 'model' | 'family' | 'default';

export type ContextUsage = {
	tokens: number;
	window: number;
	ratio: number;
	// The count came from characters, not from a reply's usage.
	estimated: boolean;
	windowSource: ContextWindowSource;
};

export const DEFAULT_CONTEXT_WINDOW = 128_000;
// The ring turns amber, then red; at NOTICE the chat suggests 总结后在新对话继续.
export const CONTEXT_WARN_RATIO = 0.6;
export const CONTEXT_NOTICE_RATIO = 0.8;
export const CONTEXT_FULL_RATIO = 0.9;

// Conservative where a family spans sizes: warning early beats a request that fails.
const FAMILY_WINDOWS: Array<[RegExp, number]> = [
	[/(^|[/:.])claude-chat$/, 1_000_000],
	[/claude/, 200_000],
	[/gemini/, 1_000_000],
	[/gpt-4\.1/, 1_000_000],
	[/gpt-5/, 400_000],
	[/(^|[/:.-])o[134](-|$)/, 200_000],
	[/gpt-4o|chatgpt-4o|gpt-4-turbo/, 128_000],
	[/gpt-3\.5/, 16_000],
	[/grok-4/, 256_000],
	[/grok/, 131_000],
	[/kimi|moonshot/, 256_000],
	[/deepseek|qwen|glm|llama|mistral|mixtral/, 128_000]
];

const positive = (value: unknown): number | null => {
	if (typeof value === 'number' && Number.isFinite(value) && value > 0) return Math.floor(value);
	if (typeof value === 'string' && /^\d+$/.test(value.trim())) {
		const parsed = Number(value.trim());
		return parsed > 0 ? parsed : null;
	}
	return null;
};

export const resolveContextWindow = (
	model: Record<string, any> | null | undefined
): { tokens: number; source: ContextWindowSource } => {
	const declared = [
		model?.info?.meta?.context_window,
		model?.info?.meta?.context_length,
		model?.info?.params?.num_ctx,
		model?.context_window,
		model?.context_length,
		model?.top_provider?.context_length,
		model?.openai?.context_length
	]
		.map(positive)
		.find((value) => value !== null);
	if (declared) return { tokens: declared, source: 'model' };

	const ids = [
		model?.original_id,
		model?.model_id,
		model?.model_ref?.model_id,
		model?.info?.base_model_id,
		model?.id,
		model?.name
	]
		.filter((value): value is string => typeof value === 'string' && value.trim() !== '')
		.map((value) => value.trim().toLowerCase());
	for (const id of ids) {
		const family = FAMILY_WINDOWS.find(([pattern]) => pattern.test(id));
		if (family) return { tokens: family[1], source: 'family' };
	}
	return { tokens: DEFAULT_CONTEXT_WINDOW, source: 'default' };
};

const CJK_RE = /[぀-ヿ㐀-䶿一-鿿가-힯＀-￯]/g;
const DETAILS_RE = /<details\b[^>]*>[\s\S]*?<\/details>/gi;

// Same rough count as backend/open_webui/utils/chat_handoff.py.
export const estimateTokens = (text: string): number => {
	if (!text) return 0;
	const cjk = text.match(CJK_RE)?.length ?? 0;
	return cjk + Math.floor((text.length - cjk + 3) / 4);
};

const messageText = (message: Record<string, any>): string => {
	const content = message?.content;
	const text =
		typeof content === 'string'
			? content
			: Array.isArray(content)
				? content
						.map((part) => (typeof part?.text === 'string' ? part.text : ''))
						.join('\n')
				: '';
	return text.replace(DETAILS_RE, '');
};

// Tokens the conversation up to this reply takes in the next request. Its
// reasoning is not sent back, so it does not count.
const usageTokens = (usage: unknown): number | null => {
	if (!usage || typeof usage !== 'object') return null;
	const data = usage as Record<string, any>;
	const input = positive(data.prompt_tokens) ?? positive(data.input_tokens);
	const output = positive(data.completion_tokens) ?? positive(data.output_tokens) ?? 0;
	if (input === null) return null;
	const cached =
		(positive(data.cache_read_input_tokens) ?? 0) + (positive(data.cache_creation_input_tokens) ?? 0);
	const reasoning = positive(data.completion_tokens_details?.reasoning_tokens) ?? 0;
	return input + cached + Math.max(0, output - reasoning);
};

export const computeContextUsage = (
	history: { currentId?: string | null; messages?: Record<string, any> } | null | undefined,
	windowTokens: number,
	windowSource: ContextWindowSource = 'default'
): ContextUsage | null => {
	const messages = history?.messages ?? {};
	const branch: Record<string, any>[] = [];
	const seen = new Set<string>();
	let id = history?.currentId ?? null;
	while (id && !seen.has(id) && messages[id]) {
		seen.add(id);
		branch.push(messages[id]);
		id = messages[id].parentId ?? null;
	}
	if (branch.length === 0 || !(windowTokens > 0)) return null;

	// branch is newest first: count what came after the newest reply with usage.
	let tokens = 0;
	let estimated = true;
	for (const message of branch) {
		const fromUsage = message?.role === 'assistant' ? usageTokens(message.usage) : null;
		if (fromUsage !== null) {
			tokens += fromUsage;
			estimated = false;
			break;
		}
		tokens += estimateTokens(messageText(message));
	}

	return {
		tokens,
		window: windowTokens,
		ratio: tokens / windowTokens,
		estimated,
		windowSource
	};
};

const compact = (value: number, digits: number) => `${Number(value.toFixed(digits))}`;

export const formatTokenCount = (tokens: number): string => {
	if (tokens >= 1_000_000) return `${compact(tokens / 1_000_000, tokens >= 10_000_000 ? 0 : 1)}M`;
	if (tokens >= 1_000) return `${compact(tokens / 1_000, tokens >= 100_000 ? 0 : 1)}k`;
	return `${tokens}`;
};
