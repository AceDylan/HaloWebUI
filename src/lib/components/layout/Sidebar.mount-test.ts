import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { get, writable } from 'svelte/store';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

const nav = vi.hoisted(() => ({
	goto: vi.fn(async () => {}),
	afterNavigate: vi.fn()
}));

vi.mock('$app/environment', () => ({ browser: true }));
vi.mock('$app/navigation', () => nav);
vi.mock('$app/stores', async () => {
	const { writable } = await import('svelte/store');
	return {
		page: writable({ url: new URL('http://localhost/') }),
		navigating: writable(null),
		updated: { subscribe: writable(false).subscribe }
	};
});

vi.mock('bits-ui', async () => {
	const { default: PassThrough } = await import('$lib/test-support/PassThrough.svelte');
	const group = {
		Root: PassThrough,
		Trigger: PassThrough,
		Content: PassThrough,
		Item: PassThrough,
		Separator: PassThrough,
		Sub: PassThrough,
		SubTrigger: PassThrough,
		SubContent: PassThrough,
		CheckboxItem: PassThrough,
		Value: PassThrough,
		Input: PassThrough,
		PrevButton: PassThrough,
		NextButton: PassThrough,
		Page: PassThrough
	};
	return {
		DropdownMenu: group,
		Select: group,
		Pagination: group,
		Switch: group
	};
});

vi.mock('lucide-svelte', async () => {
	const { default: PassThrough } = await import('$lib/test-support/PassThrough.svelte');
	return {
		Bookmark: PassThrough,
		Pin: PassThrough,
		PinOff: PassThrough,
		PencilLine: PassThrough,
		Copy: PassThrough,
		Archive: PassThrough,
		Share2: PassThrough,
		Download: PassThrough,
		Trash2: PassThrough,
		FolderInput: PassThrough,
		Check: PassThrough
	};
});

vi.mock('$lib/apis/chats', () => ({
	getChatList: vi.fn(async () => [
		{ id: 'c1', title: '折叠屏优化讨论', updated_at: Math.floor(Date.now() / 1000), time_range: 'Today' }
	]),
	getChatListByAssistantId: vi.fn(async () => []),
	getAllTags: vi.fn(async () => []),
	getChatListBySearchText: vi.fn(async () => []),
	getPinnedChatList: vi.fn(async () => []),
	getArchivedChatList: vi.fn(async () => []),
	getArchivedChatCount: vi.fn(async () => 0),
	getBookmarkedChatList: vi.fn(async () => [])
}));

vi.mock('$lib/apis/folders', () => ({
	getFolders: vi.fn(async () => []),
	createNewFolder: vi.fn(async () => null)
}));

vi.mock('$lib/apis/channels', () => ({
	getChannels: vi.fn(async () => []),
	createNewChannel: vi.fn(async () => null)
}));

vi.mock('$lib/apis/discussions', () => ({ listDiscussions: vi.fn(async () => []) }));
vi.mock('$lib/apis/teams', () => ({ listTeams: vi.fn(async () => ({ teams: [] })) }));
vi.mock('$lib/apis/answers', () => ({ listAnswers: vi.fn(async () => []) }));
vi.mock('$lib/apis/auths', () => ({ userSignOut: vi.fn(async () => {}) }));
vi.mock('$lib/apis/hermes', () => ({
	getOfficialQuotas: vi.fn(async () => ({ fetched_at: 0, quotas: [] })),
	listHermesSessions: vi.fn(async () => []),
	listHermesRuns: vi.fn(async () => ({ runs: [], unread: [], background: [], work: [] }))
}));
vi.mock('$lib/services/models', () => ({
	MODELS_ERROR_TOAST_ID: 'models-error',
	describeModelsError: (err: unknown) => String(err),
	ensureModels: vi.fn(async () => [])
}));

const sleep = (ms = 30) => new Promise((resolve) => setTimeout(resolve, ms));

let stores: any;
let Sidebar: any;
let app: any = null;
let target: HTMLElement | null = null;

const setViewport = (width: number, height: number) => {
	(window as any).innerWidth = width;
	(window as any).innerHeight = height;
};

const mountSidebar = async ({
	width,
	height,
	isMobile = width < 768,
	role = 'admin',
	models = [] as any[]
}: {
	width: number;
	height: number;
	isMobile?: boolean;
	role?: string;
	models?: any[];
}) => {
	setViewport(width, height);
	stores.mobile.set(isMobile);
	stores.user.set({
		id: 'u1',
		name: 'Admin',
		email: 'admin@example.com',
		role,
		profile_image_url: ''
	});
	stores.config.set({
		features: {
			enable_agent_teams: true,
			enable_image_generation: true,
			enable_channels: false
		}
	});
	stores.models.set(models);
	stores.modelsStatus.set('ready');
	stores.chats.set(null);
	stores.pinnedChats.set([]);
	stores.selectedAssistantScene.set(null);
	stores.showOfficialQuotas.set(false);
	stores.showArchivedChats.set(false);
	stores.showTaskInbox.set(false);
	stores.showBookmarks.set(false);
	stores.showHermesSessions.set(false);
	stores.showCommandPalette.set(false);

	target = document.createElement('div');
	document.body.appendChild(target);
	app = new Sidebar({
		target,
		context: new Map([['i18n', writable({ t: (s: string) => s, language: 'zh-CN' })]])
	});
	await sleep(50);
	return target;
};

