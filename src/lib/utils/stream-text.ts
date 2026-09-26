// Fade-in of streamed text ("Fade In" / "Smooth" transition): only the
// characters that are still animating get their own <span class="stream-char">;
// the rest of the run is one plain text node. One span per character for the
// whole answer made every update re-style thousands of animated elements, and a
// long reply stuttered more the longer it got.

/** How long a character stays a span. Longer than the 280 ms stream-char animation. */
export const STREAM_CHAR_SETTLE_MS = 320;

export type StreamTextChar = { index: number; char: string };

const isHighSurrogate = (code: number) => code >= 0xd800 && code <= 0xdbff;

/** Never cut between the two halves of a surrogate pair. */
const clampToCodePoint = (text: string, index: number) => {
	const cut = Math.max(0, Math.min(index, text.length));
	return cut > 0 && cut < text.length && isHighSurrogate(text.charCodeAt(cut - 1)) ? cut - 1 : cut;
};

/** Length of the part `next` shares with `previous` from the start. */
export const commonPrefixLength = (previous: string, next: string) => {
	const limit = Math.min(previous.length, next.length);
	let index = 0;
	while (index < limit && previous.charCodeAt(index) === next.charCodeAt(index)) {
		index += 1;
	}
	return clampToCodePoint(next, index);
};

/**
 * The settled head (plain text) and the still-fading tail, one entry per code
 * point, keyed by its position so an animating character keeps its element.
 */
export const splitStreamText = (text: string, settled: number) => {
	const cut = clampToCodePoint(text, settled);
	const tail: StreamTextChar[] = [];
	let index = cut;
	for (const char of text.slice(cut)) {
		tail.push({ index, char });
		index += char.length;
	}
	return { settledText: text.slice(0, cut), tail };
};
