import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { installDominoDom } from '$lib/test-support/domino-dom';
import type { OfficialQuotasResponse } from '$lib/apis/hermes';

installDominoDom('http://localhost/');

const goto = vi.hoisted(() => vi.fn(async () => {}));
const api = vi.hoisted(() => {
	class MockHermesSessionExpiredError extends Error {
		constructor() {
			super('session expired');
			this.name = 'HermesSessionExpiredError';
		}
	}
	return {
		getOfficialQuotas: vi.fn(),
		HermesSessionExpiredError: MockHermesSessionExpiredError
	};
});

vi.mock('$app/navigation', () => ({ goto }));
vi.mock('$lib/apis/hermes', () => api);

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const qAll = (root: ParentNode, selector: string): HTMLElement[] =>
	Array.from(root.querySelectorAll(selector)) as HTMLElement[];

const makeDeferred = <T>() => {
	let resolve!: (value: T) => void;
	let reject!: (reason?: unknown) => void;
	const promise = new Promise<T>((res, rej) => {
		resolve = res;
		reject = rej;
	});
	return { promise, resolve, reject };
};

const SAMPLE_RESPONSE: OfficialQuotasResponse = {
	fetched_at: 1764315720.89,
	cache_ttl_seconds: 60,
	quotas: [
		{
			runner: 'openai-codex',
			label: 'Hermes Codex',
			plan: 'Plus',
			banked_resets: 2,
			available: true,
			checked_at: 1764315720.68,
			windows: [
				{
					key: 'five_hour',
					label: '5 小时',
					utilization: 10,
					resets_at: '2026-11-28T11:45:00+00:00'
				},
				{
					key: 'weekly',
					label: '每周',
					utilization: 65,
					resets_at: '2026-12-03T03:04:25+00:00'
				}
			]
		},
		{
			runner: 'offiagy',
			label: 'offiagy',
			available: true,
			checked_at: 1764315720.45,
			windows: [
				{
					key: 'five_hour',
					label: '5 小时',
					utilization: 99,
					resets_at: null
				},
				{
					key: 'gemini_five_hour',
					label: 'Gemini 5 小时',
					utilization: 5,
					resets_at: '2026-11-28T12:30:00+00:00'
				},
				{
					key: 'claude_sonnet',
					label: 'Claude Sonnet',
					utilization: 80,
					resets_at: null
				},
				{
					key: 'gpt_weekly',
					label: 'GPT 每周',
					utilization: 70,
					resets_at: null
				},
				{
					key: 'gemini_weekly',
					label: 'Gemini 每周（Weekly Limit）',
					utilization: 12,
					resets_at: '2026-12-04T08:00:00+08:00'
				},
				{
					key: 'argon',
					label: 'Argon',
					utilization: 0,
					resets_at: null
				}
			]
		},
		{
			runner: 'officlaude',
			label: '官方 Claude',
			available: true,
			checked_at: 1764315720.12,
			windows: [
				{
					key: 'five_hour',
					label: '5 小时',
					utilization: 18,
					resets_at: '2026-11-28T13:00:00+00:00'
				},
				{
					key: 'seven_day',
					label: '每周',
					utilization: 42,
					resets_at: '2026-12-02T00:00:00+00:00'
				}
			]
		}
	]
};

let buttonApp: any = null;
let modalApp: any = null;
let host: HTMLElement | null = null;
let unsubShow: (() => void) | null = null;

