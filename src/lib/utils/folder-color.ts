// A folder's colour in the sidebar: the chat list marks a chat's folder with a
// short bar before the title instead of a name badge, and the folder row tints
// its icon with the same colour so the two can be matched. Derived from the
// folder id, so it is stable across reloads and needs no stored setting.
//
// Full class strings (not built from parts) so Tailwind keeps them.
//
// No blues or greens: a chat row also carries status dots — blue while a reply
// runs, emerald when it finished unopened — and a folder mark in those colours
// read as a status (emerald-500 was the very same colour).
//
// Shades picked for distance from each other (OKLab): amber-500 next to
// orange-600, and rose-500 next to orange-600, were hard to tell apart at this
// size.
const FOLDER_COLORS = [
	{ dot: 'bg-yellow-500', text: 'text-yellow-600 dark:text-yellow-400' },
	{ dot: 'bg-rose-600', text: 'text-rose-600 dark:text-rose-400' },
	{ dot: 'bg-violet-500', text: 'text-violet-500 dark:text-violet-400' },
	{ dot: 'bg-orange-500', text: 'text-orange-500 dark:text-orange-400' },
	{ dot: 'bg-fuchsia-400', text: 'text-fuchsia-500 dark:text-fuchsia-400' },
	{ dot: 'bg-stone-400', text: 'text-stone-500 dark:text-stone-400' }
] as const;

export type FolderColor = (typeof FOLDER_COLORS)[number];

type FolderLike = { id?: string; created_at?: number | null };

const hashColor = (folderId: string): FolderColor => {
	let hash = 0;
	for (let index = 0; index < folderId.length; index += 1) {
		hash = (hash * 31 + folderId.charCodeAt(index)) >>> 0;
	}
	return FOLDER_COLORS[hash % FOLDER_COLORS.length];
};

/**
 * With the folder list at hand, folders take palette colours in creation order,
 * so up to six folders never share one and adding a folder does not recolour
 * the others. Without it (or for an unknown id) the colour comes from a hash of
 * the id.
 */
export const getFolderColor = (
	folderId: string,
	folders?: Record<string, FolderLike> | null
): FolderColor => {
	if (folders && folders[folderId]) {
		const ordered = Object.entries(folders)
			.map(([id, folder]) => ({ id, createdAt: Number(folder?.created_at ?? 0) }))
			.sort((a, b) => a.createdAt - b.createdAt || a.id.localeCompare(b.id));
		const index = ordered.findIndex((entry) => entry.id === folderId);
		return FOLDER_COLORS[index % FOLDER_COLORS.length];
	}
	return hashColor(folderId);
};
