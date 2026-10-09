// Answers to the same question, including versions made by editing that question.
// Reading a comparison must never change which branch the chat has selected.
export type CompareMessage = {
	id: string;
	role: string;
	parentId?: string | null;
	childrenIds?: string[];
	content?: string;
	model?: string;
	modelName?: string;
	done?: boolean;
	[key: string]: unknown;
};

export type CompareHistory = { messages: Record<string, CompareMessage>; currentId?: string };
export type BranchAnswer = { message: CompareMessage; prompt: CompareMessage | undefined };

export const chatAnswers = (history: CompareHistory): BranchAnswer[] =>
	Object.values(history?.messages ?? {})
		.filter((message) => message.role === 'assistant' && !!message.content?.trim())
		.map((message) => ({ message, prompt: history.messages[message.parentId ?? ''] }));

export const branchAnswers = (history: CompareHistory, messageId: string): BranchAnswer[] => {
	const messages = history?.messages ?? {};
	const selected = messages[messageId];
	if (!selected) return [];
	const prompt = selected.role === 'user' ? selected : messages[selected.parentId ?? ''];
	if (!prompt || prompt.role !== 'user') return [];
	const parentId = prompt.parentId ?? null;
	const promptIds = parentId
		? (messages[parentId]?.childrenIds ?? [prompt.id])
		: Object.values(messages)
				.filter((m) => m.role === 'user' && !m.parentId)
				.map((m) => m.id);
	const seen = new Set<string>();
	return promptIds.flatMap((id) => {
		const question = messages[id];
		if (!question || question.role !== 'user' || (question.parentId ?? null) !== parentId)
			return [];
		return (question.childrenIds ?? []).flatMap((answerId) => {
			const message = messages[answerId];
			if (!message || message.role !== 'assistant' || message.parentId !== id || seen.has(answerId))
				return [];
			seen.add(answerId);
			return [{ message, prompt: question }];
		});
	});
};

export const comparisonPair = (answers: BranchAnswer[], messageId: string): [string, string] => {
	const current =
		answers.find((a) => a.message.id === messageId) ??
		answers.find((a) => a.prompt?.id === messageId) ??
		answers[0];
	return [
		current?.message.id ?? '',
		answers.find((a) => a.message.id !== current?.message.id)?.message.id ?? ''
	];
};

/** Ids on the branch the chat shows now (currentId up to the root), for the 当前 mark. */
export const currentPath = (history: CompareHistory): Set<string> => {
	const path = new Set<string>();
	let id = history?.currentId ?? null;
	while (id && !path.has(id)) {
		path.add(id);
		id = history.messages?.[id]?.parentId ?? null;
	}
	return path;
};
