import { readFileSync } from 'node:fs';
import { describe, expect, it, vi } from 'vitest';
import { parse, preprocess } from 'svelte/compiler';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

import { resolveModelBuiltinWebSearchState } from '$lib/utils/model-web-search-preference';

describe('web search settings save', () => {
	it('refreshes authenticated config so Hermes can use the saved Smart Search engine', async () => {
		const filename = 'src/routes/(app)/settings/web-search/+page.svelte';
		const { code } = await preprocess(readFileSync(filename, 'utf8'), vitePreprocess(), {
			filename
		});
		const ast = parse(code);
		const page = ast.html.children.find((node: any) => node.type === 'IfBlock') as any;
		const webSearch = page.children.find((node: any) => node.name === 'WebSearch');
		const saveHandler = webSearch.attributes.find(
			(attribute: any) => attribute.name === 'saveHandler'
		).value[0].expression;
		const handlerSource = code.slice(saveHandler.start, saveHandler.end);

		const authenticatedConfig = {
			features: {
				enable_halo_web_search: true,
				default_web_search_mode: 'auto',
				web_search_engine: 'smart_search'
			}
		};
		const getBackendConfig = vi.fn(async (token?: string) =>
			token === 'session-token' ? authenticatedConfig : { features: {} }
		);
		const config = { set: vi.fn() };
		const handler = new Function(
			'getBackendConfig',
			'localStorage',
			'config',
			'tick',
			'toast',
			'$i18n',
			`return (${handlerSource});`
		)(
			getBackendConfig,
			{ token: 'session-token' },
			config,
			async () => {},
			{ success: vi.fn() },
			{ t: (key: string) => key }
		);

		await handler();

		expect(getBackendConfig).toHaveBeenCalledWith('session-token');
		expect(config.set).toHaveBeenCalledWith(authenticatedConfig);
		expect(
			resolveModelBuiltinWebSearchState(
				[{ id: 'hermes-agent' }],
				authenticatedConfig.features.default_web_search_mode as 'auto',
				() => 'auto',
				['hermes-agent'],
				authenticatedConfig.features.web_search_engine
			)
		).toEqual({ mode: 'auto', source: 'default' });
	});
});
