// Mounts real Svelte components in a lightweight DOM (domino) without jsdom.
// Only picks up *.mount-test.ts (outside the default *.test.ts glob); run with
// `npm run test:frontend:mount`.
import { fileURLToPath } from 'node:url';
import { defineConfig, mergeConfig } from 'vitest/config';
import viteConfig from './vite.config';

export default mergeConfig(
	viteConfig,
	defineConfig({
		// Prefer the `browser` export condition so `svelte` resolves to its DOM runtime
		// (the default/node condition is the SSR runtime whose onMount is a no-op).
		resolve: {
			conditions: ['browser'],
			alias: [
				{
					find: /^svelte$/,
					replacement: fileURLToPath(
						new URL('./node_modules/svelte/src/runtime/index.js', import.meta.url)
					)
				}
			]
		},
		test: {
			include: ['src/**/*.mount-test.ts'],
			hookTimeout: 60000,
			testTimeout: 30000,
			// Compile Svelte components for the DOM (not SSR) and resolve `svelte` to its
			// browser runtime so onMount/bind: work; inline the Svelte libraries so every
			// module shares that single runtime instance.
			testTransformMode: { web: ['**/*.mount-test.ts'] },
			server: {
				deps: {
					inline: [
						/\/node_modules\/svelte\//,
						/\/node_modules\/bits-ui\//,
						/\/node_modules\/@melt-ui\//
					]
				}
			}
		}
	})
);
