/**
 * Render-time safety net for fragmented reasoning output.
 *
 * Some upstream providers/proxies mirror each thinking token into both the
 * `content` and `reasoning_content` fields of every streamed delta. The backend
 * already drops the exact echo, but a render-side fallback keeps the UI sane for
 * any provider whose echo isn't byte-identical: it collapses a run of adjacent
 * `<details type="reasoning">` blocks into a single block, dropping only the
 * whitespace / echoed text that sits between them. Real answer text between two
 * reasoning blocks is preserved, so a genuine reasoning→answer→reasoning
 * interleaving is never merged.
 */

const REASONING_BLOCK_REGEX =
	/<details\b(?=[^>]*\btype=["']reasoning["'])[^>]*>[\s\S]*?<\/details>/gi;

type Segment =
	| { type: 'text'; raw: string }
	| { type: 'reasoning'; raw: string };

type ReasoningParts = {
	done: boolean;
	duration: number | null;
	inner: string;
};

/** Strip blockquote markers and collapse whitespace for echo comparison. */
const normalizeForEcho = (value: string): string =>
	value
		.replace(/<\/?summary\b[^>]*>/gi, '')
		.replace(/^\s*>+\s?/gm, '')
		.replace(/\s+/g, ' ')
		.trim();

const roundToTenth = (value: number): number => {
	const rounded = Math.round(value * 10) / 10;
	return rounded > 0 ? rounded : 0.1;
};

const splitReasoningBlock = (block: string): ReasoningParts => {
	const openTag = block.match(/^<details\b[^>]*>/i)?.[0] ?? '';
	const done = /\bdone\s*=\s*["']true["']/i.test(openTag);
	const durationMatch = openTag.match(/\bduration\s*=\s*["']([^"']+)["']/i);
	const durationValue = durationMatch ? Number(durationMatch[1]) : NaN;

	const inner = block
		.replace(/^<details\b[^>]*>/i, '')
		.replace(/<summary\b[^>]*>[\s\S]*?<\/summary>/i, '')
		.replace(/<\/details>\s*$/i, '')
		.replace(/^\s*\n/, '')
		.replace(/\n\s*$/, '');

	return {
		done,
		duration: Number.isFinite(durationValue) ? durationValue : null,
		inner
	};
};

const buildReasoningBlock = (parts: ReasoningParts): string => {
	const inner = parts.inner.trim();

	if (parts.done && parts.duration !== null) {
		const duration = roundToTenth(parts.duration);
		return `<details type="reasoning" done="true" duration="${duration}">\n<summary>Thought for ${duration} seconds</summary>\n${inner}\n</details>`;
	}

	return `<details type="reasoning" done="false">\n<summary>Thinking…</summary>\n${inner}\n</details>`;
};

const mergeParts = (a: ReasoningParts, b: ReasoningParts): ReasoningParts => {
	const inner = [a.inner.trim(), b.inner.trim()].filter(Boolean).join('\n');
	const done = a.done && b.done;

	let duration: number | null = null;
	if (a.duration !== null || b.duration !== null) {
		duration = (a.duration ?? 0) + (b.duration ?? 0);
	}

	return { done, duration, inner };
};

/**
 * The gap between two reasoning blocks is "ignorable" when it is whitespace only
 * or when its visible text is a substring of the surrounding reasoning content
 * (i.e. the provider echoed the reasoning into the answer stream).
 */
const isIgnorableGap = (gap: string, priorInner: string, nextInner: string): boolean => {
	const normalizedGap = normalizeForEcho(gap);
	if (normalizedGap === '') {
		return true;
	}

	const reference = normalizeForEcho(`${priorInner}\n${nextInner}`);
	return reference.length > 0 && reference.includes(normalizedGap);
};

/** Collapse adjacent reasoning `<details>` blocks separated by whitespace / echoed text. */
export const mergeAdjacentReasoningDetails = (content: string): string => {
	if (typeof content !== 'string' || !content) {
		return content;
	}

	// Cheap bail-out: nothing to merge unless there are at least two reasoning blocks.
	const blockCount = (content.match(/\btype=["']reasoning["']/gi) ?? []).length;
	if (blockCount < 2) {
		return content;
	}

	try {
		const segments: Segment[] = [];
		let lastIndex = 0;
		let match: RegExpExecArray | null;

		REASONING_BLOCK_REGEX.lastIndex = 0;
		while ((match = REASONING_BLOCK_REGEX.exec(content)) !== null) {
			if (match.index > lastIndex) {
				segments.push({ type: 'text', raw: content.slice(lastIndex, match.index) });
			}
			segments.push({ type: 'reasoning', raw: match[0] });
			lastIndex = match.index + match[0].length;
		}
		if (lastIndex < content.length) {
			segments.push({ type: 'text', raw: content.slice(lastIndex) });
		}

		const result: Segment[] = [];
		let merged = false;

		for (const segment of segments) {
			if (segment.type !== 'reasoning') {
				result.push(segment);
				continue;
			}

			// Look back for a reasoning block, tolerating one text gap in between.
			let gapIndex = -1;
			let priorIndex = result.length - 1;
			if (priorIndex >= 0 && result[priorIndex].type === 'text') {
				gapIndex = priorIndex;
				priorIndex -= 1;
			}

			const prior = priorIndex >= 0 ? result[priorIndex] : null;

			if (prior && prior.type === 'reasoning') {
				const priorParts = splitReasoningBlock(prior.raw);
				const currentParts = splitReasoningBlock(segment.raw);
				const gap = gapIndex >= 0 ? (result[gapIndex] as { raw: string }).raw : '';

				if (isIgnorableGap(gap, priorParts.inner, currentParts.inner)) {
					prior.raw = buildReasoningBlock(mergeParts(priorParts, currentParts));
					if (gapIndex >= 0) {
						result.splice(gapIndex, 1);
					}
					merged = true;
					continue;
				}
			}

			result.push(segment);
		}

		if (!merged) {
			return content;
		}

		return result.map((segment) => segment.raw).join('');
	} catch {
		// Never let a rendering safety net break rendering.
		return content;
	}
};
