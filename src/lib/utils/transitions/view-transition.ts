// While a view transition runs, the browser paints snapshots over the live page and only takes
// them away once every transition animation has finished. If those animations never advance,
// the snapshot stays: in the Hub frame a chat opened from 讨论台 / 协作台 showed the old page's
// composer and nothing else, every chat opened after it the same, until a reload — though the
// page underneath had loaded. So a transition that does not end on its own is cut short.

type ViewTransitionLike = {
	ready: Promise<unknown>;
	finished: Promise<unknown>;
	skipTransition: () => void;
};

/** After the animations start: the longest of them (page change, theme reveal) is 560ms. */
export const VIEW_TRANSITION_SETTLE_MS = 1200;
/** From the start, in case the animations never start at all. */
export const VIEW_TRANSITION_MAX_MS = 3000;

export const guardViewTransition = <T extends ViewTransitionLike>(
	transition: T,
	{
		settleMs = VIEW_TRANSITION_SETTLE_MS,
		maxMs = VIEW_TRANSITION_MAX_MS,
		onGiveUp
	}: { settleMs?: number; maxMs?: number; onGiveUp?: () => void } = {}
): T => {
	let over = false;
	const timers: ReturnType<typeof setTimeout>[] = [];
	const end = () => {
		over = true;
		timers.forEach(clearTimeout);
	};
	const giveUp = () => {
		if (over) return;
		end();
		onGiveUp?.();
		try {
			transition.skipTransition();
		} catch {
			// already over
		}
	};
	timers.push(setTimeout(giveUp, maxMs));
	transition.ready.then(
		() => {
			if (!over) timers.push(setTimeout(giveUp, settleMs));
		},
		() => {}
	);
	transition.finished.catch(() => {}).finally(end);
	return transition;
};
