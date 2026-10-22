/**
 * 简化版图标匹配逻辑
 * 设计原则：简单、轻量、易维护
 */

import { MODEL_ICON_FILES } from './model-icons.manifest';

export const DEFAULT_MODEL_ICON = '/static/favicon.png';
const ICON_BASE = '/static/model-icons';

function normalizeKey(input: string): string {
	let s = (input ?? '').toString().toLowerCase().trim();

	// Strip surrounding quotes/backticks
	s = s.replace(/^["'`]+|["'`]+$/g, '');

	// Remove trailing bracketed suffixes repeatedly: "(free)", "（2024-05-13）", "[preview]" ...
	for (let i = 0; i < 5; i++) {
		const next = s.replace(/\s*[（(\[{【][^）)\]}】]*[）)\]}】]\s*$/g, '').trim();
		if (next === s) break;
		s = next;
	}

	// Unify separators: spaces/underscores/middle dots -> hyphen
	s = s.replace(/[·•]+/g, '-');
	s = s.replace(/[_\s]+/g, '-');
	s = s.replace(/-+/g, '-');
	s = s.replace(/^-+|-+$/g, '');

	return s;
}

// ============================================================================
// 1. 构建图标映射表（启动时执行一次）
// ============================================================================

const MODEL_ICONS = new Map<string, string>();
const PROVIDER_ICONS = new Map<string, string>();

for (const filename of MODEL_ICON_FILES) {
	const baseName = filename.replace(/\.[^.]+$/, '').trim();
	const key = normalizeKey(baseName);
	const url = `${ICON_BASE}/${encodeURIComponent(filename)}`;

	const isSvg = filename.toLowerCase().endsWith('.svg');
	const isProviderLike = isSvg || /-color$/i.test(key);

	if (isProviderLike) {
		// Vendor/provider icon (SVG or `*-color.png`)
		const providerKey = key.replace(/-color$/i, '');
		PROVIDER_ICONS.set(providerKey, url);
	}

	// Keep all raster images addressable as model icons too.
	if (!isSvg) {
		MODEL_ICONS.set(key, url);
	}
}

// Build an index for "family prefix" -> possible model icons.
// Used to map versions like `omni-moderation-2024-09-26` -> `omni-moderation-latest` (unique prefix match),
// without scanning the full set each call.
const MODEL_PREFIX_TO_KEYS = new Map<string, string[]>();
for (const key of MODEL_ICONS.keys()) {
	const parts = key.split('-').filter(Boolean);
	// Only build prefixes if it meaningfully narrows (>= 2 parts).
	for (let i = 1; i < parts.length; i++) {
		const prefix = parts.slice(0, i).join('-');
		const list = MODEL_PREFIX_TO_KEYS.get(prefix);
		if (list) list.push(key);
		else MODEL_PREFIX_TO_KEYS.set(prefix, [key]);
	}
}

// Some vendors only have a PNG in the folder; expose them as provider icons too.
// (Keeps the runtime matcher simple and avoids hardcoding URLs elsewhere.)
if (!PROVIDER_ICONS.has('zhipu') && MODEL_ICONS.has('zhipu-glm')) {
	PROVIDER_ICONS.set('zhipu', MODEL_ICONS.get('zhipu-glm')!);
}

if (!PROVIDER_ICONS.has('kimi') && MODEL_ICONS.has('kimi-color')) {
	PROVIDER_ICONS.set('kimi', MODEL_ICONS.get('kimi-color')!);
}

// InclusionAI icon is stored as a model PNG; expose as provider icon.
if (!PROVIDER_ICONS.has('inclusion') && MODEL_ICONS.has('inclusion-ling')) {
	PROVIDER_ICONS.set('inclusion', MODEL_ICONS.get('inclusion-ling')!);
}

// Tencent icon key normalization: users may provide either `hunyuan-*` or `tencent-*`.
if (!PROVIDER_ICONS.has('tencent') && PROVIDER_ICONS.has('hunyuan')) {
	PROVIDER_ICONS.set('tencent', PROVIDER_ICONS.get('hunyuan')!);
}
if (!PROVIDER_ICONS.has('hunyuan') && PROVIDER_ICONS.has('tencent')) {
	PROVIDER_ICONS.set('hunyuan', PROVIDER_ICONS.get('tencent')!);
}

// Treat Amazon Nova icon as AWS (used by Bedrock and related models).
if (!PROVIDER_ICONS.has('aws') && PROVIDER_ICONS.has('nova')) {
	PROVIDER_ICONS.set('aws', PROVIDER_ICONS.get('nova')!);
}
if (!PROVIDER_ICONS.has('amazon') && PROVIDER_ICONS.has('nova')) {
	PROVIDER_ICONS.set('amazon', PROVIDER_ICONS.get('nova')!);
}

