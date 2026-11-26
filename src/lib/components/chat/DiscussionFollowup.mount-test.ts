import { afterEach, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';
import { discussionRoomForReply } from '$lib/utils/hermes';

installDominoDom('http://localhost/');
const { getDiscussion, error } = vi.hoisted(() => ({ getDiscussion: vi.fn(), error: vi.fn() }));
vi.mock('$lib/apis/discussions', () => ({ getDiscussion }));
vi.mock('svelte-sonner', () => ({ toast: { error } }));

let app: any;
const prepare = vi.fn();
const mount = async () => {
	const { default: Followup } = await import('./DiscussionFollowup.svelte');
	const target = document.createElement('div');
	app = new Followup({ target, props: { roomId: 'room-1', originId: 'chat-1', canUseHermes: true, prepare } });
	return target;
};

afterEach(() => {
	app?.$destroy();
	vi.clearAllMocks();
});

const first = { origin: { chatId: 'chat-1' }, status: 'done', question: '选 A？', conclusion: { content: '旧结论' } };

it('only offers the room for the delivered reply on the selected branch', () => {
	const messages = {
		report: { role: 'assistant', done: true, parentId: 'notice' },
		notice: { role: 'user', hermes_notice: { source: 'discuss', run_id: 'discuss:room-1:ask-1' } },
		sibling: { role: 'assistant', done: true, parentId: 'ordinary' }
	};
	expect(discussionRoomForReply({ messages, currentId: 'report' })).toBe('room-1');
	expect(discussionRoomForReply({ messages, currentId: 'sibling' })).toBeNull();
});

it('continues in the same room and hands the newest completed conclusion to the composer', async () => {
	getDiscussion.mockResolvedValue({ asks: [first, { status: 'done', question: '改选 B？', conclusion: { content: '最新结论 B [1]' }, research: { sources: [{ n: 1, title: '资料', url: 'https://example.org/b' }] } }] });
	const target = await mount();
	expect(target.querySelector('a')?.getAttribute('href')).toBe('/discuss/room-1#follow-up');
	target.querySelector('button')!.click();
	await vi.waitFor(() => expect(prepare).toHaveBeenCalledTimes(1));
	expect(prepare.mock.calls[0][0]).toContain('改选 B？');
	expect(prepare.mock.calls[0][0]).toContain('最新结论 B');
	expect(prepare.mock.calls[0][0]).toContain('https://example.org/b');
	expect(prepare.mock.calls[0][0]).not.toContain('旧结论');
});

it('keeps the existing draft when a newer question has not concluded', async () => {
	getDiscussion.mockResolvedValue({ asks: [first, { status: 'running' }] });
	const target = await mount();
	target.querySelector('button')!.click();
	await vi.waitFor(() => expect(error).toHaveBeenCalledOnce());
	expect(prepare).not.toHaveBeenCalled();
});
