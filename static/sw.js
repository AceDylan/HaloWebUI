const CURRENT_URL = new URL(self.location.href);
const BUILD_HASH = CURRENT_URL.searchParams.get('build') || 'dev-build';
const CACHE_PREFIX = 'halo-pwa';
const SHELL_CACHE = `${CACHE_PREFIX}-shell-${BUILD_HASH}`;
const ASSET_CACHE = `${CACHE_PREFIX}-assets-${BUILD_HASH}`;

const PRECACHE_URLS = [
	'/',
	'/settings',
	'/settings/interface',
	'/manifest.json',
	'/static/favicon.png',
	'/static/favicon-dark.png',
	'/static/favicon-96x96.png',
	'/static/apple-touch-icon.png',
	'/static/web-app-manifest-192x192.png',
	'/static/web-app-manifest-512x512.png',
	'/static/web-app-manifest-maskable-192x192.png',
	'/static/web-app-manifest-maskable-512x512.png'
];

const EXCLUDED_PREFIXES = [
	'/api',
	'/ws',
	'/cache',
	'/openai',
	'/ollama',
	'/gemini',
	'/grok',
	'/anthropic'
];

const isCacheableAsset = (pathname) =>
	pathname.startsWith('/_app/') ||
	pathname.startsWith('/assets/') ||
	pathname.startsWith('/static/');

const shouldBypass = (request, url) => {
	if (request.method !== 'GET') {
		return true;
	}

	if (url.origin !== self.location.origin) {
		return true;
	}

	// Range requests (download managers, media seeking) get partial 206
	// responses the Cache API cannot store; leave them to the browser.
	if (request.headers.has('range')) {
		return true;
	}

	return EXCLUDED_PREFIXES.some((prefix) => url.pathname.startsWith(prefix));
};

// Only complete same-origin 200s are worth keeping. A 206, a redirect or an
// error must never be cached, and caching is always best-effort: a body that
// breaks halfway (flaky tunnel) is the browser's problem to retry, not a reason
// to fail the page.
const isCacheableResponse = (response) =>
	Boolean(response) && response.status === 200 && response.type === 'basic';

const putInCache = async (cacheName, request, response) => {
	try {
		const cache = await caches.open(cacheName);
		await cache.put(request, response);
	} catch (error) {
		// Ignored on purpose; see isCacheableResponse.
	}
};

const cacheInBackground = (event, cacheName, request, response) => {
	if (!isCacheableResponse(response)) {
		return;
	}
	const pending = putInCache(cacheName, request, response.clone());
	if (event && typeof event.waitUntil === 'function') {
		event.waitUntil(pending);
	}
};

const precacheUrl = async (cache, url) => {
	try {
		const response = await fetch(url, { cache: 'no-store' });
		if (isCacheableResponse(response)) {
			await cache.put(url, response.clone());
		}
	} catch (error) {
		// Ignore individual precache failures so one missing asset doesn't block install.
	}
};

self.addEventListener('install', (event) => {
	event.waitUntil(
		(async () => {
			const cache = await caches.open(SHELL_CACHE);
			await Promise.allSettled(PRECACHE_URLS.map((url) => precacheUrl(cache, url)));
			await self.skipWaiting();
		})()
	);
});

self.addEventListener('activate', (event) => {
	event.waitUntil(
		(async () => {
			// A new build hash means a new pair of caches; everything older is
			// dropped so hashed chunks from previous deploys stop piling up.
			const cacheNames = await caches.keys();
			await Promise.all(
				cacheNames.map((name) => {
					if (name.startsWith(CACHE_PREFIX) && name !== SHELL_CACHE && name !== ASSET_CACHE) {
						return caches.delete(name);
					}
					return Promise.resolve(false);
				})
			);
			await self.clients.claim();
		})()
	);
});

const handleNavigationRequest = async (event, request) => {
	try {
		const response = await fetch(request);
		cacheInBackground(event, SHELL_CACHE, request, response);
		return response;
	} catch (error) {
		const cache = await caches.open(SHELL_CACHE);
		const fallback =
			(await cache.match(request, { ignoreSearch: true })) ||
			(await cache.match('/')) ||
			(await cache.match('/settings'));
		if (fallback) {
			return fallback;
		}
		throw error;
	}
};

const handleAssetRequest = async (event, request) => {
	const cache = await caches.open(ASSET_CACHE);
	const cached = await cache.match(request);
	if (cached) {
		return cached;
	}

	const response = await fetch(request);
	cacheInBackground(event, ASSET_CACHE, request, response);
	return response;
};

const handleManifestRequest = async (event, request) => {
	try {
		const response = await fetch(request, { cache: 'no-store' });
		cacheInBackground(event, SHELL_CACHE, request, response);
		return response;
	} catch (error) {
		const cache = await caches.open(SHELL_CACHE);
		const fallback = (await cache.match(request)) || (await cache.match('/manifest.json'));
		if (fallback) {
			return fallback;
		}
		throw error;
	}
};

self.addEventListener('fetch', (event) => {
	const { request } = event;
	const url = new URL(request.url);

	if (shouldBypass(request, url)) {
		return;
	}

	if (request.mode === 'navigate') {
		event.respondWith(handleNavigationRequest(event, request));
		return;
	}

	if (url.pathname === '/manifest.json') {
		event.respondWith(handleManifestRequest(event, request));
		return;
	}

	if (isCacheableAsset(url.pathname)) {
		event.respondWith(handleAssetRequest(event, request));
	}
});
