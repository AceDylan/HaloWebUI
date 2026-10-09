import { WEBUI_API_BASE_URL } from '$lib/constants';

// Obsidian 笔记 for the composer's # list (admin only; backend routers/vault.py).

export type VaultNoteHit = {
	path: string;
	title: string;
	folder: string;
	snippet: string;
	updated_at: number;
};

export type VaultNote = {
	path: string;
	title: string;
	content: string;
	truncated: boolean;
	size: number;
	host_path: string | null;
};

const call = async <T>(token: string, path: string): Promise<T> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/vault${path}`, {
		headers: { Accept: 'application/json', authorization: `Bearer ${token}` }
	});
	if (!res.ok) {
		const body = await res.json().catch(() => ({}));
		throw body?.detail ?? `${res.status} ${res.statusText}`;
	}
	return res.json();
};

export const searchVaultNotes = (token: string, query: string, limit = 8) =>
	call<{ enabled: boolean; notes: VaultNoteHit[] }>(
		token,
		`/notes?q=${encodeURIComponent(query)}&limit=${limit}`
	);

export const getVaultNote = (token: string, path: string) =>
	call<VaultNote>(token, `/note?path=${encodeURIComponent(path)}`);

/** The attachment a note becomes: an inline document (the chat's context) that names its path. */
export const vaultNoteAttachment = (note: VaultNote) => ({
	type: 'vault_note',
	id: `vault:${note.path}`,
	name: note.title,
	path: note.path,
	size: note.size,
	status: 'processed',
	docs: [
		{
			content: note.truncated ? `${note.content}\n\n（笔记太长，后面的部分没有附上）` : note.content,
			metadata: { source: `Obsidian 笔记：${note.path}`, name: note.title }
		}
	]
});
