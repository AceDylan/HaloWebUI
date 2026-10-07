// The dock on the mode pages: the chat and its modes side by side, the page you are on lit, the
// work under way counted, and what you are writing carried to the mode you switch to.
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/answer');

const nav = vi.hoisted(() => ({ goto: vi.fn() }));
vi.mock('$app/navigation', () => nav);

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
let stores: any;
let relay: any;
const apps: any[] = [];

beforeAll(async () => {
	stores = await import('$lib/stores');
	relay = await import('./mode-relay');
}, 60000);

beforeEach(() => {
	nav.goto.mockReset();
	sessionStorage.removeItem('halo.handoff');
	relay.modeDraft.set(null);
	relay.modeLive.set({ chat: 0, answer: 0, discuss: 0, teams: 0, studio: 0 });
	stores.config.set({
		features: { enable_agent_teams: true, enable_image_generation: true }
	} as any);
	stores.user.set({ id: 'u1', role: 'admin' } as any);
});

afterEach(() => {
	apps.splice(0).forEach((app) => app.$destroy());
	document.body.innerHTML = '';
});

const mount = async (props: { current: string }) => {
	const { default: ModeDock } = await import('./ModeDock.svelte');
	const target = document.createElement('div');
	document.body.appendChild(target);
	apps.push(new ModeDock({ target, props: props as any }));
	await sleep(20);
	return target;
};

const click = (el: any) => {
	const event = document.createEvent('MouseEvent') as any;
	event.initEvent('click', true, true);
	el.dispatchEvent(event);
	return event;
};

describe('ModeDock', () => {
	it('lists the chat and the modes the account may use, the current one marked', async () => {
		const target = await mount({ current: 'answer' });
		const stations = [...target.querySelectorAll('[data-halo-dock-station]')];
		expect(stations.map((el: any) => el.getAttribute('data-halo-dock-station'))).toEqual([
			'chat',
			'answer',
			'discuss',
			'teams',
			'studio'
		]);
		expect(
			target.querySelector('[aria-current="page"]')?.getAttribute('data-halo-dock-station')
		).toBe('answer');
		expect(target.querySelector('[data-halo-dock-station="chat"]')?.getAttribute('href')).toBe(
			'/?fresh-chat=true'
		);
		expect(target.querySelector('[data-halo-dock-station="discuss"]')?.getAttribute('href')).toBe(
			'/discuss'
		);
	});

	it('leaves out what the account may not use', async () => {
		stores.config.set({
			features: { enable_agent_teams: false, enable_image_generation: true }
		} as any);
		stores.user.set({
			id: 'u2',
			role: 'user',
			permissions: { features: { image_generation: false } }
		} as any);
		const target = await mount({ current: 'discuss' });
		expect(
			[...target.querySelectorAll('[data-halo-dock-station]')].map((el: any) =>
				el.getAttribute('data-halo-dock-station')
			)
		).toEqual(['chat', 'answer', 'discuss']);
	});

	it('with nothing written is a plain link: no handoff', async () => {
		const target = await mount({ current: 'answer' });
		const event = click(target.querySelector('[data-halo-dock-station="discuss"]'));
		expect(event.defaultPrevented).toBe(false);
		expect(nav.goto).not.toHaveBeenCalled();
		expect(sessionStorage.getItem('halo.handoff')).toBeNull();
		expect(target.querySelector('[data-halo-dock-cargo]')).toBeFalsy();
	});

	it('carries the draft, its files and its background to the mode picked', async () => {
		relay.setModeDraft('answer', '小团队用 Postgres 还是 MongoDB？', {
			context: '用户：我们只有三个人',
			from: { kind: 'chat', id: 'c1', title: '选型' },
			files: [{ id: 'f1', name: 'spec.pdf', type: 'file' }]
		});
		const target = await mount({ current: 'answer' });
		expect(target.querySelector('[data-halo-dock-cargo]')?.textContent).toContain('带上草稿');
		const event = click(target.querySelector('[data-halo-dock-station="discuss"]'));
		expect(event.defaultPrevented).toBe(true);
		expect(nav.goto).toHaveBeenCalledWith('/discuss');
		expect(JSON.parse(sessionStorage.getItem('halo.handoff')!)).toMatchObject({
			to: 'discuss',
			text: '小团队用 Postgres 还是 MongoDB？',
			context: '用户：我们只有三个人',
			files: [{ id: 'f1', name: 'spec.pdf', type: 'file' }],
			from: { kind: 'chat', id: 'c1', title: '选型' }
		});
	});

	it('takes the draft to the chat as well', async () => {
		relay.setModeDraft('teams', '调研三个看板工具');
		const target = await mount({ current: 'teams' });
		click(target.querySelector('[data-halo-dock-station="chat"]'));
		expect(nav.goto).toHaveBeenCalledWith('/');
		expect(JSON.parse(sessionStorage.getItem('halo.handoff')!)).toMatchObject({
			to: 'chat',
			text: '调研三个看板工具'
		});
	});

	it("ignores another page's draft", async () => {
		relay.setModeDraft('discuss', '别的页面写的');
		const target = await mount({ current: 'answer' });
		const event = click(target.querySelector('[data-halo-dock-station="teams"]'));
		expect(event.defaultPrevented).toBe(false);
		expect(sessionStorage.getItem('halo.handoff')).toBeNull();
	});

	it('counts the work under way in the other modes', async () => {
		relay.setModeLive('teams', 2);
		relay.setModeLive('answer', 1);
		const target = await mount({ current: 'answer' });
		expect(target.querySelector('[data-halo-dock-live="teams"]')?.textContent).toBe('2');
		// the page you are on shows its own list
		expect(target.querySelector('[data-halo-dock-live="answer"]')).toBeFalsy();
	});
});
