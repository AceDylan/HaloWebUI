import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { guardViewTransition, VIEW_TRANSITION_MAX_MS, VIEW_TRANSITION_SETTLE_MS } from './index';

const fakeTransition = () => {
	let ready!: () => void;
	let finish!: () => void;
	const transition = {
		ready: new Promise<void>((resolve) => (ready = resolve)),
		finished: new Promise<void>((resolve) => (finish = resolve)),
		skipTransition: vi.fn(() => finish())
	};
	return { transition, ready, finish };
};

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe('guardViewTransition', () => {
	it('cuts short a transition whose animations started but never end', async () => {
		const { transition, ready } = fakeTransition();
		guardViewTransition(transition);
		ready();
		await vi.advanceTimersByTimeAsync(VIEW_TRANSITION_SETTLE_MS - 1);
		expect(transition.skipTransition).not.toHaveBeenCalled();
		await vi.advanceTimersByTimeAsync(1);
		expect(transition.skipTransition).toHaveBeenCalledTimes(1);
	});

	it('leaves a transition alone once it has ended by itself', async () => {
		const { transition, ready, finish } = fakeTransition();
		const onGiveUp = vi.fn();
		guardViewTransition(transition, { onGiveUp });
		ready();
		await vi.advanceTimersByTimeAsync(560);
		finish();
		await vi.advanceTimersByTimeAsync(VIEW_TRANSITION_MAX_MS * 2);
		expect(transition.skipTransition).not.toHaveBeenCalled();
		expect(onGiveUp).not.toHaveBeenCalled();
	});

	it('lets the navigation go on when the animations never start', async () => {
		const { transition } = fakeTransition();
		const onGiveUp = vi.fn();
		guardViewTransition(transition, { onGiveUp });
		await vi.advanceTimersByTimeAsync(VIEW_TRANSITION_MAX_MS);
		expect(onGiveUp).toHaveBeenCalledTimes(1);
		expect(transition.skipTransition).toHaveBeenCalledTimes(1);
	});

	it('does not throw when the transition is already over', async () => {
		const { transition, ready } = fakeTransition();
		transition.skipTransition.mockImplementation(() => {
			throw new DOMException('InvalidStateError');
		});
		guardViewTransition(transition);
		ready();
		await expect(vi.advanceTimersByTimeAsync(VIEW_TRANSITION_SETTLE_MS)).resolves.not.toThrow();
	});
});
