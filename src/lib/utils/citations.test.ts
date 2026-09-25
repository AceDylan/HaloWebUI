import { describe, expect, it } from 'vitest';

import { getCitationEntries, getCitationKey, getCitationList } from './citations';

// Stored shape of a HaloWebUI web search answer: one page per source, the
// query as the source name, no file_id.
const webSource = (query: string, url: string, text: string, extra = {}) => ({
	source: { name: query, type: 'web_search', urls: [url] },
	document: [text],
	metadata: [{ source: url, title: `Title of ${url}`, ...extra }]
});

describe('citations', () => {
	it('numbers web pages per URL in message order, like the backend', () => {
		const list = getCitationList([
			webSource('q1', 'https://a.example/1', 'A'),
			webSource('q1', 'https://b.example/2', 'B'),
			webSource('q2', 'https://a.example/1', 'A again'),
			webSource('q2', 'https://c.example/3', 'C')
		]);

		expect(list.map(({ id, title }) => [id, title])).toEqual([
			['https://a.example/1', 'https://a.example/1'],
			['https://b.example/2', 'https://b.example/2'],
			['https://c.example/3', 'https://c.example/3']
		]);
		expect(list[0].document).toEqual(['A', 'A again']);
		expect(list[0].source).toMatchObject({
			name: 'https://a.example/1',
			url: 'https://a.example/1'
		});
	});

	it('keeps distinct links apart even when their titles match', () => {
		const toolSource = (url: string) => ({
			source: { id: url, name: 'Same title', type: 'url', url },
			document: ['text'],
			metadata: [{ source: `web:${url}`, name: 'Same title', url }]
		});

		const list = getCitationList([
			toolSource('https://a.example/'),
			toolSource('https://b.example/')
		]);

		expect(list.map(({ id }) => id)).toEqual(['web:https://a.example/', 'web:https://b.example/']);
		expect(list.map(({ title }) => title)).toEqual(['Same title', 'Same title']);
	});

	it('falls back to the source id and never throws on non-string sources', () => {
		expect(getCitationKey({ source: { id: 'file-1' } }, { file_id: 'file-1', name: 'a.pdf' })).toBe(
			'file-1'
		);
		expect(getCitationKey({ source: {} }, { source: 42 })).toBe('42');
		expect(getCitationKey({}, undefined)).toBe('N/A');
		expect(
			getCitationList([null, {}, 'x', webSource('q', 'https://a.example/', 'A')])
		).toHaveLength(1);
	});

	it('shows the page description when no page text was captured', () => {
		const [entry] = getCitationEntries(
			webSource('q', 'https://a.example/', '', { description: 'What the page is about' })
		);

		expect(entry.document).toBe('What the page is about');
	});
});
