// Minimal browser globals for mounting Svelte 4 components in vitest without jsdom.
// Backed by @mixmark-io/domino (already a dependency via turndown). Call before importing
// any component so module-level `typeof window`/`document` checks see the DOM.
import domino from '@mixmark-io/domino';

export const installDominoDom = (href = 'http://localhost/') => {
	const g = globalThis as any;
	const window: any = domino.createWindow(
		'<!DOCTYPE html><html><head></head><body></body></html>',
		href
	);
	const impl: any = (domino as any).impl;

	// Svelte's dev runtime reads `Object`, `console`, `Math`... from `window`; a domino window
	// is a plain object, so mirror the JavaScript globals onto it first.
	for (const name of Object.getOwnPropertyNames(globalThis)) {
		if (name in window) continue;
		try {
			window[name] = (globalThis as any)[name];
		} catch {
			/* getter-only global; skip */
		}
	}
	const storage: Record<string, string> = {};
	const storageApi = {
		getItem: (k: string) => (k in storage ? storage[k] : null),
		setItem: (k: string, v: unknown) => {
			storage[k] = String(v);
		},
		removeItem: (k: string) => {
			delete storage[k];
		},
		clear: () => {
			for (const k of Object.keys(storage)) delete storage[k];
		},
		key: (i: number) => Object.keys(storage)[i] ?? null,
		get length() {
			return Object.keys(storage).length;
		}
	};
	// The app also reads/writes `localStorage.token` / `localStorage.theme` as properties.
	const localStorage = new Proxy(storageApi, {
		get: (t, p) => (p in t ? (t as any)[p] : typeof p === 'string' ? storage[p] : undefined),
		set: (_t, p, v) => {
			storage[p as string] = String(v);
			return true;
		},
		has: (t, p) => p in t || (typeof p === 'string' && p in storage)
	});

	const matchMedia = () => ({
		matches: false,
		media: '',
		onchange: null,
		addEventListener: () => {},
		removeEventListener: () => {},
		addListener: () => {},
		removeListener: () => {},
		dispatchEvent: () => false
	});
	class NoopObserver {
		observe() {}
		unobserve() {}
		disconnect() {}
		takeRecords() {
			return [];
		}
	}
	const raf = (cb: (t: number) => void) => setTimeout(() => cb(Date.now()), 0);

	Object.assign(window, {
		localStorage,
		sessionStorage: localStorage,
		matchMedia,
		requestAnimationFrame: raf,
		cancelAnimationFrame: clearTimeout,
		ResizeObserver: NoopObserver,
		IntersectionObserver: NoopObserver,
		MutationObserver: NoopObserver,
		performance: globalThis.performance,
		innerWidth: 1280,
		innerHeight: 800,
		scrollTo: () => {},
		scroll: () => {},
		scrollX: 0,
		scrollY: 0,
		getSelection: () => null
	});

	// Svelte transitions insert keyframes into a <style> sheet.
	Object.defineProperty(impl.HTMLStyleElement.prototype, 'sheet', {
		configurable: true,
		get() {
			if (!this.__sheet) {
				const rules: unknown[] = [];
				this.__sheet = {
					cssRules: rules,
					insertRule: (rule: string) => {
						rules.push(rule);
						return rules.length - 1;
					},
					deleteRule: (i: number) => {
						rules.splice(i, 1);
					}
				};
			}
			return this.__sheet;
		}
	});
	const rect = () => ({ x: 0, y: 0, top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0 });
	for (const method of ['getBoundingClientRect', 'scrollIntoView', 'focus', 'blur']) {
		if (typeof impl.Element.prototype[method] !== 'function') {
			impl.Element.prototype[method] = method === 'getBoundingClientRect' ? rect : () => {};
		}
	}
	if (!('dataset' in impl.Element.prototype)) {
		// domino has no `dataset`; melt-ui builders write `node.dataset.escapee` etc.
		const toAttr = (p: string | symbol) =>
			`data-${String(p).replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`)}`;
		Object.defineProperty(impl.Element.prototype, 'dataset', {
			configurable: true,
			get() {
				const el = this;
				return new Proxy(
					{},
					{
						get: (_t, p) => (el.hasAttribute(toAttr(p)) ? el.getAttribute(toAttr(p)) : undefined),
						set: (_t, p, v) => {
							el.setAttribute(toAttr(p), String(v));
							return true;
						},
						deleteProperty: (_t, p) => {
							el.removeAttribute(toAttr(p));
							return true;
						},
						has: (_t, p) => el.hasAttribute(toAttr(p)),
						ownKeys: () =>
							[...el.attributes]
								.map((a: any) => a.name)
								.filter((n: string) => n.startsWith('data-'))
								.map((n: string) => n.slice(5).replace(/-([a-z])/g, (_m, c) => c.toUpperCase())),
						getOwnPropertyDescriptor: (_t, p) =>
							el.hasAttribute(toAttr(p))
								? {
										value: el.getAttribute(toAttr(p)),
										enumerable: true,
										configurable: true,
										writable: true
									}
								: undefined
					}
				);
			}
		});
	}
	// domino's NodeList (a plain array-like; querySelectorAll itself is frozen) is not iterable.
	for (const sample of [
		window.document.querySelectorAll('*'),
		window.document.querySelectorAll('x-none')
	]) {
		const proto = Object.getPrototypeOf(sample);
		if (proto && proto !== Object.prototype && !proto[Symbol.iterator]) {
			proto[Symbol.iterator] = Array.prototype[Symbol.iterator];
			if (!proto.forEach) proto.forEach = Array.prototype.forEach;
		}
	}
	if (!impl.Element.prototype.getClientRects) {
		impl.Element.prototype.getClientRects = () => [];
	}

	const defineGlobal = (name: string, value: unknown) => {
		// Node 22 exposes some of these (navigator, performance) as getter-only globals.
		Object.defineProperty(g, name, { value, configurable: true, writable: true, enumerable: true });
	};
	const globals: Record<string, unknown> = {
		window,
		self: window,
		document: window.document,
		location: window.location,
		navigator: window.navigator,
		localStorage,
		sessionStorage: localStorage,
		matchMedia,
		requestAnimationFrame: raf,
		cancelAnimationFrame: clearTimeout,
		ResizeObserver: NoopObserver,
		IntersectionObserver: NoopObserver,
		MutationObserver: NoopObserver,
		getComputedStyle: window.getComputedStyle.bind(window),
		scrollTo: () => {}
	};
	for (const [name, value] of Object.entries(globals)) defineGlobal(name, value);
	// Node 22 ships native Event/CustomEvent; domino's dispatchEvent only accepts its own
	// event objects (Svelte dev mode dispatches SvelteDOM* CustomEvents on the document).
	const keepNative = new Set(['EventTarget', 'DOMException']);
	for (const name of Object.keys(impl)) {
		if (keepNative.has(name)) continue;
		if (!(name in g) || /Event$/.test(name)) defineGlobal(name, impl[name]);
	}
	if (!g.KeyboardEvent) {
		g.KeyboardEvent = class KeyboardEvent extends impl.UIEvent {
			key: string;
			constructor(type: string, init: any = {}) {
				super(type, init);
				this.key = init.key ?? '';
			}
		};
	}
	if (!g.PointerEvent) g.PointerEvent = impl.MouseEvent;
	return window;
};