// 厂商别名映射
const PROVIDER_ALIASES: Record<string, string> = {
	'byte-dance': 'bytedance',
	tongyi: 'qwen',
	alibaba: 'qwen',
	'01ai': 'yi',
	ai2: 'allenai',
	ai21labs: 'ai21',
	'ai21-labs': 'ai21',
	// OpenRouter org tokens vs icon filenames
	'aion-labs': 'aionlabs',
	arceeai: 'arcee',
	'arcee-ai': 'arcee',
	doubao: 'doubao',
	cogito: 'deepcogito',
	'deep-cogito': 'deepcogito',
	liquidai: 'liquid',
	'liquid-ai': 'liquid',
	nous: 'noushermes',
	nousresearch: 'noushermes',
	xiaomi: 'xiaomimimo',
	mi: 'xiaomimimo',
	aws: 'aws',
	amazon: 'aws',
	bedrock: 'aws',
	writer: 'aws',
	tencent: 'hunyuan',
	hunyuan: 'hunyuan',
	xai: 'grok',
	moonshot: 'kimi',
	anthropic: 'claude',
	typesafe: 'jev',
	microsoft: 'copilot',
	msft: 'copilot',
	azure: 'copilot',
	kwaipilot: 'kwaikat',
	kwai: 'kwaikat',
	siliconflow: 'siliconcloud',
	'stepfun-ai': 'stepfun',
	stepfunai: 'stepfun',
	inclusionai: 'inclusion',
	'inclusion-ai': 'inclusion',
	netease: 'netease-youdao',
	youdao: 'netease-youdao',
	// Chinese vendor / connection names (low-priority fallback via "| <name>")
	硅基流动: 'siliconcloud',
	英伟达: 'nvidia',
	字节跳动: 'bytedance',
	月之暗面: 'kimi',
	智谱: 'zhipu',
	阿里巴巴: 'qwen',
	通义: 'qwen',
	谷歌: 'google',
	微软: 'copilot'
};

// ============================================================================
// 2. 提取候选名称
// ============================================================================

function extractCandidates(input: string): string[] {
	if (!input) return [];

	const candidates: string[] = [];
	const raw = input.toLowerCase().trim();

	// Split "xxx | yyy" but keep both sides (right side is low-priority fallback).
	const barParts = raw
		.split('|')
		.map((s) => s.trim())
		.filter(Boolean);
	const primary = barParts[0] ?? raw;
	const secondary = barParts.slice(1);

	const push = (value: string) => {
		const key = normalizeKey(value);
		if (key) candidates.push(key);
	};

	const pushModelVariants = (modelKey: string) => {
		if (!modelKey) return;

		// Exact model token first
		push(modelKey);

		// ":" suffix (e.g. gpt-4o:extended)
		if (modelKey.includes(':') && !modelKey.includes('://')) {
			push(modelKey.split(':')[0]);
		}

		// "prefix.model" (direct-connection prefix_id) -> model
		if (/^[a-z0-9_-]+\.[a-z]/.test(modelKey) && !/\d\.\d/.test(modelKey)) {
			push(modelKey.split('.', 2)[1]);
		}

		// gpt-4o-2024-05-13 -> gpt-4o
		const noDate = modelKey.replace(/-\d{4}-\d{2}-\d{2}$/i, '');
		if (noDate !== modelKey) push(noDate);

		// gpt-4o-20240513 -> gpt-4o
		const noCompactDate = modelKey.replace(/-\d{8}$/i, '');
		if (noCompactDate !== modelKey) push(noCompactDate);

		// gpt-4o-0806 -> gpt-4o
		const noNum = modelKey.replace(/-\d{4}$/i, '');
		if (noNum !== modelKey) push(noNum);

		// Progressive shrink: a-b-c -> a-b -> a
		let reduced = modelKey;
		for (let i = 0; i < 8 && reduced.includes('-'); i++) {
			reduced = reduced.replace(/-[^-]+$/, '');
			push(reduced);
		}
	};

	const processPiece = (piece: string, withVariants: boolean) => {
		if (!piece) return;

		// "vendor: model" in display names
		if (piece.includes(':') && !piece.includes('://')) {
			const [left, ...rest] = piece.split(':');
			push(left);
			const right = rest.join(':').trim();
			if (right) push(right);
		}

		// org/model or org1/org2/model
		const pathParts = piece
			.split('/')
			.map((s) => s.trim())
			.filter(Boolean);

		const modelPart = pathParts.length > 0 ? pathParts[pathParts.length - 1] : piece;

		// Prefer the model segment over org tokens, so model-family icons (e.g. doubao-*, omni-*) win
		// even when the org token also matches a provider (e.g. bytedance/*).
		if (withVariants) pushModelVariants(normalizeKey(modelPart));

		for (const p of pathParts) {
			// Some sources prefix org with "<connection>.<org>" (e.g. "openai.baai/bge-m3").
			// Split by '.' (but avoid version-like tokens such as "gpt-4.1") and prefer the last segment first.
			if (p.includes('.') && !/\d\.\d/.test(p)) {
				const segs = p
					.split('.')
					.map((s) => s.trim())
					.filter(Boolean);
				if (segs.length > 1) {
					push(segs[segs.length - 1]);
					for (let i = 0; i < segs.length - 1; i++) push(segs[i]);
				}
			}
			push(p);
		}
	};

	processPiece(primary, true);
	for (const piece of secondary) processPiece(piece, false);

	// Dedupe but keep order (Set preserves insertion order)
	return [...new Set(candidates)].filter(Boolean);
}

