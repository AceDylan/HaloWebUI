/** Stable identity for current prompts and legacy command-only records. */
export const chatPromptKey = (prompt: { id?: string; command?: string }) =>
	prompt.id ? `id:${prompt.id}` : `command:${(prompt.command ?? '').replace(/^\//, '')}`;

/** Saved IDs come first; new items retain their source order at the end. */
export const orderPrompts = <T>(items: T[], savedOrder: unknown, key: (item: T) => string): T[] => {
	const ids = Array.isArray(savedOrder)
		? [...new Set(savedOrder.filter((id): id is string => typeof id === 'string' && id !== ''))]
		: [];
	const positions = new Map(ids.map((id, index) => [id, index]));
	return [...items].sort(
		(a, b) => (positions.get(key(a)) ?? ids.length) - (positions.get(key(b)) ?? ids.length)
	);
};

/** Reorder the complete visible list, also pruning deleted/unavailable IDs. */
export const movePrompt = (ids: string[], id: string, target: number): string[] => {
	const next = [...new Set(ids)];
	const from = next.indexOf(id);
	if (from < 0 || target < 0 || target >= next.length) return next;
	next.splice(from, 1);
	next.splice(target, 0, id);
	return next;
};
