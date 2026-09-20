// Mounts the real /hub page. What must hold: only admins get as far as asking
// for a ticket; the frame is sandboxed without top-navigation and sends no
// referrer; every (re)load uses a fresh single-use ticket; and a
// misconfiguration is explained instead of leaving a blank frame.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('https://host.acedylan.us:3001/hub');

vi.mock('$app/navigation', () => ({ goto: vi.fn(async () => {}) }));
vi.mock('$app/environment', () => ({ browser: true }));
vi.mock('dompurify', () => ({ default: { sanitize: (html: string) => html } }));
vi.mock('$lib/apis/hub', () => ({
	createHubEmbed: vi.fn(),
	openHubInNewTab: vi.fn(async () => true)
}));

const HUB = 'https://best.acedylan.us:5526';
const ORIGIN = 'https://host.acedylan.us:3001';

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const waitFor = async <T>(probe: () => T | null | undefined | false, label: string, timeout = 8000) => {
	const started = Date.now();
	for (;;) {
		const value = probe();
		if (value) return value as T;
		if (Date.now() - started > timeout) {
			throw new Error(
				`timed out waiting for ${label}; page text: ${String(document.body.textContent ?? '')
					.replace(/\s+/g, ' ')
					.slice(0, 400)}`
			);
		}
		await sleep(15);
	}
};

let ticketNo = 0;
const embedResponse = (overrides: Record<string, any> = {}) => {
	ticketNo += 1;
	return {
		hub_url: HUB,
		url: `${HUB}/embed/enter?ticket=v1.enter.1.nonce${ticketNo}.sig`,
		sso: true,
		handshake: { ok: true, reason: 'ok', checked_at: 1, frame_ancestors: [ORIGIN] },
		...overrides
	};
};

// The domino shim answers `undefined`, not `null`, when nothing matches.
const frame = () => (document.body.querySelector('iframe#hub-frame') ?? null) as any;
const notice = () => (document.body.querySelector('[role="status"]') ?? null) as any;
const buttonByLabel = (label: string) =>
	Array.from(document.body.querySelectorAll('button')).find(
		(el: any) => el.getAttribute('aria-label') === label
	) as any;

let app: any;
let target: any;
let api: any;
let navigation: any;

const openPage = async (role: string | null, config: Record<string, any> = {}) => {
	const { writable } = await import('svelte/store');
	const stores = await import('$lib/stores');
	stores.user.set(role ? ({ id: 'u1', role } as any) : (undefined as any));
	stores.config.set({ hub_embed: { enabled: true, url: HUB }, ...config } as any);

	const i18n = writable({
		language: 'en-US',
		resolvedLanguage: 'en-US',
		t: (key: string, vars?: Record<string, string>) =>
			key.replace(/{{(\w+)}}/g, (_, name) => vars?.[name] ?? ''),
		exists: () => false,
		on: () => {},
		off: () => {},
		changeLanguage: async () => {}
	});
	const { default: HubPage } = await import('./+page.svelte');
	target = document.createElement('div');
	document.body.appendChild(target);
	app = new HubPage({ target, context: new Map<string, any>([['i18n', i18n]]) });
};

beforeEach(async () => {
	(globalThis as any).localStorage.token = 'tok';
	ticketNo = 0;
	api = await import('$lib/apis/hub');
	navigation = await import('$app/navigation');
	api.createHubEmbed.mockImplementation(async () => embedResponse());
});

afterEach(() => {
	app?.$destroy();
	target?.remove();
	app = null;
	vi.clearAllMocks();
});

