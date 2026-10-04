import { describe, expect, it } from 'vitest';

import { conversationContext, handOff, HANDOFF_KEY, originHref, originLabel, takeHandoff } from './handoff';

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
