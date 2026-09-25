import { describe, expect, it, vi } from 'vitest';

import { parseHubTicket, postActivityToHub, stripHubTicket, takeHubTicket } from './hub-embed';

const TICKET = [
	'v2',
	'chat',
	'1790000000',
	'Zm9vYmFyYmF6cXV4MTIzNDU2',
	'aHR0cHM6Ly9iZXN0LmFjZWR5bGFuLnVzOjU1MjY',
	'aHR0cHM6Ly9ob3N0LmFjZWR5bGFuLnVzOjMwMDE',
	'a'.repeat(64)
].join('.');

describe('parseHubTicket', () => {
	it('reads the ticket from the fragment, with or without the leading #', () => {
		expect(parseHubTicket(`#hub_ticket=${TICKET}`)).toBe(TICKET);
		expect(parseHubTicket(`hub_ticket=${TICKET}&other=1`)).toBe(TICKET);
	});

	it('ignores fragments that carry no ticket', () => {
		expect(parseHubTicket('')).toBeNull();
		expect(parseHubTicket('#token=abc')).toBeNull();
	});

	it('refuses anything that is not shaped like a v2 ticket', () => {
		for (const bad of [
			'v1.enter.1790000000.nonce.sig',
			TICKET.replace('v2.', 'v3.'),
			`${TICKET}.extra`,
			TICKET.split('.').slice(0, 6).join('.'),
			`${TICKET}<script>`,
			`v2.${'a'.repeat(2000)}.b.c.d.e.f`
		]) {
			expect(parseHubTicket(`#hub_ticket=${encodeURIComponent(bad)}`)).toBeNull();
		}
	});
});

describe('stripHubTicket', () => {
	it('drops only the ticket and keeps path, query and other fragment parameters', () => {
		const url = new URL(`https://host.example:3001/auth?redirect=%2Fc%2F1#hub_ticket=${TICKET}`);
		expect(stripHubTicket(url)).toBe('/auth?redirect=%2Fc%2F1');

		const mixed = new URL(`https://host.example:3001/auth#a=1&hub_ticket=${TICKET}&b=2`);
		expect(stripHubTicket(mixed)).toBe('/auth#a=1&b=2');
	});
});

describe('takeHubTicket', () => {
	const history = () => ({ state: { 'sveltekit:history': 3 }, replaceState: vi.fn() });

	it('returns the ticket and scrubs it from the address, keeping the history state', () => {
		const h = history();
		const ticket = takeHubTicket({ href: `https://host.example:3001/auth#hub_ticket=${TICKET}` }, h);
		expect(ticket).toBe(TICKET);
		expect(h.replaceState).toHaveBeenCalledTimes(1);
		expect(h.replaceState).toHaveBeenCalledWith(h.state, '', '/auth');
	});

	it('scrubs a malformed ticket too, but does not hand it on', () => {
		const h = history();
		expect(takeHubTicket({ href: 'https://host.example:3001/auth#hub_ticket=garbage' }, h)).toBeNull();
		expect(h.replaceState).toHaveBeenCalledTimes(1);
		expect(h.replaceState).toHaveBeenCalledWith(h.state, '', '/auth');
	});

	it('leaves an ordinary address alone (OAuth puts #token= here)', () => {
		const h = history();
		expect(takeHubTicket({ href: 'https://host.example:3001/auth#token=abc' }, h)).toBeNull();
		expect(h.replaceState).not.toHaveBeenCalled();
	});
});

describe('postActivityToHub', () => {
	const framed = () => {
		const parent = { postMessage: vi.fn() };
		return { win: { parent }, parent };
	};

	it('posts the state to the configured Hub origin when framed', () => {
		const { win, parent } = framed();
		expect(postActivityToHub('done', 'https://best.acedylan.us:5526', win)).toBe(true);
		expect(parent.postMessage).toHaveBeenCalledWith(
			{ source: 'halowebui', type: 'activity', state: 'done' },
			'https://best.acedylan.us:5526'
		);
	});

	it('stays quiet when not framed or no Hub is configured', () => {
		const top: any = { postMessage: vi.fn() };
		top.parent = top;
		expect(postActivityToHub('done', 'https://best.acedylan.us:5526', top)).toBe(false);
		expect(top.postMessage).not.toHaveBeenCalled();

		const { win, parent } = framed();
		expect(postActivityToHub('running', undefined, win)).toBe(false);
		expect(postActivityToHub('running', '', win)).toBe(false);
		expect(postActivityToHub('running', '*', win)).toBe(false);
		expect(postActivityToHub('running', 'https://hub.example/path', win)).toBe(false);
		expect(parent.postMessage).not.toHaveBeenCalled();
	});
});
