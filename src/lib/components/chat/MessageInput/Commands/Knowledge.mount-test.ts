// The composer's # list: Obsidian notes come first for an admin, and picking one attaches the
// note's text as an inline document that names its vault path.
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

const vault = vi.hoisted(() => ({
	searchVaultNotes: vi.fn(),
	getVaultNote: vi.fn()
}));
vi.mock('$lib/apis/vault', async () => {
	const actual: any = await vi.importActual('$lib/apis/vault');
	return { ...actual, ...vault };
});
vi.mock('$lib/apis/folders', () => ({ getFolders: vi.fn(async () => []) }));
vi.mock('$lib/apis/knowledge', () => ({
	searchKnowledgeBases: vi.fn(async () => ({ items: [] })),
	searchKnowledgeFiles: vi.fn(async () => ({ items: [] }))
}));
vi.mock('$lib/apis/notes', () => ({ getNotes: vi.fn(async () => []), getNoteById: vi.fn() }));
vi.mock('svelte-sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const until = async (check: () => boolean, ms = 10000) => {
	const end = Date.now() + ms;
	while (!check()) {
		if (Date.now() > end) throw new Error(`timed out; text: ${document.body.textContent?.slice(0, 300)}`);
		await sleep(20);
	}
};

let stores: any;
let List: any;
let app: any;
let target: any;

beforeAll(async () => {
	stores = await import('$lib/stores');
	List = (await import('./Knowledge.svelte')).default;
}, 120_000);

beforeEach(() => {
	vault.searchVaultNotes.mockReset();
	vault.getVaultNote.mockReset();
	(globalThis as any).localStorage.token = 'tok';
	stores.folders.set([]);
});

afterEach(() => {
	app?.$destroy();
	target?.remove();
	app = null;
});

const mount = async (onSelect: (e: any) => void, role = 'admin') => {
	stores.user.set({ id: 'u1', role });
	const { writable } = await import('svelte/store');
	target = document.createElement('div');
	document.body.appendChild(target);
	app = new List({
		target,
		props: { query: 'halo', onSelect },
		context: new Map([['i18n', writable({ t: (s: string) => s })]])
	});
};

describe('# list: Obsidian notes', () => {
	it('lists matching notes and attaches the one picked as an inline document', async () => {
		vault.searchVaultNotes.mockResolvedValue({
			enabled: true,
			notes: [{ path: '项目/HaloWebUI.md', title: 'HaloWebUI', folder: '项目', snippet: '', updated_at: 1 }]
		});
		vault.getVaultNote.mockResolvedValue({
			path: '项目/HaloWebUI.md',
			title: 'HaloWebUI',
			content: '# HaloWebUI\n部署用 deploy.sh',
			truncated: false,
			size: 40,
			host_path: '/root/Documents/Obsidian Vault/项目/HaloWebUI.md'
		});
		const picked: any[] = [];
		await mount((e) => picked.push(e));
		await until(() => target.textContent.includes('Obsidian 笔记'));
		expect(vault.searchVaultNotes).toHaveBeenCalledWith('tok', 'halo');
		expect(target.querySelector('[data-vault-note-hint]').textContent).toBe('项目');
		(target.querySelector('button') as any).click();
		await until(() => picked.length === 1);
		expect(vault.getVaultNote).toHaveBeenCalledWith('tok', '项目/HaloWebUI.md');
		expect(picked[0]).toEqual({
			type: 'knowledge',
			data: {
				type: 'vault_note',
				id: 'vault:项目/HaloWebUI.md',
				name: 'HaloWebUI',
				path: '项目/HaloWebUI.md',
				size: 40,
				status: 'processed',
				docs: [
					{
						content: '# HaloWebUI\n部署用 deploy.sh',
						metadata: { source: 'Obsidian 笔记：项目/HaloWebUI.md', name: 'HaloWebUI' }
					}
				]
			}
		});
	});

	it('does not ask for notes for a user who is not an admin, or when the vault is off', async () => {
		await mount(() => {}, 'user');
		await sleep(300);
		expect(vault.searchVaultNotes).not.toHaveBeenCalled();
		app.$destroy();
		target.remove();
		vault.searchVaultNotes.mockResolvedValue({ enabled: false, notes: [] });
		await mount(() => {});
		await until(() => vault.searchVaultNotes.mock.calls.length > 0);
		await sleep(50);
		expect(target.textContent).not.toContain('Obsidian 笔记');
	});
});
