type History = { messages: Record<string, any>; currentId: string | null };

const equal = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

export const mergeLiveFiles = (existing: any[] = [], incoming: any[] = []) => {
	const files: any[] = [];
	const indices = new Map<string, number>();
	for (const file of [...(existing ?? []), ...(incoming ?? [])]) {
		if (!file) continue;
		const keys = [file.id && `id:${file.id}`, file.url && `url:${file.url}`].filter(Boolean);
		if (!keys.length) keys.push(JSON.stringify(file));
		const found = keys.map((key) => indices.get(key)).find((index) => index !== undefined);
		const index = found ?? files.length;
		files[index] = { ...files[index], ...file };
		for (const key of keys) indices.set(key, index);
	}
	return files;
};

// A GET may finish after a live event or a local edit. Apply only fields which
// have not changed while it was in flight, and never rewind a streaming reply.
export const reconcileChatHistory = (
	local: History,
	remote: History,
	before: History,
	previous?: History,
	mergeFiles = mergeLiveFiles
): History => {
	const messages = { ...local.messages };
	for (const id of Object.keys(previous?.messages ?? {})) {
		if (!(id in remote.messages) && equal(local.messages[id], before.messages[id]))
			delete messages[id];
	}
	for (const [id, incoming] of Object.entries(remote.messages ?? {})) {
		const current = local.messages[id];
		if (!current) {
			messages[id] = structuredClone(incoming);
			continue;
		}
		const next = { ...incoming };
		for (const key of new Set([
			...Object.keys(current),
			...Object.keys(before.messages[id] ?? {})
		])) {
			if (!equal(current[key], before.messages[id]?.[key])) {
				if (key in current) next[key] = current[key];
				else delete next[key];
			}
		}
		if (
			incoming.done !== true &&
			((current.done === true && current.completedAt != null) ||
				(current.content?.length ?? 0) > (incoming.content?.length ?? 0))
		) {
			next.content = current.content;
			next.done = current.done;
			next.completedAt = current.completedAt;
		}
		if (current.files || incoming.files) {
			next.files = equal(current.files, before.messages[id]?.files)
				? mergeFiles(current.files, incoming.files)
				: mergeFiles(incoming.files, current.files);
		}
		if (incoming.childrenIds || current.childrenIds) {
			next.childrenIds = [
				...new Set([
					...(incoming.childrenIds ?? []),
					...(current.childrenIds ?? []).filter(
						(id: string) => messages[id] && !remote.messages[id]
					)
				])
			];
		}
		messages[id] = next;
	}

	// Follow appended turns, but keep the branch the reader selected locally.
	let currentId = local.currentId && messages[local.currentId] ? local.currentId : null;
	let cursor = remote.currentId;
	const seen = new Set<string>();
	while (cursor && !seen.has(cursor)) {
		if (!currentId || cursor === currentId) {
			if (local.currentId === before.currentId) currentId = remote.currentId;
			break;
		}
		seen.add(cursor);
		cursor = messages[cursor]?.parentId;
	}
	return { ...local, messages, currentId };
};

// Coalesce reload bursts, retry on the next trigger after a failed request, and
// discard responses after navigation/unmount. No routing or persistence here.
export const createChatSync = <T>(options: {
	getKey: () => string | null;
	read: (signal: AbortSignal) => Promise<T>;
	apply: (value: T) => void;
	onError?: (error: unknown) => void;
	delay?: number;
}) => {
	let disposed = false;
	let running = false;
	let pending = false;
	let timer: ReturnType<typeof setTimeout> | undefined;
	let abort: AbortController | undefined;
	const request = () => {
		if (disposed || !options.getKey()) return;
		pending = true;
		if (!running && !timer) timer = setTimeout(run, options.delay ?? 100);
	};
	const run = async () => {
		timer = undefined;
		const key = options.getKey();
		if (disposed || !key) return;
		pending = false;
		running = true;
		abort = new AbortController();
		const timeout = setTimeout(() => abort?.abort(), 10000);
		try {
			const value = await options.read(abort.signal);
			if (!disposed && key === options.getKey()) options.apply(value);
		} catch (error) {
			options.onError?.(error);
		} finally {
			clearTimeout(timeout);
			abort = undefined;
			running = false;
			if (pending) request();
		}
	};
	return {
		request,
		dispose: () => {
			disposed = true;
			clearTimeout(timer);
			abort?.abort();
		}
	};
};

export const subscribeChatSync = ({
	socketStore,
	onEvent,
	refresh,
	window,
	document
}: {
	socketStore: { subscribe: (callback: (socket: any) => void) => () => void };
	onEvent: (event: any, callback?: any) => void;
	refresh: () => void;
	window: EventTarget;
	document: EventTarget & { visibilityState: string };
}) => {
	let socket: any;
	const resume = () => {
		if (document.visibilityState === 'visible') refresh();
	};
	const unsubscribe = socketStore.subscribe((next) => {
		if (socket === next) return;
		socket?.off('chat-events', onEvent);
		socket?.off('connect', resume);
		socket = next;
		socket?.on('chat-events', onEvent);
		socket?.on('connect', resume);
		resume();
	});
	const events = ['focus', 'online', 'pageshow'];
	for (const event of events) window.addEventListener(event, resume);
	document.addEventListener('visibilitychange', resume);
	const interval = setInterval(resume, 15000);
	return () => {
		clearInterval(interval);
		unsubscribe();
		socket?.off('chat-events', onEvent);
		socket?.off('connect', resume);
		for (const event of events) window.removeEventListener(event, resume);
		document.removeEventListener('visibilitychange', resume);
	};
};

export const createEventDeduplicator = (limit = 2048) => {
	const seen = new Set<string>();
	return (id?: string) => {
		if (!id) return true; // Compatibility with older servers.
		if (seen.has(id)) return false;
		seen.add(id);
		if (seen.size > limit) seen.delete(seen.values().next().value!);
		return true;
	};
};
