// Mounts the real /settings/interface route page (route -> InterfaceSettingsPage ->
// InterfacePreferences) in a domino DOM and drives the per-user "auto-archive inactive
// chats" and "expand collapsed sidebar on hover" controls through the visible UI and the
// page's Save button. Regression guard for the settings living in an unmounted component.
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/settings/interface?tab=chat');

vi.mock('$app/environment', () => ({
	browser: true,
	dev: false,
	building: false,
	version: 'test'
}));
vi.mock('$app/stores', async () => {
	const { writable } = await import('svelte/store');
	const page = writable({ url: new URL('http://localhost/settings/interface?tab=chat') });
	(globalThis as any).__pageStore = page;
	return { page, navigating: writable(null), updated: { subscribe: writable(false).subscribe } };
});
vi.mock('$app/navigation', () => ({
	goto: async (href: string) => {
		const { page } = await import('$app/stores'); // mocked above
		(page as any).set({ url: new URL(href, 'http://localhost') });
	},
	invalidate: async () => {},
	invalidateAll: async () => {},
	beforeNavigate: () => {},
	afterNavigate: () => {}
}));
// DOMPurify cannot parse HTML through domino's document implementation (it returns '');
// sanitisation is not under test here, so pass the dialog/tooltip markup through.
vi.mock('dompurify', () => ({ default: { sanitize: (html: unknown) => String(html ?? '') } }));
vi.mock('svelte-sonner', () => ({
	toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() }
}));
vi.mock('$lib/apis/chats', async (importOriginal) => ({
	...(await importOriginal<any>()),
	archiveInactiveChats: vi.fn(),
	restoreAutoArchivedChats: vi.fn()
}));

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const waitFor = async <T>(
	probe: () => T | null | undefined | false,
	label: string,
	timeout = 8000
) => {
	const started = Date.now();
	for (;;) {
		const value = probe();
		if (value) return value as T;
		if (Date.now() - started > timeout)
			throw new Error(
				`timed out waiting for ${label}; page text: ${String(target?.textContent ?? '')
					.replace(/\s+/g, ' ')
					.slice(0, 400)}`
			);
		await sleep(15);
	}
};
// domino only runs click listeners for its own activation path, not for a dispatched MouseEvent.
const click = (el: any) => {
	if (!el) throw new Error('click target not found');
	el.click();
};
const byText = (root: any, selector: string, text: string) =>
	Array.from(root.querySelectorAll(selector)).find((el: any) => el.textContent.trim() === text) ??
	null;
const rowOf = (root: any, labelText: string) => {
	const label = Array.from(root.querySelectorAll('div, label')).find(
		(el: any) => el.children.length === 0 && el.textContent.trim() === labelText
	);
	return label?.closest('.glass-item') ?? null;
};
const interpolate = (s: string, opts?: Record<string, any>) =>
	s.replace(/\{\{(\w+)\}\}/g, (_m, k) => String(opts?.[k] ?? `{{${k}}}`));

let target: any;
let app: any;
let saveSettings: ReturnType<typeof vi.fn>;
let stores: any;
let goto: (href: string) => Promise<void>;

const mountPage = async (initialSettings: Record<string, any>) => {
	const { writable } = await import('svelte/store');
	stores = await import('$lib/stores');
	({ goto } = await import('$app/navigation'));
	await goto('/settings/interface?tab=chat'); // the mocked page store outlives a mount
	stores.user.set({ id: 'u-test', role: 'user', permissions: { chat: { temporary: true } } });
	stores.settings.set(initialSettings);
	stores.models.set([]);
	const i18n = writable({
		language: 'en-US',
		resolvedLanguage: 'en-US',
		t: (key: string, opts?: Record<string, any>) =>
			interpolate(typeof opts?.defaultValue === 'string' ? opts.defaultValue : key, opts),
		exists: () => false,
		on: () => {},
		off: () => {},
		changeLanguage: async () => {}
	});
	saveSettings = vi.fn(async (patch: Record<string, any>) => {
		stores.settings.update((s: any) => ({ ...(s ?? {}), ...patch }));
	});
	const t0 = Date.now();
	const { default: Page } = await import('../../../routes/(app)/settings/interface/+page.svelte');
	console.log(`[mount] route module imported in ${Date.now() - t0}ms`);
	target = document.createElement('div');
	document.body.appendChild(target);
	app = new Page({
		target,
		context: new Map<string, any>([
			['i18n', i18n],
			['user-settings', { saveSettings, getModels: async () => [] }]
		])
	});
	await waitFor(() => target.querySelector('#chat-auto-archive-days'), 'chat section to load');
	// InterfacePreferences absorbs changes into its baseline for SECTION_BASELINE_SYNC_WINDOW_MS
	// (400 ms) after loading; interact only once that window has closed, like a user would.
	await sleep(500);
};

const unmount = () => {
	app?.$destroy();
	target?.remove();
	app = null;
};

const saveButton = () => byText(target, 'button', 'Save');
const pressSave = async () => {
	const button = await waitFor(() => saveButton(), 'Save button (section dirty)');
	click(button);
	await waitFor(() => saveSettings.mock.calls.length > 0, 'saveSettings call');
	// A save re-opens the 400 ms baseline-sync window; let it close before the next interaction.
	await sleep(500);
};

