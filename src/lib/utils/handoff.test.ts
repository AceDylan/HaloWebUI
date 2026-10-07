import { describe, expect, it } from 'vitest';
import { get } from 'svelte/store';

import {
	chatHandoff,
	conversationContext,
	goalWithBackground,
	handOff,
	HANDOFF_KEY,
	originHref,
	originLabel,
	relay,
	replyHandoff,
	takeHandoff
} from './handoff';

const memory = () => {
	const data = new Map<string, string>();
	return {
		data,
		getItem: (k: string) => (data.has(k) ? data.get(k)! : null),
		setItem: (k: string, v: string) => void data.set(k, v),
		removeItem: (k: string) => void data.delete(k)
	};
};

describe('handOff / takeHandoff', () => {
	it('carries the draft, the models, the files and where it came from, once', () => {
		const store = memory();
		expect(
			handOff(store, {
				to: 'discuss',
				text: '  用 Postgres 还是 MongoDB？ ',
				models: ['m-a', 'm-b'],
				files: [
					{ id: 'f1', name: 'a.png', type: 'image' },
					{ id: '../x', name: 'bad', type: 'file' }
				],
				context: '用户：之前聊过',
				from: { kind: 'chat', id: 'c-1', title: '数据库' }
			}, 1000)
		).toBe(true);
		// another page does not take it
		expect(takeHandoff(store, 'teams', 2000)).toBeNull();
		const got = takeHandoff(store, 'discuss', 2000)!;
		expect(got.text).toBe('用 Postgres 还是 MongoDB？');
		expect(got.models).toEqual(['m-a', 'm-b']);
		expect(got.files).toEqual([{ id: 'f1', name: 'a.png', type: 'image' }]);
		expect(got.from).toEqual({ kind: 'chat', id: 'c-1', title: '数据库' });
		expect(got.context).toBe('用户：之前聊过');
		expect(takeHandoff(store, 'discuss', 2000)).toBeNull();
	});

	it('drops a stale entry and a broken one', () => {
		const store = memory();
		handOff(store, { to: 'chat', text: 'hi' }, 0);
		expect(takeHandoff(store, 'chat', 6 * 60 * 1000)).toBeNull();
		expect(store.data.has(HANDOFF_KEY)).toBe(false);
		store.setItem(HANDOFF_KEY, '{oops');
		expect(takeHandoff(store, 'chat')).toBeNull();
		expect(store.data.has(HANDOFF_KEY)).toBe(false);
	});

	it('labels and links the origin', () => {
		expect(originLabel({ kind: 'chat', id: 'c1', title: '旅行' })).toBe('对话「旅行」');
		expect(originHref({ kind: 'chat', id: 'c1', title: '' })).toBe('/c/c1');
		expect(originHref({ kind: 'discuss', id: 'd1', title: '' })).toBe('/discuss/d1');
		expect(originHref({ kind: 'team', id: 't1', title: '' })).toBe('/teams/t1');
	});
});

describe('conversationContext', () => {
	const history = {
		currentId: 'a2',
		messages: {
			u1: { id: 'u1', parentId: null, role: 'user', content: '去哪玩？' },
			a1: { id: 'a1', parentId: 'u1', role: 'assistant', content: '<details type="reasoning">想</details>\n去杭州 ![x](/img.png)' },
			x1: { id: 'x1', parentId: 'u1', role: 'assistant', content: '另一个分支' },
			u2: { id: 'u2', parentId: 'a1', role: 'user', content: [{ type: 'text', text: '预算 3000' }, { type: 'image_url' }] },
			a2: { id: 'a2', parentId: 'u2', role: 'assistant', content: '够了' }
		}
	};

	it('follows the branch on screen, oldest first, without thinking blocks or images', () => {
		expect(conversationContext(history)).toBe('用户：去哪玩？\n\n助手：去杭州 [图片]\n\n用户：预算 3000\n\n助手：够了');
	});

	it('keeps the latest turns when it is long', () => {
		expect(conversationContext(history, 15)).toBe('助手：够了');
		expect(conversationContext({ currentId: null, messages: {} })).toBe('');
	});
});

