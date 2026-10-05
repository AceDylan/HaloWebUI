import { DUR, prefersReducedMotion } from './spring';
import { warp } from '$lib/components/scifi/scifi';

/** Capture geometry before the first accepted message changes the landing layout. */
export function captureFirstMessage(): (() => void) | null {
	if (typeof document === 'undefined' || document.hidden || prefersReducedMotion()) return null;
	const composer = document.querySelector<HTMLElement>('.halo-composer');
	if (!composer || typeof composer.animate !== 'function') return null;
	const from = composer.getBoundingClientRect();
	warp(700);
	const hero = document.querySelector<HTMLElement>('.halo-hero');
	const ghost = hero?.cloneNode(true) as HTMLElement | undefined;
	if (ghost && hero) {
		const r = hero.getBoundingClientRect();
		ghost.removeAttribute('id');
		ghost.querySelectorAll('[id]').forEach((el) => el.removeAttribute('id'));
		ghost.setAttribute('aria-hidden', 'true');
		ghost.inert = true;
		Object.assign(ghost.style, {
			position: 'fixed',
			left: `${r.left}px`,
			top: `${r.top}px`,
			width: `${r.width}px`,
			height: `${r.height}px`,
			margin: '0',
			pointerEvents: 'none',
			zIndex: '40'
		});
		document.body.append(ghost);
		const a = ghost.animate(
			[
				{ opacity: 1, transform: 'scale(1)' },
				{ opacity: 0, transform: 'scale(.975)' }
			],
			{ duration: 240, easing: 'ease-out', fill: 'forwards' }
		);
		a.finished.catch(() => {}).finally(() => ghost.remove());
	}
	return () => {
		const next = document.querySelector<HTMLElement>('.halo-composer');
		if (!next || document.hidden) return;
		const to = next.getBoundingClientRect();
		if (!to.width || !to.height) return;
		const easing =
			getComputedStyle(document.documentElement).getPropertyValue('--spring-gentle').trim() ||
			'cubic-bezier(.16,1,.3,1)';
		const message = document.querySelector<HTMLElement>('.user-message');
		message?.animate(
			[
				{ opacity: 0, transform: 'translateY(8px)' },
				{ opacity: 1, transform: 'none' }
			],
			{ duration: 160, easing: 'ease-out' }
		);
		next.animate(
			[
				{
					transformOrigin: 'top left',
					transform: `translate(${from.left - to.left}px,${from.top - to.top}px) scale(${from.width / to.width},${from.height / to.height})`
				},
				{ transformOrigin: 'top left', transform: 'none' }
			],
			{ duration: DUR.hero, easing }
		);
	};
}
