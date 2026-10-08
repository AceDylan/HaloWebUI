// The words a search matched, split out of its excerpt so the list can bold them
// without rendering any HTML from the chat (utils/chat_search.py builds the excerpt).
export type SnippetPart = { text: string; match: boolean };

// The text part of a search, as the server matches it: lower case, no `tag:` words.
export const searchPhrase = (raw: string): string =>
	(raw ?? '')
		.toLowerCase()
		.trim()
		.split(' ')
		.filter((word) => !word.startsWith('tag:'))
		.join(' ')
		.trim();

export const snippetParts = (snippet: string, rawSearch: string): SnippetPart[] => {
	const text = snippet ?? '';
	const phrase = searchPhrase(rawSearch);
	if (!text) return [];
	if (!phrase) return [{ text, match: false }];

	const lower = text.toLowerCase();
	const parts: SnippetPart[] = [];
	let from = 0;
	let index = lower.indexOf(phrase, from);
	while (index >= 0) {
		if (index > from) parts.push({ text: text.slice(from, index), match: false });
		parts.push({ text: text.slice(index, index + phrase.length), match: true });
		from = index + phrase.length;
		index = lower.indexOf(phrase, from);
	}
	if (from < text.length) parts.push({ text: text.slice(from), match: false });
	return parts;
};