describe('chatHandoff / replyHandoff / goalWithBackground', () => {
	const history = {
		currentId: 'a2',
		messages: {
			u1: { id: 'u1', parentId: null, role: 'user', content: '去哪玩？' },
			a1: { id: 'a1', parentId: 'u1', role: 'assistant', content: '去杭州' },
			u2: { id: 'u2', parentId: 'a1', role: 'user', content: '预算 3000 够吗？', files: [{ id: 'f9', name: 'p.png', type: 'image' }] },
			a2: { id: 'a2', parentId: 'u2', role: 'assistant', content: '够了' }
		}
	};

	it('a draft from a new chat carries no background and no origin', () => {
		const h = chatHandoff('teams', { text: '写个周报', files: [{ id: 'f1', name: 'a.txt', type: 'file', status: 'uploaded' }, { id: null, name: 'b', status: 'uploading' }], history: { currentId: null, messages: {} }, chatId: 'c1' });
		expect(h).toMatchObject({ to: 'teams', text: '写个周报', context: '', from: null });
		expect(h.files).toEqual([{ id: 'f1', name: 'a.txt', type: 'file' }]);
	});

	it('a draft in a chat brings the conversation and a way back', () => {
		const h = chatHandoff('discuss', { text: '再想想', history, chatId: 'c1', title: '出游', models: ['m1', 'm2'] });
		expect(h.context).toContain('助手：够了');
		expect(h.from).toEqual({ kind: 'chat', id: 'c1', title: '出游' });
		expect(h.models).toEqual(['m1', 'm2']);
	});

	it('a reply goes with its question and the conversation up to it', () => {
		const h = replyHandoff('discuss', { history, messageId: 'a1', chatId: 'c1', title: '出游' });
		expect(h.text).toBe('去哪玩？');
		expect(h.context).toBe('用户：去哪玩？\n\n助手：去杭州');
		const later = replyHandoff('teams', { history, messageId: 'a2', chatId: 'local' });
		expect(later.text).toBe('预算 3000 够吗？');
		expect(later.files).toEqual([{ id: 'f9', name: 'p.png', type: 'image' }]);
		expect(later.from).toBeNull();
	});

	it('writes the background under a team goal, within the limit', () => {
		expect(goalWithBackground('做计划', '', null)).toBe('做计划');
		const goal = goalWithBackground('做计划', '用户：去哪玩？', { kind: 'chat', id: 'c1', title: '出游' });
		expect(goal).toBe('做计划\n\n背景（来自对话「出游」）：\n用户：去哪玩？');
		const long = goalWithBackground('做计划', 'x'.repeat(9000), null, 1000);
		expect(long.length).toBe(1000);
		expect(long).toContain('…x');
	});
});

describe('精答', () => {
	it('takes a draft with its conversation, and an answer hands on with a way back to it', () => {
		const store = memory();
		const history = {
			currentId: 'b',
			messages: { a: { id: 'a', parentId: null, role: 'user', content: '我在北京租房' }, b: { id: 'b', parentId: 'a', role: 'assistant', content: '好的' } }
		};
		expect(handOff(store, chatHandoff('answer', { text: '押金多久退？', history, chatId: 'c-1', title: '租房' }), 1000)).toBe(true);
		expect(takeHandoff(store, 'discuss', 1000)).toBeNull();
		const taken = takeHandoff(store, 'answer', 1000)!;
		expect(taken.text).toBe('押金多久退？');
		expect(taken.context).toContain('我在北京租房');
		expect(taken.from).toEqual({ kind: 'chat', id: 'c-1', title: '租房' });
		const from = { kind: 'answer' as const, id: 'r-1', title: '押金' };
		expect(originHref(from)).toBe('/answer/r-1');
		expect(originLabel(from)).toBe('精答「押金」');
	});
});

describe('relay', () => {
	it('marks each handoff stored, with what it carries, for the flash of light', () => {
		relay.set(null);
		const store = memory();
		handOff(store, { to: 'teams', text: '调研看板工具', context: '讨论结论：…', files: [{ id: 'f1', name: 'a.pdf', type: 'file' }] }, 5000);
		expect(get(relay)).toEqual({ to: 'teams', chars: 6, files: 1, context: true, at: 5000 });
	});

	it('stays quiet when nothing was stored', () => {
		relay.set(null);
		expect(handOff(null, { to: 'answer', text: 'x' })).toBe(false);
		const full = { getItem: () => null, setItem: () => { throw new Error('quota'); }, removeItem: () => {} };
		expect(handOff(full, { to: 'answer', text: 'x' })).toBe(false);
		expect(get(relay)).toBeNull();
	});
});