describe('/settings/interface: auto-archive and sidebar hover controls are mounted and saveable', () => {
	beforeAll(async () => {
		await mountPage({});
	});
	afterAll(unmount);

	it('renders the archive controls in the Chat tab, off by default', () => {
		const text = target.textContent;
		for (const label of [
			'Auto-archive inactive chats',
			'Days of inactivity',
			'Archive inactive chats now',
			'Restore auto-archived chats'
		]) {
			expect(text).toContain(label);
		}
		const row = rowOf(target, 'Auto-archive inactive chats');
		expect(row).not.toBeNull();
		expect(row.querySelector('button[role="switch"]').getAttribute('aria-checked')).toBe('false');
		expect(target.querySelector('#chat-auto-archive-days').value).toBe('30');
		expect(saveButton()).toBeNull(); // nothing dirty yet
	});

	it('enabling the switch and setting days saves settings.chatAutoArchive', async () => {
		const row = rowOf(target, 'Auto-archive inactive chats');
		click(row.querySelector('button[role="switch"]'));
		await waitFor(
			() => row.querySelector('button[role="switch"]').getAttribute('aria-checked') === 'true',
			'switch on'
		);
		const input = target.querySelector('#chat-auto-archive-days');
		input.value = '45';
		input.dispatchEvent(new (globalThis as any).Event('input', { bubbles: true }));
		await pressSave();
		const patch = saveSettings.mock.calls.at(-1)[0];
		expect(patch.chatAutoArchive).toEqual({ enabled: true, days: 45 });
		expect(patch.sidebarPeekOnHover).toBeUndefined(); // layout keys are not touched by a chat save
		expect(
			stores.settings && (await import('svelte/store')).get(stores.settings).chatAutoArchive
		).toEqual({
			enabled: true,
			days: 45
		});
		await waitFor(() => saveButton() === null, 'section clean after save');
	});

	it('clamps out-of-range day counts on change', async () => {
		const input = target.querySelector('#chat-auto-archive-days');
		for (const [raw, expected] of [
			['0', '30'],
			['99999', '3650'],
			['12.7', '12']
		]) {
			input.value = raw;
			input.dispatchEvent(new (globalThis as any).Event('input', { bubbles: true }));
			input.dispatchEvent(new (globalThis as any).Event('change', { bubbles: true }));
			await waitFor(() => input.value === expected, `days normalised from ${raw}`);
		}
	});

	it('"Archive now" previews with dry_run, asks, then archives with the shown days', async () => {
		const { archiveInactiveChats } = await import('$lib/apis/chats');
		const { toast } = await import('svelte-sonner');
		const { get } = await import('svelte/store');
		const mocked = archiveInactiveChats as unknown as ReturnType<typeof vi.fn>;
		mocked.mockReset();
		mocked.mockImplementation(async (_token: string, { days, dryRun }: any) => ({
			count: 3,
			days,
			cutoff: 0,
			dry_run: !!dryRun
		}));
		const revisionBefore = get(stores.chatListRefreshRevision);

		click(byText(target, 'button', 'Archive inactive chats now'));
		await waitFor(() => mocked.mock.calls.length === 1, 'dry-run call');
		expect(mocked.mock.calls[0][1]).toEqual({ days: 12, dryRun: true });

		const confirm = await waitFor(
			() => byText(document.body, 'button', 'Confirm'),
			'confirm dialog'
		);
		expect(document.body.textContent).toContain('Archive 3 chat(s) with no activity for 12 days?');
		click(confirm);
		await waitFor(() => mocked.mock.calls.length === 2, 'real archive call');
		expect(mocked.mock.calls[1][1]).toEqual({ days: 12 });
		await waitFor(() => (toast.success as any).mock.calls.length > 0, 'success toast');
		expect((toast.success as any).mock.calls.at(-1)[0]).toBe('Archived 3 chat(s).');
		expect(get(stores.chatListRefreshRevision)).toBe(revisionBefore + 1);
	});

	it('"Restore auto-archived chats" calls the restore endpoint', async () => {
		const { restoreAutoArchivedChats } = await import('$lib/apis/chats');
		const mocked = restoreAutoArchivedChats as unknown as ReturnType<typeof vi.fn>;
		mocked.mockReset();
		mocked.mockResolvedValue({ count: 2 });
		click(byText(target, 'button', 'Restore auto-archived chats'));
		await waitFor(() => mocked.mock.calls.length === 1, 'restore call');
	});

	it('the Layout tab shows the sidebar hover toggle (on by default) and saves it off', async () => {
		await goto('/settings/interface?tab=layout');
		const row = await waitFor(
			() => rowOf(target, 'Expand collapsed sidebar on hover'),
			'layout tab'
		);
		await sleep(500); // see mountPage: baseline-sync window
		const toggle = row.querySelector('button[role="switch"]');
		expect(toggle.getAttribute('aria-checked')).toBe('true');
		saveSettings.mockClear();
		click(toggle);
		await waitFor(() => toggle.getAttribute('aria-checked') === 'false', 'switch off');
		await pressSave();
		const patch = saveSettings.mock.calls.at(-1)[0];
		expect(patch.sidebarPeekOnHover).toBe(false);
		expect(patch.chatAutoArchive).toBeUndefined();
	});
});

describe('/settings/interface: stored preferences are loaded back into the controls', () => {
	beforeAll(async () => {
		await mountPage({ chatAutoArchive: { enabled: true, days: 60 }, sidebarPeekOnHover: false });
	});
	afterAll(unmount);

	it('shows the saved archive policy', () => {
		const row = rowOf(target, 'Auto-archive inactive chats');
		expect(row.querySelector('button[role="switch"]').getAttribute('aria-checked')).toBe('true');
		expect(target.querySelector('#chat-auto-archive-days').value).toBe('60');
	});

	it('shows the saved sidebar hover preference', async () => {
		await goto('/settings/interface?tab=layout');
		const row = await waitFor(
			() => rowOf(target, 'Expand collapsed sidebar on hover'),
			'layout tab'
		);
		expect(row.querySelector('button[role="switch"]').getAttribute('aria-checked')).toBe('false');
	});
});
