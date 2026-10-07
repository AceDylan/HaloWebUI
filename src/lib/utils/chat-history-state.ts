export type ChatHistoryState = {
	currentId?: string | null;
	messages?: Record<string, unknown> | null;
} | null | undefined;

/** Whether the history has a message that can actually be rendered. */
export const hasRenderableChatHistory = (history: ChatHistoryState): boolean => {
	const currentId = history?.currentId;
	return Boolean(currentId && history?.messages?.[currentId]);
};
