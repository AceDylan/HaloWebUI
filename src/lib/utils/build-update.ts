import { WEBUI_BASE_URL, WEBUI_BUILD_HASH } from '$lib/constants';

/**
 * An open tab keeps running the bundle it loaded. After a deploy the server is a
 * newer build and new features only show up once the page is reloaded, so the
 * tab asks which build is serving whenever its socket reconnects (a deploy
 * always drops it) and offers a reload when that differs from its own.
 */
const knownBuild = (build: unknown): build is string =>
	typeof build === 'string' && build !== '' && build !== 'dev-build';

export const isNewerBuild = (running: unknown, serving: unknown) =>
	knownBuild(running) && knownBuild(serving) && running !== serving;

let announced = '';

export const checkForNewBuild = async (
	onNewBuild: (build: string) => void,
	{ running = WEBUI_BUILD_HASH, fetchImpl = fetch }: { running?: string; fetchImpl?: typeof fetch } = {}
) => {
	try {
		const res = await fetchImpl(`${WEBUI_BASE_URL}/api/version`, { cache: 'no-store' });
		if (!res.ok) return;
		const build = (await res.json())?.build;
		// Once per build: several reconnects during one restart say it once.
		if (!isNewerBuild(running, build) || build === announced) return;
		announced = build;
		onNewBuild(build);
	} catch {
		// The server is still coming back; the next reconnect asks again.
	}
};

export const resetBuildUpdateForTest = () => {
	announced = '';
};
