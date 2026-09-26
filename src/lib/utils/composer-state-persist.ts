// Debounced saving of a chat's composer state (web search mode, tools, skills,
// image generation, reasoning) to `/chats/<id>/composer-state`.
//
// The chat id and the state are both fixed when a save is scheduled, never
// read when the timer fires. Chat.svelte schedules from a reactive block that
// also re-runs on navigation while `$chatId` still names the chat being left;
// reading the state 250 ms later picked up whatever the next chat had loaded
// (or the defaults a new chat starts with) and wrote it into the old chat.
//
// A state equal to the last one saved or loaded for that chat is not sent, so
// merely opening or leaving a chat writes nothing.

export type ComposerStateSaver = (chatId: string, payload: unknown) => Promise<unknown>;

type TimerHandle = ReturnType<typeof setTimeout>;

type PendingSave = {
	chatId: string;
	payload: unknown;
	signature: string;
	timer: TimerHandle;
};

export type ComposerStatePersister = {
	/** Record the state a chat was loaded with; an identical state is not re-sent. */
	markPersisted: (chatId: string | null | undefined, payload: unknown) => void;
	/** Save `payload` for `chatId` after the debounce delay, unless it is unchanged. */
	schedule: (chatId: string | null | undefined, payload: unknown) => void;
	/** Send a scheduled save now (e.g. before the component goes away). */
	flush: () => Promise<void>;
	/** Drop a scheduled save without sending it. */
	cancel: () => void;
	/** Settles once every save sent so far has finished. */
	idle: () => Promise<void>;
};

const signatureOf = (payload: unknown) => JSON.stringify(payload ?? null);

export const createComposerStatePersister = ({
	save,
	delayMs = 250,
	onError = (error: unknown) => console.error(error)
}: {
	save: ComposerStateSaver;
	delayMs?: number;
	onError?: (error: unknown) => void;
}): ComposerStatePersister => {
	// Last state known to be stored per chat (loaded, or sent without error).
	const stored = new Map<string, string>();
	let pending: PendingSave | null = null;
	let chain: Promise<void> = Promise.resolve();

	const send = (chatId: string, payload: unknown, signature: string) => {
		const previous = stored.get(chatId);
		// Optimistic, so a repeat of the same state while this save is in flight
		// is not queued again; rolled back when the save fails.
		stored.set(chatId, signature);
		chain = chain
			.catch(() => undefined)
			.then(async () => {
				const result = await save(chatId, payload);
				if (result === null || result === undefined) {
					throw new Error('composer state was not saved');
				}
			})
			.catch((error) => {
				if (stored.get(chatId) === signature) {
					if (previous === undefined) {
						stored.delete(chatId);
					} else {
						stored.set(chatId, previous);
					}
				}
				onError(error);
			});
		return chain;
	};

	const flush = () => {
		if (!pending) {
			return chain;
		}
		const { chatId, payload, signature, timer } = pending;
		pending = null;
		clearTimeout(timer);
		return send(chatId, payload, signature);
	};

	const cancel = () => {
		if (pending) {
			clearTimeout(pending.timer);
			pending = null;
		}
	};

	return {
		markPersisted(chatId, payload) {
			if (!chatId) return;
			stored.set(chatId, signatureOf(payload));
		},
		schedule(chatId, payload) {
			if (!chatId) return;
			const signature = signatureOf(payload);

			if (pending && pending.chatId !== chatId) {
				// A change made in the chat being left still belongs to that chat.
				void flush();
			}
			cancel();

			if (stored.get(chatId) === signature) {
				return;
			}

			// Snapshot: arrays/objects in the payload must not change under the timer.
			const snapshot = JSON.parse(signature);
			pending = {
				chatId,
				payload: snapshot,
				signature,
				timer: setTimeout(() => {
					void flush();
				}, delayMs)
			};
		},
		flush,
		cancel,
		idle: () => chain
	};
};
