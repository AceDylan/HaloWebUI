type ChatMessage = {
	role?: unknown;
};

export const countUserTurns = (messages: Array<ChatMessage | null | undefined> = []): number =>
	messages.filter((message) => message?.role === 'user').length;

export const isTitleGenerationMilestone = (userTurnCount: number): boolean =>
	Number.isInteger(userTurnCount) &&
	userTurnCount >= 1 &&
	(userTurnCount === 1 || userTurnCount % 3 === 0);

export const shouldRequestTitleGeneration = ({
	messages,
	isPrimaryModel,
	isTemporaryChat
}: {
	messages: Array<ChatMessage | null | undefined>;
	isPrimaryModel: boolean;
	isTemporaryChat: boolean;
}): boolean =>
	!isTemporaryChat && isPrimaryModel && isTitleGenerationMilestone(countUserTurns(messages));
