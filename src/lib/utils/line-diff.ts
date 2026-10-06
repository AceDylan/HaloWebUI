/** A line of a two-text comparison: in both, only in the old text, or only in the new one. */
export type DiffLine = { type: 'same' | 'del' | 'add'; text: string };

// Past this many cells (old lines × new lines) the LCS table is skipped and the texts are shown
// as one block removed and one added; system prompts are capped at 8000 characters, far below.
const MAX_CELLS = 4_000_000;

const splitLines = (text: string): string[] => {
	const normalized = String(text ?? '').replace(/\r\n/g, '\n');
	return normalized === '' ? [] : normalized.split('\n');
};

/** Line diff of `before` → `after` by longest common subsequence. Removed lines come before the
 * lines added in their place. */
export const lineDiff = (before: string, after: string): DiffLine[] => {
	const a = splitLines(before);
	const b = splitLines(after);

	// Common head and tail need no table.
	let start = 0;
	while (start < a.length && start < b.length && a[start] === b[start]) start++;
	let endA = a.length;
	let endB = b.length;
	while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) {
		endA--;
		endB--;
	}

	const head: DiffLine[] = a.slice(0, start).map((text) => ({ type: 'same', text }));
	const tail: DiffLine[] = a.slice(endA).map((text) => ({ type: 'same', text }));
	const midA = a.slice(start, endA);
	const midB = b.slice(start, endB);
	const n = midA.length;
	const m = midB.length;

	if (n * m > MAX_CELLS) {
		return [
			...head,
			...midA.map((text) => ({ type: 'del' as const, text })),
			...midB.map((text) => ({ type: 'add' as const, text })),
			...tail
		];
	}

	// lcs[i][j] = LCS length of midA[i..] and midB[j..]
	const width = m + 1;
	const lcs = new Uint32Array((n + 1) * width);
	for (let i = n - 1; i >= 0; i--) {
		for (let j = m - 1; j >= 0; j--) {
			lcs[i * width + j] =
				midA[i] === midB[j]
					? lcs[(i + 1) * width + j + 1] + 1
					: Math.max(lcs[(i + 1) * width + j], lcs[i * width + j + 1]);
		}
	}

	const middle: DiffLine[] = [];
	let i = 0;
	let j = 0;
	while (i < n && j < m) {
		if (midA[i] === midB[j]) {
			middle.push({ type: 'same', text: midA[i] });
			i++;
			j++;
		} else if (lcs[(i + 1) * width + j] >= lcs[i * width + j + 1]) {
			middle.push({ type: 'del', text: midA[i++] });
		} else {
			middle.push({ type: 'add', text: midB[j++] });
		}
	}
	while (i < n) middle.push({ type: 'del', text: midA[i++] });
	while (j < m) middle.push({ type: 'add', text: midB[j++] });

	return [...head, ...middle, ...tail];
};

/** How many lines were removed and added. */
export const diffStats = (lines: DiffLine[]) => ({
	added: lines.filter((line) => line.type === 'add').length,
	removed: lines.filter((line) => line.type === 'del').length
});
