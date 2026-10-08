import { describe, expect, it } from 'vitest';

import { searchPhrase, snippetParts } from './search-snippet';

describe('search snippet', () => {
	it('drops tag words like the server does', () => {
		expect(searchPhrase(' Nginx tag:ops Reload ')).toBe('nginx reload');
		expect(searchPhrase('tag:ops')).toBe('');
	});

	it('marks every case-insensitive occurrence, keeping the original text', () => {
		expect(snippetParts('…Run NGINX, then nginx -s reload…', 'nginx')).toEqual([
			{ text: '…Run ', match: false },
			{ text: 'NGINX', match: true },
			{ text: ', then ', match: false },
			{ text: 'nginx', match: true },
			{ text: ' -s reload…', match: false }
		]);
	});

	it('shows the excerpt plain when only tags were searched', () => {
		expect(snippetParts('<b>hi</b>', 'tag:ops')).toEqual([{ text: '<b>hi</b>', match: false }]);
		expect(snippetParts('', 'x')).toEqual([]);
	});
});
