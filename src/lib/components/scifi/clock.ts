// hh:mm:ss for the HUD read-outs (the landing's reactor and orbit), ticking once a second while
// the tab is visible and only while something shows it.
import { readable } from 'svelte/store';

const now = () => {
	const d = new Date();
	return [d.getHours(), d.getMinutes(), d.getSeconds()].map((n) => String(n).padStart(2, '0')).join(':');
};

export const hudClock = readable('', (set) => {
	set(now());
	const id = setInterval(() => !document.hidden && set(now()), 1000);
	return () => clearInterval(id);
});
