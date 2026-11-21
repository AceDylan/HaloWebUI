// One-line transparency for chat → workbench handoffs: says exactly what will travel
// (draft length, attachments/images, current conversation turns) and makes clear that
// clicking only opens and prefills the workbench without starting a run immediately.

import { composerFiles } from './handoff';

type HistoryMessage = { id?: string; parentId?: string | null; role?: string; content?: unknown };
type ChatHistory = { currentId?: string | null; messages?: Record<string, HistoryMessage> };
type ComposerFile = { id?: string | null; name?: string; type?: string; status?: string };

export type HandoffSummary = {
	carrying: boolean;
	draftChars: number;
	fileCount: number;
	imageCount: number;
	messageCount: number;
	/** Short human-readable parts: ["草稿 12 字", "1 张图", "当前对话 4 条"] */
	parts: string[];
	/** Joined cargo label without prefix, e.g. "草稿 12 字 · 1 个附件" */
	cargo: string;
	/** Full one-line description for menus and tooltips. */
	line: string;
	/** Explicit execution mode note: switching only prefills, never fires immediately. */
	actionNote: string;
};

const countBranchMessages = (history: ChatHistory | null | undefined): number => {
	const messages = history?.messages;
	if (!messages || !history?.currentId) return 0;
	const seen = new Set<string>();
	let id: string | null | undefined = history.currentId;
	let count = 0;
	while (id && messages[id] && !seen.has(id)) {
		seen.add(id);
		const role = messages[id].role;
		if (role === 'user' || role === 'assistant') count += 1;
		id = messages[id].parentId;
	}
	return count;
};

export const summarizeHandoff = (opts: {
	text?: string | null;
	files?: ComposerFile[] | null;
	history?: ChatHistory | null;
}): HandoffSummary => {
	const draftChars = (opts.text ?? '').trim().length;
	const uploaded = composerFiles(opts.files);
	const fileCount = uploaded.length;
	const imageCount = uploaded.filter((f) => f.type === 'image').length;
	const messageCount = countBranchMessages(opts.history);

	const parts: string[] = [];
	if (draftChars > 0) parts.push(`草稿 ${draftChars} 字`);
	if (fileCount > 0) {
		if (imageCount === fileCount) {
			parts.push(`${imageCount} 张图`);
		} else if (imageCount > 0) {
			parts.push(`${fileCount} 个附件（含 ${imageCount} 张图）`);
		} else {
			parts.push(`${fileCount} 个附件`);
		}
	}
	if (messageCount > 0) parts.push(`当前对话 ${messageCount} 条`);

	const carrying = parts.length > 0;
	const cargo = parts.join(' · ');
	const actionNote = '仅预填，不会立即开跑';
	const line = carrying ? `将带走：${cargo}（${actionNote}）` : '直接打开工作台（不会自动开跑）';

	return {
		carrying,
		draftChars,
		fileCount,
		imageCount,
		messageCount,
		parts,
		cargo,
		line,
		actionNote
	};
};