beforeAll(async () => {
	stores = await import('$lib/stores');
	Sidebar = (await import('./Sidebar.svelte')).default;
}, 120_000);

beforeEach(() => {
	localStorage.clear();
	(localStorage as any).token = 'test-token';
	nav.goto.mockReset();
	nav.afterNavigate.mockReset();
});

afterEach(() => {
	app?.$destroy();
	app = null;
	target?.remove();
	target = null;
	document.body.innerHTML = '';
});

describe('Sidebar responsive layout (Fold6 / tablet / desktop)', () => {
	it('starts as compact foldable-rail on Fold6 portrait (771x835) and landscape (835x771) without overwriting desktop preference, and opens as overlay with sibling backdrop', async () => {
		localStorage.setItem('sidebar', 'true');
		const root = await mountSidebar({ width: 771, height: 835 });
		const sidebar = root.querySelector('#sidebar') as HTMLElement;
		expect(sidebar).toBeTruthy();

		// R1 height classes
		expect(sidebar.className).not.toContain('min-h-screen');
		expect(sidebar.className).toContain('max-h-[100dvh]');

		// Collapsed foldable-rail state
		expect(sidebar.getAttribute('data-state')).toBe('collapsed');
		expect(sidebar.getAttribute('data-sidebar-mode')).toBe('foldable-rail');
		expect(sidebar.getAttribute('data-rail-density')).toBe('compact');
		expect(sidebar.getAttribute('data-compact-expanded')).toBe('true');
		expect(get(stores.showSidebar)).toBe(false);
		expect(localStorage.getItem('sidebar')).toBe('true');

		// Collapsed rail deduplication: no standalone Archived Chats button, single library trigger
		expect(sidebar.querySelector('[aria-label="Archived Chats"]')).toBeFalsy();
		expect(sidebar.querySelector('[data-sidebar-library-trigger]')).toBeTruthy();

		// Click expand -> overlay + sibling backdrop (R3)
		const toggleBtn = sidebar.querySelector('#sidebar-collapse-button') as HTMLButtonElement;
		toggleBtn.click();
		await sleep(30);

		expect(sidebar.getAttribute('data-state')).toBe('overlay');
		expect(sidebar.className).toContain('w-[60px]');
		expect(localStorage.getItem('sidebar')).toBe('true');

		const backdrop = root.querySelector('[data-halo-sidebar-backdrop]') as HTMLElement | null;
		expect(backdrop).toBeTruthy();
		expect(sidebar.contains(backdrop!)).toBe(false);

		// Click backdrop -> collapses back to rail
		backdrop!.click();
		await sleep(30);
		expect(sidebar.getAttribute('data-state')).toBe('collapsed');
		expect(root.querySelector('[data-halo-sidebar-backdrop]')).toBeFalsy();

		// Re-open -> Escape closes overlay
		(sidebar.querySelector('#sidebar-collapse-button') as HTMLButtonElement).click();
		await sleep(30);
		expect(sidebar.getAttribute('data-state')).toBe('overlay');

		const esc = new (window as any).Event('keydown', { bubbles: true }) as any;
		esc.key = 'Escape';
		window.dispatchEvent(esc);
		await sleep(30);
		expect(sidebar.getAttribute('data-state')).toBe('collapsed');

		// Landscape Fold6 (835x771) stays foldable-rail + compact
		setViewport(835, 771);
		window.dispatchEvent(new Event('resize'));
		await sleep(30);
		expect(sidebar.getAttribute('data-sidebar-mode')).toBe('foldable-rail');
		expect(sidebar.getAttribute('data-rail-density')).toBe('compact');
	});

	it('uses tight rail density on ultra-short foldable viewports (835x580)', async () => {
		const root = await mountSidebar({ width: 835, height: 580 });
		const sidebar = root.querySelector('#sidebar') as HTMLElement;
		expect(sidebar.getAttribute('data-sidebar-mode')).toBe('foldable-rail');
		expect(sidebar.getAttribute('data-rail-density')).toBe('tight');
		expect(sidebar.getAttribute('data-compact-expanded')).toBe('true');
	});

	it('renders compact expanded chrome on Fold6: inline primary actions, on-demand search, single-row footer, and collapsed Assistants by default', async () => {
		const root = await mountSidebar({
			width: 771,
			height: 835,
			models: [
				{ id: 'a1', name: '写作助手', base_model_id: 'gpt-4o', is_active: true, meta: {} },
				{ id: 'a2', name: '翻译助手', base_model_id: 'gpt-4o', is_active: true, meta: {} }
			]
		});
		const sidebar = root.querySelector('#sidebar') as HTMLElement;
		(sidebar.querySelector('#sidebar-collapse-button') as HTMLButtonElement).click();
		await sleep(40);

		expect(sidebar.getAttribute('data-state')).toBe('overlay');

		// Primary action row has both New Chat and inline Auto Workbench pill
		const primaryRow = sidebar.querySelector('[data-sidebar-primary-actions]') as HTMLElement;
		expect(primaryRow).toBeTruthy();
		expect(primaryRow.querySelector('#sidebar-new-chat-button')).toBeTruthy();
		expect(primaryRow.querySelector('[data-sidebar-auto-inline]')).toBeTruthy();

		// Search input hidden by default in compactExpanded; clicking toggle opens it
		expect(sidebar.querySelector('#chat-search')).toBeFalsy();
		const searchToggle = sidebar.querySelector('[data-sidebar-search-toggle]') as HTMLButtonElement;
		expect(searchToggle).toBeTruthy();
		searchToggle.click();
		await sleep(30);
		const searchInput = sidebar.querySelector('#chat-search input') as HTMLInputElement;
		expect(searchInput).toBeTruthy();

		// Escape inside empty search collapses search input without closing the foldable overlay
		const escInSearch = new (window as any).Event('keydown', { bubbles: true }) as any;
		escInSearch.key = 'Escape';
		searchInput.dispatchEvent(escInSearch);
		await sleep(30);
		expect(sidebar.querySelector('#chat-search')).toBeFalsy();
		expect(sidebar.getAttribute('data-state')).toBe('overlay');

		// Single-row footer contains both user trigger and inline official quotas pill
		const quotaBtn = sidebar.querySelector(
			'[data-halo-official-quotas-trigger="expanded"]'
		) as HTMLElement;
		expect(quotaBtn).toBeTruthy();
		expect(quotaBtn.classList.contains('halo-quota-trigger--inline')).toBe(true);
		expect(sidebar.textContent).toContain('Admin');

		// Assistants folder defaults collapsed when showAssistantSection is unset, with count badge
		const folderButtons = Array.from(sidebar.querySelectorAll('button[aria-expanded]')) as HTMLElement[];
		const assistantsBtn = folderButtons.find((btn) => btn.textContent?.includes('Assistants'));
		expect(assistantsBtn).toBeTruthy();
		expect(assistantsBtn!.getAttribute('aria-expanded')).toBe('false');
		expect(assistantsBtn!.querySelector('[data-folder-count]')?.textContent?.trim()).toBe('2');

		// R10: same-URL New Chat click closes foldable overlay
		(primaryRow.querySelector('#sidebar-new-chat-button') as HTMLElement).click();
		await sleep(30);
		expect(sidebar.getAttribute('data-state')).toBe('collapsed');
	});

	it('preserves full desktop behavior at 1440x900: comfortable rail, expanded by default, persistent search and localStorage preference', async () => {
		const root = await mountSidebar({ width: 1440, height: 900 });
		const sidebar = root.querySelector('#sidebar') as HTMLElement;

		expect(sidebar.getAttribute('data-sidebar-mode')).toBe('desktop');
		expect(sidebar.getAttribute('data-rail-density')).toBe('comfortable');
		expect(sidebar.getAttribute('data-compact-expanded')).toBe('false');
		expect(sidebar.getAttribute('data-state')).toBe('expanded');
		expect(sidebar.querySelector('#chat-search')).toBeTruthy();
		expect(sidebar.querySelector('[data-sidebar-search-toggle]')).toBeFalsy();

		// Collapsing on desktop persists localStorage.sidebar = 'false'
		(sidebar.querySelector('#sidebar-collapse-button') as HTMLButtonElement).click();
		await sleep(30);
		expect(sidebar.getAttribute('data-state')).toBe('collapsed');
		expect(localStorage.getItem('sidebar')).toBe('false');
	});

	it('R4 regression: toggling mobile store true -> false at 771x835 keeps foldable rail closed and preserves localStorage.sidebar', async () => {
		localStorage.setItem('sidebar', 'true');
		const root = await mountSidebar({ width: 771, height: 835, isMobile: true });
		const sidebar = root.querySelector('#sidebar') as HTMLElement;

		expect(get(stores.showSidebar)).toBe(false);
		expect(localStorage.getItem('sidebar')).toBe('true');

		// Unfolding from outer screen (mobile=true) to inner screen (mobile=false) at 771x835
		stores.mobile.set(false);
		await sleep(30);

		expect(get(stores.showSidebar)).toBe(false);
		expect(sidebar.getAttribute('data-state')).toBe('collapsed');
		expect(localStorage.getItem('sidebar')).toBe('true');
	});
});
