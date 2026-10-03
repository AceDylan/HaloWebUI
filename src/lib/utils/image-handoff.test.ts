import { describe, expect, it, vi } from 'vitest';

import {
	CHAT_EDIT_IMAGE_EVENT,
	CHAT_IMAGE_HANDOFF_KEY,
	chatImageFileFromHandoff,
	imageFileIdFromUrl,
	parseChatImageHandoff,
	readStudioRequest,
	requestChatImageEdit,
	studioUrlForImage,
	takeChatImageHandoff
} from './image-handoff';

const ORIGIN = 'https://halo.example';

describe('image file addresses', () => {
	it("takes this server's file content addresses only", () => {
		expect(imageFileIdFromUrl('/api/v1/files/abc-123/content')).toBe('abc-123');
		expect(imageFileIdFromUrl(`${ORIGIN}/api/v1/files/abc/content`, ORIGIN)).toBe('abc');
		expect(imageFileIdFromUrl('https://evil.example/api/v1/files/abc/content', ORIGIN)).toBe('');
		expect(imageFileIdFromUrl(`${ORIGIN}/api/v1/files/abc/content`)).toBe('');
		expect(imageFileIdFromUrl('//evil.example/api/v1/files/abc/content', ORIGIN)).toBe('');
		expect(imageFileIdFromUrl('data:image/png;base64,AAAA', ORIGIN)).toBe('');
		expect(imageFileIdFromUrl('/api/v1/files/../users/content')).toBe('');
		expect(imageFileIdFromUrl('/api/v1/files/abc/content?x=1')).toBe('');
		expect(imageFileIdFromUrl(null)).toBe('');
	});
});

describe('opening a chat image in the studio', () => {
	it('round-trips the image and the prompt through the address', () => {
		const url = studioUrlForImage('/api/v1/files/abc/content', '  a fox & a hen  ');
		expect(url.startsWith('/workspace/images?tab=workbench&reference=')).toBe(true);
		expect(readStudioRequest(url.split('?')[1], ORIGIN)).toEqual({
			fileId: 'abc',
			prompt: 'a fox & a hen'
		});
	});

	it('ignores a reference that is not one of our files', () => {
		expect(readStudioRequest('reference=https%3A%2F%2Fevil.example%2Fx.png', ORIGIN)).toEqual({
			fileId: '',
			prompt: ''
		});
	});
});

describe('sending a studio image to a chat', () => {
	it('is read once, fresh, and becomes an uploaded image attachment', () => {
		const raw = JSON.stringify({ fileId: 'abc', name: 'fox.png', at: 1_000 });
		const handoff = parseChatImageHandoff(raw, 2_000);
		expect(handoff).toEqual({ fileId: 'abc', name: 'fox.png', at: 1_000 });
		expect(chatImageFileFromHandoff(handoff!, '/api/v1', 'item-1')).toEqual({
			type: 'image',
			id: 'abc',
			url: '/api/v1/files/abc/content',
			name: 'fox.png',
			status: 'uploaded',
			itemId: 'item-1'
		});
	});

	it('drops stale or malformed handoffs', () => {
		expect(parseChatImageHandoff(JSON.stringify({ fileId: 'abc', at: 0 }), 10 * 60 * 1000)).toBeNull();
		expect(parseChatImageHandoff(JSON.stringify({ fileId: '../x', at: 1 }), 2)).toBeNull();
		expect(parseChatImageHandoff('nope', 2)).toBeNull();
		expect(parseChatImageHandoff(null)).toBeNull();
	});
});

describe('taking a handoff', () => {
	const store = (value: string | null) => {
		const data = new Map<string, string>();
		if (value !== null) data.set(CHAT_IMAGE_HANDOFF_KEY, value);
		return {
			data,
			getItem: (key: string) => data.get(key) ?? null,
			removeItem: (key: string) => void data.delete(key)
		};
	};

	it('returns a fresh handoff once and removes it', () => {
		const storage = store(JSON.stringify({ fileId: 'abc', name: '', at: 1_000 }));
		expect(takeChatImageHandoff(storage, 2_000)?.fileId).toBe('abc');
		expect(storage.data.size).toBe(0);
		expect(takeChatImageHandoff(storage, 2_000)).toBeNull();
	});

	it('removes a stale one without using it', () => {
		const storage = store(JSON.stringify({ fileId: 'abc', at: 0 }));
		expect(takeChatImageHandoff(storage, 10 * 60 * 1000)).toBeNull();
		expect(storage.data.size).toBe(0);
		expect(takeChatImageHandoff(null)).toBeNull();
	});
});

describe('editing a chat image', () => {
	it('announces only our own files to the chat page', () => {
		const target = Object.assign(new EventTarget(), { location: { origin: ORIGIN } });
		vi.stubGlobal('window', target);
		const seen: unknown[] = [];
		target.addEventListener(CHAT_EDIT_IMAGE_EVENT, (event) => seen.push((event as CustomEvent).detail));
		try {
			expect(requestChatImageEdit('/api/v1/files/abc/content', ' fox.png ')).toBe(true);
			expect(requestChatImageEdit(`${ORIGIN}/api/v1/files/def/content`)).toBe(true);
			expect(requestChatImageEdit('https://evil.example/api/v1/files/x/content')).toBe(false);
		} finally {
			vi.unstubAllGlobals();
		}
		expect(seen).toEqual([
			{ fileId: 'abc', name: 'fox.png' },
			{ fileId: 'def', name: '' }
		]);
	});
});