const mountPair = async ({
	role = 'admin',
	compact = false,
	inline = false,
	sidebarStyle = 'flat' as 'flat' | 'card',
	isMobile = false,
	onOpen = vi.fn()
} = {}) => {
	const stores = await import('$lib/stores');
	stores.user.set({
		id: 'u1',
		email: 'admin@example.com',
		name: 'Admin',
		role,
		profile_image_url: ''
	});
	stores.mobile.set(isMobile);
	stores.showSidebar.set(true);
	stores.showOfficialQuotas.set(false);

	const [{ default: OfficialQuotasButton }, { default: OfficialQuotasModal }] = await Promise.all([
		import('./OfficialQuotasButton.svelte'),
		import('./OfficialQuotasModal.svelte')
	]);

	host = document.createElement('div');
	const btnHost = document.createElement('div');
	const modalHost = document.createElement('div');
	host.appendChild(btnHost);
	host.appendChild(modalHost);
	document.body.appendChild(host);

	buttonApp = new OfficialQuotasButton({
		target: btnHost,
		props: { compact, inline, sidebarStyle, buttonClass: 'test-btn', onOpen }
	});
	modalApp = new OfficialQuotasModal({
		target: modalHost,
		props: { show: get(stores.showOfficialQuotas) }
	});
	unsubShow = stores.showOfficialQuotas.subscribe((val) => {
		modalApp?.$set({ show: val });
	});

	await sleep(20);
	return { stores, btnHost, modalHost, onOpen };
};

const getModal = () =>
	document.body.querySelector('[data-halo-official-quotas-modal]') as HTMLElement | null;

beforeAll(async () => {
	await Promise.all([
		import('./OfficialQuotasButton.svelte'),
		import('./OfficialQuotasModal.svelte')
	]);
}, 120_000);

beforeEach(() => {
	(globalThis as any).localStorage.token = 'admin-token';
	api.getOfficialQuotas.mockReset();
	goto.mockReset();
});

afterEach(() => {
	unsubShow?.();
	unsubShow = null;
	buttonApp?.$destroy();
	buttonApp = null;
	modalApp?.$destroy();
	modalApp = null;
	host?.remove();
	host = null;
	for (const el of qAll(document.body, '.modal')) {
		el.remove();
	}
});

