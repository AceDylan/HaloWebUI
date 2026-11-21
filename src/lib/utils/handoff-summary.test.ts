import { describe, expect, it } from 'vitest';
import { summarizeHandoff } from './handoff-summary';

describe('summarizeHandoff', () => {
	it('reports direct open when there is no draft, attachment, or history', () => {
		const res = summarizeHandoff({ text: '   ', files: [], history: { currentId: null, messages: {} } });
		expect(res.carrying).toBe(false);
		expect(res.parts).toEqual([]);
		expect(res.line).toContain('直接打开工作台');
		expect(res.line).toContain('不会自动开跑');
	});

	it('summarizes draft length, uploaded images/files, and conversation branch count', () => {
		const history = {
			currentId: 'm2',
			messages: {
				m1: { id: 'm1', parentId: null, role: 'user', content: 'hi' },
				m2: { id: 'm2', parentId: 'm1', role: 'assistant', content: 'hello' },
				other: { id: 'other', parentId: null, role: 'user', content: 'off-branch' }
			}
		};
		const res = summarizeHandoff({
			text: '帮我做个对比方案',
			files: [
				{ id: 'f1', name: 'a.png', type: 'image', status: 'uploaded' },
				{ id: 'f2', name: 'b.pdf', type: 'file', status: 'uploaded' },
				{ id: null, name: 'pending.png', type: 'image', status: 'uploading' }
			],
			history
		});
		expect(res.carrying).toBe(true);
		expect(res.draftChars).toBe(8);
		expect(res.fileCount).toBe(2);
		expect(res.imageCount).toBe(1);
		expect(res.messageCount).toBe(2);
		expect(res.parts).toEqual(['草稿 8 字', '2 个附件（含 1 张图）', '当前对话 2 条']);
		expect(res.line).toBe('将带走：草稿 8 字 · 2 个附件（含 1 张图） · 当前对话 2 条（仅预填，不会立即开跑）');
	});

	it('uses image wording when all attachments are images', () => {
		const res = summarizeHandoff({
			text: '',
			files: [{ id: 'img1', name: 'cat.jpg', type: 'image', status: 'uploaded' }]
		});
		expect(res.parts).toEqual(['1 张图']);
		expect(res.line).toContain('将带走：1 张图');
	});
});