// ============================================================================
// 3. 厂商模式匹配
// ============================================================================

const PROVIDER_PATTERNS: Array<[RegExp, string]> = [
	[/^(gpt-|o1-|o3-|o4-|chatgpt-|dall-e|text-embedding|text-moderation|tts-|whisper)/i, 'openai'],
	[/^claude/i, 'claude'],
	[/^gemma/i, 'gemma'],
	[/^(llama|meta-llama|codellama)/i, 'meta'],
	[/^(mistral|mixtral|codestral)/i, 'mistral'],
	[/^deepseek/i, 'deepseek'],
	[/^jev(?:$|[-_.:@])/i, 'jev'],
	[/^bge/i, 'baai'],
	[/^qwen/i, 'qwen'],
	[/^(glm|zhipu)/i, 'zhipu'],
	[/^doubao/i, 'doubao'],
	[/^bytedance/i, 'bytedance'],
	[/^ai21/i, 'ai21'],
	[/^(kimi|moonshot)/i, 'kimi'],
	[/^grok/i, 'grok'],
	[/^(cogito|deepcogito)/i, 'deepcogito'],
	[/^liquid/i, 'liquid'],
	[/^(nous|nousresearch|deephermes|hermes)/i, 'noushermes'],
	[/^(writer|palmyra)/i, 'aws'],
	[/^(xiaomi|xiaomimimo|mimo)/i, 'xiaomimimo'],
	[/^(tencent|hunyuan)/i, 'hunyuan'],
	[/^(command-|cohere)/i, 'cohere'],
	[/^flux/i, 'flux'],
	[/^midjourney/i, 'midjourney'],
	[/^sora/i, 'sora'],
	[/^minimax/i, 'minimax'],
	[/^nova/i, 'nova'],
	[/^perplexity/i, 'perplexity'],
	[/^(phi|kosmos)/i, 'copilot'],
	[/^(kat-|kwaipilot)/i, 'kwaikat']
];

function matchProvider(candidate: string): string | null {
	for (const [pattern, provider] of PROVIDER_PATTERNS) {
		if (pattern.test(candidate)) return provider;
	}
	return null;
}

function resolveProviderIcon(providerKey: string): string | null {
	const raw = normalizeKey(providerKey);
	if (!raw) return null;

	const aliased = PROVIDER_ALIASES[raw] ?? raw;

	const variants: string[] = [];
	const push = (s: string) => {
		const v = normalizeKey(s);
		if (v && !variants.includes(v)) variants.push(v);
	};

	push(aliased);
	// common org suffixes vs icon filenames: "xxx-ai", "xxx-labs"
	push(aliased.replace(/-ai$/i, ''));
	push(aliased.replace(/-labs?$/i, ''));
	// handle "aion-labs" -> "aionlabs" style differences
	push(aliased.replace(/-/g, ''));

	for (const v of variants) {
		const icon = PROVIDER_ICONS.get(v);
		if (icon) return icon;
	}

	return null;
}

// ============================================================================
// 4. Gemini 特殊处理
// ============================================================================

function resolveGeminiIcon(candidates: string[]): string | null {
	for (const c of candidates) {
		if (!c.includes('gemini')) continue;

		// nano-banana 或 image 类型
		if (/nano-?banana/.test(c) || c.includes('image')) {
			return MODEL_ICONS.get('nano-banana') ?? null;
		}

		// 根据版本号选择图标
		const match = c.match(/gemini-?(\d+)/);
		if (match) {
			const version = parseInt(match[1], 10);
			return version >= 3
				? (PROVIDER_ICONS.get('google-gemini-icon') ?? PROVIDER_ICONS.get('gemini') ?? null)
				: (PROVIDER_ICONS.get('gemini') ?? null);
		}

		return PROVIDER_ICONS.get('gemini') ?? null;
	}
	return null;
}

// ============================================================================
// 5. 核心解析函数
// ============================================================================

