import { describe, expect, it } from 'vitest';

import { getFolderColor } from './folder-color';

describe('getFolderColor', () => {
	it('is stable for a folder id', () => {
		const id = '7143c787-337a-4ea6-a6ba-7930a6b456ab';
		expect(getFolderColor(id)).toBe(getFolderColor(id));
	});

	it('gives up to eight listed folders distinct colours in creation order', () => {
		const folders = Object.fromEntries(
			Array.from({ length: 8 }, (_, index) => [
				`folder-${index}`,
				{ id: `folder-${index}`, created_at: 1000 + index }
			])
		);
		const dots = Object.keys(folders).map((id) => getFolderColor(id, folders).dot);
		expect(new Set(dots).size).toBe(8);

		// A new folder does not recolour the existing ones.
		const withNew = { ...folders, 'folder-new': { id: 'folder-new', created_at: 5000 } };
		expect(getFolderColor('folder-3', withNew)).toBe(getFolderColor('folder-3', folders));
	});

	it('spreads different folders over the palette', () => {
		const ids = [
			'7143c787-337a-4ea6-a6ba-7930a6b456ab',
			'80506165-fa19-4edd-89d5-025146999fff',
			'3b36de07-8f22-4bd9-a866-9d547f887e5e',
			'50d011b9-8621-4fc0-8b7c-0a86382145e7',
			'67e62936-4ba3-4c57-922a-2b772a13addd',
			'29d06ced-7302-44d8-ad3b-b93f6a3fe911'
		];
		const dots = new Set(ids.map((id) => getFolderColor(id).dot));
		expect(dots.size).toBeGreaterThan(2);
	});
});