describe('/hub: the Bookmark Hub inside HaloWebUI', () => {
	it('frames the address the backend signed, sandboxed and without a referrer', async () => {
		await openPage('admin');
		const el = await waitFor(frame, 'the hub iframe');

		expect(api.createHubEmbed).toHaveBeenCalledTimes(1);
		expect(api.createHubEmbed).toHaveBeenCalledWith('tok');
		expect(el.getAttribute('src')).toBe(`${HUB}/embed/enter?ticket=v1.enter.1.nonce1.sig`);
		expect(el.getAttribute('referrerpolicy')).toBe('no-referrer');

		const sandbox = String(el.getAttribute('sandbox')).split(/\s+/);
		// The Hub needs its own cookie (same-origin), scripts, confirm() and real new tabs…
		for (const flag of [
			'allow-scripts',
			'allow-same-origin',
			'allow-forms',
			'allow-popups',
			'allow-popups-to-escape-sandbox',
			'allow-modals'
		]) {
			expect(sandbox).toContain(flag);
		}
		// …but must never be able to navigate HaloWebUI itself away.
		expect(sandbox.some((flag) => flag.startsWith('allow-top-navigation'))).toBe(false);
		expect(notice()).toBeNull();
	});

	it.each([['user'], ['pending'], [null]])(
		'sends a %s viewer home without ever asking for a ticket',
		async (role) => {
			await openPage(role);
			await waitFor(() => navigation.goto.mock.calls.length > 0, 'the redirect');

			expect(navigation.goto).toHaveBeenCalledWith('/');
			expect(api.createHubEmbed).not.toHaveBeenCalled();
			expect(frame()).toBeNull();
		}
	);

	it('stays away when the feature is switched off (HUB_URL empty)', async () => {
		await openPage('admin', { hub_embed: { enabled: false, url: null } });
		await waitFor(() => navigation.goto.mock.calls.length > 0, 'the redirect');
		expect(api.createHubEmbed).not.toHaveBeenCalled();
	});

	it('reload asks for a new ticket instead of replaying the spent one', async () => {
		await openPage('admin');
		const first = (await waitFor(frame, 'the hub iframe')).getAttribute('src');

		(await waitFor(() => buttonByLabel('Reload'), 'the reload button')).click();
		await waitFor(() => frame() && frame().getAttribute('src') !== first, 'a re-keyed iframe');

		expect(api.createHubEmbed).toHaveBeenCalledTimes(2);
		expect(frame().getAttribute('src')).toBe(`${HUB}/embed/enter?ticket=v1.enter.1.nonce2.sig`);
	});

	it('says so when the Hub does not allow this site to frame it', async () => {
		api.createHubEmbed.mockImplementation(async () =>
			embedResponse({
				handshake: { ok: true, reason: 'ok', checked_at: 1, frame_ancestors: ['https://elsewhere.example'] }
			})
		);
		await openPage('admin');
		const el = await waitFor(notice, 'the allow-list hint');
		expect(el.textContent).toContain('HUB_FRAME_ANCESTORS');
		expect(el.textContent).toContain(ORIGIN);
	});

	it('explains a secret mismatch and frames the plain Hub page without a ticket', async () => {
		api.createHubEmbed.mockImplementation(async () =>
			embedResponse({
				url: `${HUB}/?embed=1`,
				sso: false,
				handshake: { ok: false, reason: 'secret_mismatch', checked_at: 1, frame_ancestors: null }
			})
		);
		await openPage('admin');
		const el = await waitFor(notice, 'the sign-in hint');
		expect(el.textContent).toContain('differs between HaloWebUI and the Hub');
		expect(frame().getAttribute('src')).toBe(`${HUB}/?embed=1`);
	});

	it('offers a retry when the backend cannot produce an address', async () => {
		api.createHubEmbed.mockImplementationOnce(async () => {
			throw new Error('HTTP 502');
		});
		await openPage('admin');
		const retry = await waitFor(
			() =>
				Array.from(document.body.querySelectorAll('button')).find(
					(el: any) => el.textContent.trim() === 'Retry'
				) as any,
			'the retry button'
		);
		expect(frame()).toBeNull();
		expect(document.body.textContent).toContain('HTTP 502');

		retry.click();
		await waitFor(frame, 'the hub iframe after retrying');
	});

	it('the new-tab fallback goes through the same ticket exchange', async () => {
		await openPage('admin');
		await waitFor(frame, 'the hub iframe');
		(await waitFor(() => buttonByLabel('Open in new tab'), 'the new-tab button')).click();
		expect(api.openHubInNewTab).toHaveBeenCalledWith('tok', HUB);
	});
});