type ModelLike = {
	id?: string;
	name?: string;
	base_model_id?: string | null;
	owned_by?: string;
	// direct connections may attach connection name separately from display name
	connectionName?: string;
	connection_name?: string;
	originalId?: string;
	openai?: { id?: string; name?: string };
	info?: { id?: string; name?: string; meta?: { profile_image_url?: string | null } };
	meta?: { profile_image_url?: string | null };
};

export function resolveModelIcon(model?: ModelLike): string | null {
	if (!model) return null;

	// 收集所有可能的 ID 来源
	const sources = [
		model.openai?.id,
		model.originalId,
		model.id,
		model.base_model_id,
		model.name,
		model.connection_name,
		model.connectionName,
		model.info?.id,
		model.info?.name
	].filter(Boolean) as string[];

	const allCandidates = sources.flatMap(extractCandidates);
	const candidates = [...new Set(allCandidates)];

	// 1. 尝试精确匹配模型图标
	for (const c of candidates) {
		const icon = MODEL_ICONS.get(c);
		if (icon) return icon;
	}

	// 1.5 版本/日期的"族谱"匹配：优先尝试 `*-latest`，再尝试唯一前缀匹配
	for (const c of candidates) {
		const latest = MODEL_ICONS.get(`${c}-latest`);
		if (latest) return latest;

		const keys = MODEL_PREFIX_TO_KEYS.get(c);
		if (keys && keys.length === 1) {
			const icon = MODEL_ICONS.get(keys[0]);
			if (icon) return icon;
		}
	}

	// 2. Gemini 特殊处理
	const geminiIcon = resolveGeminiIcon(candidates);
	if (geminiIcon) return geminiIcon;

	// 3. 通过模式匹配找厂商
	for (const c of candidates) {
		const provider = matchProvider(c);
		if (provider) {
			const icon = resolveProviderIcon(provider);
			if (icon) return icon;
		}
	}

	// 4. 尝试直接匹配厂商名（聚合平台最后兜底）
	const AGGREGATOR_PROVIDERS = new Set(['openrouter', 'siliconcloud', 'siliconflow']);

	for (const c of candidates) {
		const aliased = PROVIDER_ALIASES[c] ?? c;
		if (AGGREGATOR_PROVIDERS.has(aliased)) continue;
		const icon = resolveProviderIcon(aliased);
		if (icon) return icon;
	}

	for (const c of candidates) {
		const aliased = PROVIDER_ALIASES[c] ?? c;
		if (!AGGREGATOR_PROVIDERS.has(aliased)) continue;
		const icon = resolveProviderIcon(aliased);
		if (icon) return icon;
	}

	// 5. owned_by / connection provider 作为最后 fallback（例如 openrouter）
	if (model.owned_by) {
		const owner = normalizeKey(model.owned_by);
		const aliased = PROVIDER_ALIASES[owner] ?? owner;
		const icon = resolveProviderIcon(aliased);
		if (icon) return icon;
	}

	return null;
}

// ============================================================================
// 6. 应用图标到模型对象
// ============================================================================

export function applyModelIcon<T extends ModelLike>(model: T): T {
	if (!model) return model;

	const existingIcon = model.info?.meta?.profile_image_url ?? model.meta?.profile_image_url ?? null;
	const hasUpstreamBaseModel = Boolean(model.base_model_id ?? model.info?.base_model_id ?? null);

	// Workspace 助手场景的头像应以用户保存的结果为准，不能在全局模型列表里
	// 又被基础模型/厂商图标重新盖掉，否则会出现侧栏头像正确、下拉列表头像错误。
	if (hasUpstreamBaseModel && existingIcon && existingIcon !== DEFAULT_MODEL_ICON) {
		return model;
	}

	// 保留用户自定义图标（data URL, blob, cache）
	const isUserCustom =
		existingIcon &&
		existingIcon !== DEFAULT_MODEL_ICON &&
		(existingIcon.startsWith('data:') ||
			existingIcon.startsWith('blob:') ||
			existingIcon.startsWith('/cache/') ||
			existingIcon.startsWith('/api/v1/files/'));

	if (isUserCustom) return model;

	const resolved = resolveModelIcon(model);
	const finalIcon = resolved ?? existingIcon ?? null;

	if (!finalIcon) return model;

	// 设置图标
	if (model.meta) {
		model.meta.profile_image_url = finalIcon;
	} else {
		model.meta = { profile_image_url: finalIcon };
	}

	if (model.info?.meta) {
		model.info.meta.profile_image_url = finalIcon;
	} else if (model.info) {
		model.info.meta = { profile_image_url: finalIcon };
	}

	return model;
}

export function applyModelIcons<T extends ModelLike>(
	models: T[] | null | undefined
): T[] | null | undefined {
	if (!Array.isArray(models)) return models;
	return models.map((m) => applyModelIcon(m));
}
