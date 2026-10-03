// What a failed chat image says next to its error, and whether retrying
// without the reference images is worth offering.
//
// The relay in front of gpt-image (cch) rewrites many upstream 400s into its
// own "请求格式非法…" text, so the real cause is often gone by the time it
// gets here. Edits (a request with reference images) fail far more often than
// plain generations, so a hidden cause on an edit points at the references.

export type ImageGenerationErrorKind =
	| 'moderation'
	| 'quota'
	| 'rate_limit'
	| 'timeout'
	| 'reference'
	| 'relay_hidden';

const ERROR_KINDS: Array<[ImageGenerationErrorKind, RegExp]> = [
	['moderation', /safety system|moderation|content[\s_-]*policy|内容审核|违规|敏感内容/i],
	['quota', /insufficient[\s_-]*(user[\s_-]*)?quota|quota exceeded|billing|余额不足|额度不足/i],
	['rate_limit', /rate[\s_-]*limit|too many requests|请求过于频繁|\b429\b/i],
	['timeout', /timed?[\s_-]*out|timeout|超时/i],
	[
		'reference',
		/invalid[\s_-]*image|unsupported[\s_-]*(image|mime|file)|image.{0,40}(too large|format|dimension)|图片(格式|尺寸|过大|太大)/i
	],
	['relay_hidden', /请求格式非法|请求参数验证失败|缺少必需参数或包含不允许的参数/]
];

export const classifyImageGenerationError = (text: unknown): ImageGenerationErrorKind | null => {
	const value = `${text ?? ''}`;
	if (!value.trim()) return null;
	for (const [kind, pattern] of ERROR_KINDS) {
		if (pattern.test(value)) return kind;
	}
	return null;
};

type MessageLike = {
	parentId?: string | null;
	files?: unknown;
	imageReferences?: unknown;
	[key: string]: unknown;
};

const hasImageFile = (files: unknown) =>
	Array.isArray(files) &&
	files.some(
		(file) =>
			file &&
			typeof file === 'object' &&
			(file as Record<string, unknown>).type === 'image' &&
			Boolean((file as Record<string, unknown>).url || (file as Record<string, unknown>).id)
	);

/**
 * True when the image request answering `parentId` went out with source
 * images: the message's own uploads, the earlier images it kept referenced,
 * or, for a message from before references were recorded, any image earlier
 * in the conversation (the server then took the latest one).
 */
export const imageRequestHadReferences = (
	messages: Record<string, MessageLike | undefined> | null | undefined,
	parentId: string | null | undefined
): boolean => {
	const parent = parentId ? messages?.[parentId] : undefined;
	if (!parent) return false;
	if (hasImageFile(parent.files)) return true;
	if (Array.isArray(parent.imageReferences)) return parent.imageReferences.length > 0;

	const seen = new Set<string>();
	let id = parent.parentId ?? null;
	while (id && !seen.has(id)) {
		seen.add(id);
		const earlier = messages?.[id];
		if (!earlier) break;
		if (hasImageFile(earlier.files)) return true;
		id = earlier.parentId ?? null;
	}
	return false;
};
