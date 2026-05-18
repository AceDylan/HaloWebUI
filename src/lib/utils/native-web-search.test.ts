import { describe, expect, it } from 'vitest';

import { buildWebSearchModeOptions } from './native-web-search';

const t = (key: string) => key;

describe('native web search mode options', () => {
	it('offers smart web search when only HaloWebUI search is enabled', () => {
		const options = buildWebSearchModeOptions(
			t,
			{
				features: {
					enable_halo_web_search: true,
					enable_native_web_search: false
				}
			},
			[{ id: 'local-model', owned_by: 'anthropic' }]
		);

		expect(options.map((option) => option.value)).toContain('auto');
		expect(options.find((option) => option.value === 'auto')?.disabled).toBeFalsy();
		expect(options.find((option) => option.value === 'native')).toBeUndefined();
	});

	it('keeps smart web search disabled when no route can search', () => {
		const options = buildWebSearchModeOptions(
			t,
			{
				features: {
					enable_halo_web_search: false,
					enable_native_web_search: true
				}
			},
			[{ id: 'local-model', owned_by: 'anthropic' }]
		);

		expect(options.find((option) => option.value === 'auto')?.disabled).toBe(true);
	});
});
