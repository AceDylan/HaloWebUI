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
/** How long a transition's animations get to move before they are called stuck. */
export const VIEW_TRANSITION_STALL_MS = 400;
/** From the start, in case the animations never start at all. */
export const VIEW_TRANSITION_MAX_MS = 3000;

/** The transition's own animations, if this browser can list them. */
const viewTransitionAnimations = (): Animation[] => {
	if (typeof document === 'undefined' || typeof document.getAnimations !== 'function') return [];
	try {
		return document
			.getAnimations()
			.filter((animation) => String(animation.effect?.pseudoElement ?? '').includes('view-transition'));
	} catch {
		return [];
	}
};

/** Where the transition's animations are now (null while an animation has no time yet). */
const animationTimes = (): (number | null)[] =>
	viewTransitionAnimations().map((animation) => animation.currentTime);

/** Handed to the browser and then not moving: the page underneath stays hidden at the animation's
 *  first frame (a nearly invisible page). It is not going to play. */
const animationsStalled = (since: (number | null)[]): boolean => {
	const now = animationTimes();
	return now.length > 0 && now.every((time, index) => time === since[index]);
};

export const guardViewTransition = <T extends ViewTransitionLike>(
	transition: T,
	{
		settleMs = VIEW_TRANSITION_SETTLE_MS,
		maxMs = VIEW_TRANSITION_MAX_MS,
		stallMs = VIEW_TRANSITION_STALL_MS,
		onGiveUp
	}: { settleMs?: number; maxMs?: number; stallMs?: number; onGiveUp?: () => void } = {}
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
		// A transition that did not end on its own is a bug worth seeing in the console: the page
		// change, the sign-in hand-off and the theme reveal all rely on this ending.
		console.warn('[halo] view transition did not finish; skipped so the page shows');
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
			if (over) return;
			// Started but not moving: the reader is looking at the first frame of an animation
			// that never plays (the page looks empty). Show the page instead of waiting it out.
			const started = animationTimes();
			timers.push(setTimeout(() => animationsStalled(started) && giveUp(), stallMs));
			timers.push(setTimeout(giveUp, settleMs));
		},
		() => {}
	);
	transition.finished.catch(() => {}).finally(end);
	return transition;
};
