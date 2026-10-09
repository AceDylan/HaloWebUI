import { describe, expect, it } from 'vitest';
import { paletteItems } from './command-palette';
import { libraryDestinations, modeDestinations } from './destinations';

const admin = { role: 'admin' };
const destinations = [
	...modeDestinations({ features: { enable_agent_teams: true } }, admin),
	...libraryDestinations(admin)
];
const recent = [
	{ id: 'c1', title: '部署 HaloWebUI', kind: null },
	{ id: 'd1', title: '选数据库', kind: 'discuss' }
];
const models = [
	{ id: 'openai.gpt-chat', name: 'gpt-chat' },
	{ id: 'hermes-agent', name: 'Hermes' },
	{ id: 'secret', name: 'gpt-hidden', info: { meta: { hidden: true } } }
];
const base = { destinations, admin: true, recent, hits: null, models };

describe('paletteItems', () => {
	it('lists every place and the recent chats before anything is typed', () => {
		const items = paletteItems({ ...base, query: '' });
		const labels = items.filter((i) => i.section === '跳转').map((i) => i.label);
		expect(labels).toEqual(['新对话', '精答', '讨论', '协作', '助手', '提示词', '定时', '收藏', '已归档的对话', '设置', '管理后台']);
		expect(items.filter((i) => i.section === '对话').map((i) => i.href)).toEqual(['/c/c1', '/discuss/d1']);
		expect(items.some((i) => i.section === '用模型开新对话')).toBe(false);
	});

	it('narrows places, uses the server hits for chats, and offers matching models', () => {
		const items = paletteItems({
			...base,
			query: 'GPT',
			hits: [{ id: 'c9', title: '旧对话', snippet: '…gpt 的价格…', message_id: 'm3', kind: null }]
		});
		expect(items.filter((i) => i.section === '跳转')).toEqual([]);
		const chat = items.find((i) => i.section === '对话')!;
		expect(chat).toMatchObject({ href: '/c/c9', hint: '…gpt 的价格…', messageId: 'm3' });
		expect(items.filter((i) => i.section === '用模型开新对话').map((i) => i.label)).toEqual(['gpt-chat']);
		expect(items.find((i) => i.label === 'gpt-chat')!.href).toBe('/?models=openai.gpt-chat');
	});

	it('matches titles locally while the server is still searching, and finds places by name', () => {
		const items = paletteItems({ ...base, query: '定时' });
		expect(items.map((i) => i.label)).toEqual(['定时']);
		const chats = paletteItems({ ...base, query: '数据库' }).filter((i) => i.section === '对话');
		expect(chats.map((i) => i.href)).toEqual(['/discuss/d1']);
	});

	it('keeps admin-only places from other users', () => {
		const user = { role: 'user', permissions: { workspace: { prompts: true } } };
		const items = paletteItems({
			...base,
			admin: false,
			destinations: [...modeDestinations({ features: {} }, user), ...libraryDestinations(user)],
			query: ''
		});
		const labels = items.filter((i) => i.section === '跳转').map((i) => i.label);
		expect(labels).not.toContain('定时');
		expect(labels).not.toContain('管理后台');
		expect(labels).not.toContain('协作');
		expect(labels).toContain('提示词');
	});
});