describe('OfficialQuotasButton & OfficialQuotasModal', () => {
	it('makes zero requests on initial mount when modal is closed', async () => {
		const { btnHost } = await mountPair();
		const trigger = btnHost.querySelector('[data-halo-official-quotas-trigger="expanded"]');
		expect(trigger).toBeTruthy();
		expect(getModal()).toBeFalsy();
		expect(api.getOfficialQuotas).not.toHaveBeenCalled();
	});

	it('hides the trigger for non-admin users and refuses to fetch even if store flips true', async () => {
		const { stores, btnHost } = await mountPair({ role: 'user' });
		expect(btnHost.querySelector('[data-halo-official-quotas-trigger]')).toBeFalsy();

		stores.showOfficialQuotas.set(true);
		await sleep(30);
		expect(api.getOfficialQuotas).not.toHaveBeenCalled();
	});

	it('opens from expanded button, calls onOpen, collapses mobile drawer, shows skeleton then renders ordered three accounts', async () => {
		const deferred = makeDeferred<OfficialQuotasResponse>();
		api.getOfficialQuotas.mockReturnValueOnce(deferred.promise);

		const onOpen = vi.fn();
		const { stores, btnHost } = await mountPair({ isMobile: true, onOpen });

		const trigger = btnHost.querySelector(
			'[data-halo-official-quotas-trigger="expanded"]'
		) as HTMLButtonElement;
		trigger.click();
		await sleep(25);

		expect(onOpen).toHaveBeenCalledTimes(1);
		expect(get(stores.showSidebar)).toBe(false);
		expect(get(stores.showOfficialQuotas)).toBe(true);
		expect(api.getOfficialQuotas).toHaveBeenCalledTimes(1);
		expect(api.getOfficialQuotas).toHaveBeenCalledWith('admin-token');

		// Modal is portaled to document.body and shows skeleton while loading
		const modal = getModal();
		expect(modal).toBeTruthy();
		expect(host!.contains(modal!)).toBe(false);
		expect(modal!.querySelector('[data-halo-official-quotas-skeleton]')).toBeTruthy();

		// Resolve response
		deferred.resolve(SAMPLE_RESPONSE);
		await sleep(30);

		expect(modal!.querySelector('[data-halo-official-quotas-skeleton]')).toBeFalsy();

		// Verify card order: officlaude → offiagy → openai-codex
		const cards = qAll(modal!, '[data-halo-official-quota-card]').map((el) =>
			el.getAttribute('data-halo-official-quota-card')
		);
		expect(cards).toEqual(['officlaude', 'offiagy', 'openai-codex']);

		// Verify offiagy filters Claude/GPT & five_hour while keeping gemini_five_hour before gemini_weekly (no "主要" pill)
		const offiagyCard = modal!.querySelector(
			'[data-halo-official-quota-card="offiagy"]'
		) as HTMLElement;
		const offiagyWindows = qAll(offiagyCard, '[data-halo-quota-window]').map((el) =>
			el.getAttribute('data-halo-quota-window')
		);
		expect(offiagyWindows).toEqual(['gemini_five_hour', 'gemini_weekly', 'argon']);
		expect(offiagyCard.textContent).not.toContain('Claude');
		expect(offiagyCard.textContent).not.toContain('GPT');
		expect(offiagyCard.textContent).not.toContain('主要');
		expect(offiagyCard.textContent).toMatch(/查询于 .*:\d{2}:\d{2}/);

		// Verify Codex plan & banked_resets badge
		const codexCard = modal!.querySelector(
			'[data-halo-official-quota-card="openai-codex"]'
		) as HTMLElement;
		expect(codexCard.textContent).toContain('Plus');
		const bankedBadge = codexCard.querySelector('[data-halo-quota-banked-resets]');
		expect(bankedBadge?.textContent).toContain('备用重置 2 次');

		// Footer includes read-only + 1-minute cache explanation
		expect(modal!.textContent).toContain('只读查询 · 不消耗额度');
		expect(modal!.textContent).toContain('1 分钟内重复刷新会返回同一份结果');
	});

	it('opens from compact rail button', async () => {
		api.getOfficialQuotas.mockResolvedValueOnce(SAMPLE_RESPONSE);
		const onOpen = vi.fn();
		const { btnHost } = await mountPair({ compact: true, onOpen });

		const trigger = btnHost.querySelector(
			'[data-halo-official-quotas-trigger="compact"]'
		) as HTMLButtonElement;
		expect(trigger).toBeTruthy();
		trigger.click();
		await sleep(30);

		expect(onOpen).toHaveBeenCalledTimes(1);
		expect(api.getOfficialQuotas).toHaveBeenCalledTimes(1);
		expect(getModal()).toBeTruthy();
	});

	it('opens from inline expanded footer pill', async () => {
		api.getOfficialQuotas.mockResolvedValueOnce(SAMPLE_RESPONSE);
		const onOpen = vi.fn();
		const { stores, btnHost } = await mountPair({ inline: true, onOpen });

		const trigger = btnHost.querySelector(
			'[data-halo-official-quotas-trigger="expanded"]'
		) as HTMLButtonElement;
		expect(trigger).toBeTruthy();
		expect(trigger.classList.contains('halo-quota-trigger--inline')).toBe(true);
		expect(trigger.textContent).toContain('额度');
		trigger.click();
		await sleep(30);

		expect(onOpen).toHaveBeenCalledTimes(1);
		expect(get(stores.showOfficialQuotas)).toBe(true);
		expect(api.getOfficialQuotas).toHaveBeenCalledTimes(1);
		expect(getModal()).toBeTruthy();
	});

	it('renders degraded fallback card for unavailable account and role="alert" for low/empty windows', async () => {
		api.getOfficialQuotas.mockResolvedValueOnce({
			fetched_at: 1764315720,
			cache_ttl_seconds: 60,
			quotas: [
				{
					runner: 'officlaude',
					label: '官方 Claude',
					available: false,
					checked_at: 1764315720,
					notice: '官方 Claude 暂未登录',
					windows: []
				},
				{
					runner: 'offiagy',
					label: 'offiagy',
					available: true,
					checked_at: 1764315720,
					windows: [
						{ key: 'gemini_five_hour', label: 'Gemini 5 小时', utilization: 92, resets_at: null },
						{ key: 'gemini_weekly', label: 'Gemini 每周', utilization: 100, resets_at: null }
					]
				}
			]
		});

		const { btnHost } = await mountPair();
		(btnHost.querySelector('[data-halo-official-quotas-trigger]') as HTMLButtonElement).click();
		await sleep(30);

		const modal = getModal()!;
		const claudeCard = modal.querySelector('[data-halo-official-quota-card="officlaude"]')!;
		expect(claudeCard.textContent).toContain('官方 Claude 暂未登录');

		const lowWin = modal.querySelector('[data-halo-quota-window="gemini_five_hour"]')!;
		expect(lowWin.getAttribute('role')).toBe('alert');
		expect(lowWin.textContent).toContain('剩余 8%');
		expect(lowWin.textContent).toContain('额度紧张');

		const emptyWin = modal.querySelector('[data-halo-quota-window="gemini_weekly"]')!;
		expect(emptyWin.getAttribute('role')).toBe('alert');
		expect(emptyWin.textContent).toContain('剩余 0%');
		expect(emptyWin.textContent).toContain('已用完');
	});

	it('refreshes on manual click and on re-open while keeping previous cards visible (no flash)', async () => {
		const firstResp: OfficialQuotasResponse = {
			fetched_at: 1764315700,
			quotas: [
				{
					runner: 'officlaude',
					label: '官方 Claude',
					available: true,
					checked_at: 1764315700,
					windows: [{ key: 'five_hour', label: '5 小时', utilization: 20, resets_at: null }]
				}
			]
		};
		const secondDeferred = makeDeferred<OfficialQuotasResponse>();
		const thirdResp: OfficialQuotasResponse = {
			fetched_at: 1764315820,
			quotas: [
				{
					runner: 'officlaude',
					label: '官方 Claude',
					available: true,
					checked_at: 1764315820,
					windows: [{ key: 'five_hour', label: '5 小时', utilization: 50, resets_at: null }]
				}
			]
		};

		api.getOfficialQuotas
			.mockResolvedValueOnce(firstResp)
			.mockReturnValueOnce(secondDeferred.promise)
			.mockResolvedValueOnce(thirdResp);

		const { stores, btnHost } = await mountPair();
		const trigger = btnHost.querySelector('[data-halo-official-quotas-trigger]') as HTMLButtonElement;

		// 1st open
		trigger.click();
		await sleep(30);
		expect(api.getOfficialQuotas).toHaveBeenCalledTimes(1);
		expect(getModal()!.textContent).toContain('剩余 80%');

		// Manual refresh: keeps previous cards instead of flashing skeleton
		const refreshBtn = getModal()!.querySelector(
			'[data-halo-official-quotas-refresh]'
		) as HTMLButtonElement;
		refreshBtn.click();
		await sleep(20);
		expect(api.getOfficialQuotas).toHaveBeenCalledTimes(2);
		expect(refreshBtn.disabled).toBe(true);
		expect(getModal()!.querySelector('[data-halo-official-quotas-skeleton]')).toBeFalsy();
		expect(getModal()!.textContent).toContain('剩余 80%');

		secondDeferred.resolve({
			fetched_at: 1764315760,
			quotas: [
				{
					runner: 'officlaude',
					label: '官方 Claude',
					available: true,
					checked_at: 1764315760,
					windows: [{ key: 'five_hour', label: '5 小时', utilization: 35, resets_at: null }]
				}
			]
		});
		await sleep(30);
		expect(getModal()!.textContent).toContain('剩余 65%');

		// Close and re-open triggers a fresh request
		stores.showOfficialQuotas.set(false);
		await sleep(30);
		expect(getModal()).toBeFalsy();

		trigger.click();
		await sleep(30);
		expect(api.getOfficialQuotas).toHaveBeenCalledTimes(3);
		expect(getModal()!.textContent).toContain('剩余 50%');
	});

	it('discards stale out-of-order responses when closed and reopened', async () => {
		const staleDeferred = makeDeferred<OfficialQuotasResponse>();
		const freshDeferred = makeDeferred<OfficialQuotasResponse>();
		api.getOfficialQuotas
			.mockReturnValueOnce(staleDeferred.promise)
			.mockReturnValueOnce(freshDeferred.promise);

		const { stores, btnHost } = await mountPair();
		const trigger = btnHost.querySelector('[data-halo-official-quotas-trigger]') as HTMLButtonElement;

		// First open (slow request)
		trigger.click();
		await sleep(20);
		expect(api.getOfficialQuotas).toHaveBeenCalledTimes(1);

		// Close and reopen immediately (second request)
		stores.showOfficialQuotas.set(false);
		await sleep(20);
		trigger.click();
		await sleep(20);
		expect(api.getOfficialQuotas).toHaveBeenCalledTimes(2);

		// Newer request resolves first with 90% remaining
		freshDeferred.resolve({
			fetched_at: 1764315800,
			quotas: [
				{
					runner: 'officlaude',
					label: '官方 Claude',
					available: true,
					checked_at: 1764315800,
					windows: [{ key: 'five_hour', label: '5 小时', utilization: 10, resets_at: null }]
				}
			]
		});
		await sleep(25);
		expect(getModal()!.textContent).toContain('剩余 90%');

		// Stale first request resolves later with 1% remaining — must be ignored
		staleDeferred.resolve({
			fetched_at: 1764315700,
			quotas: [
				{
					runner: 'officlaude',
					label: '官方 Claude',
					available: true,
					checked_at: 1764315700,
					windows: [{ key: 'five_hour', label: '5 小时', utilization: 99, resets_at: null }]
				}
			]
		});
		await sleep(25);
		expect(getModal()!.textContent).toContain('剩余 90%');
		expect(getModal()!.textContent).not.toContain('剩余 1%');
	});

	it('keeps cached cards visible and shows inline error banner when a subsequent refresh fails', async () => {
		api.getOfficialQuotas
			.mockResolvedValueOnce(SAMPLE_RESPONSE)
			.mockRejectedValueOnce('连不上 Hermes：请求超时')
			.mockResolvedValueOnce(SAMPLE_RESPONSE);

		const { btnHost } = await mountPair();
		(btnHost.querySelector('[data-halo-official-quotas-trigger]') as HTMLButtonElement).click();
		await sleep(30);

		const modal = getModal()!;
		expect(modal.querySelector('[data-halo-official-quota-card="officlaude"]')).toBeTruthy();

		(modal.querySelector('[data-halo-official-quotas-refresh]') as HTMLButtonElement).click();
		await sleep(30);

		expect(modal.textContent).toContain('连不上 Hermes：请求超时');
		expect(modal.querySelector('[data-halo-official-quota-card="officlaude"]')).toBeTruthy();

		const retryBtn = qAll(modal, 'button').find((b) =>
			b.textContent?.includes('重试')
		) as HTMLButtonElement;
		expect(retryBtn).toBeTruthy();
		retryBtn.click();
		await sleep(30);

		expect(api.getOfficialQuotas).toHaveBeenCalledTimes(3);
		expect(modal.textContent).not.toContain('连不上 Hermes：请求超时');
	});

	it('renders error state with retry and navigates to /settings/analytics from footer', async () => {
		api.getOfficialQuotas
			.mockRejectedValueOnce('Hermes 返回 502：连接失败')
			.mockResolvedValueOnce(SAMPLE_RESPONSE);

		const { btnHost } = await mountPair();
		(btnHost.querySelector('[data-halo-official-quotas-trigger]') as HTMLButtonElement).click();
		await sleep(30);

		const modal = getModal()!;
		expect(modal.textContent).toContain('Hermes 返回 502：连接失败');

		const retryBtn = qAll(modal, 'button').find((b) =>
			b.textContent?.includes('重试')
		) as HTMLButtonElement;
		expect(retryBtn).toBeTruthy();
		retryBtn.click();
		await sleep(30);

		expect(api.getOfficialQuotas).toHaveBeenCalledTimes(2);
		expect(modal.querySelector('[data-halo-official-quota-card="officlaude"]')).toBeTruthy();

		const analyticsBtn = modal.querySelector(
			'[data-halo-official-quotas-analytics-link]'
		) as HTMLButtonElement;
		analyticsBtn.click();
		await sleep(30);

		expect(goto).toHaveBeenCalledWith('/settings/analytics');
		expect(getModal()).toBeFalsy();
	});
});
