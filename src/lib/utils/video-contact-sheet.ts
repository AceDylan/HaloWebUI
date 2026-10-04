// A video as one picture the models that read images can look at: a few evenly spaced frames,
// each stamped with its time. Decoded by the browser, so nothing is needed on the server; null
// when this browser cannot play the video (codec) or it does not load in time.

const FRAMES = 6;
const COLUMNS = 3;
const TILE_WIDTH = 480;
const WAIT_MS = 8000;

export const isVideoFile = (file: { type?: string; name?: string }) =>
	(file.type ?? '').startsWith('video/') || /\.(mp4|m4v|mov|webm|mkv|ogv)$/i.test(file.name ?? '');

const formatTime = (seconds: number) => {
	const s = Math.max(0, Math.floor(seconds));
	const mm = String(Math.floor(s / 60)).padStart(2, '0');
	return `${mm}:${String(s % 60).padStart(2, '0')}`;
};

const once = (video: HTMLVideoElement, event: string) =>
	new Promise<void>((resolve, reject) => {
		const timer = setTimeout(() => done(new Error('timeout')), WAIT_MS);
		const ok = () => done();
		const fail = () => done(new Error('error'));
		const done = (error?: Error) => {
			clearTimeout(timer);
			video.removeEventListener(event, ok);
			video.removeEventListener('error', fail);
			error ? reject(error) : resolve();
		};
		video.addEventListener(event, ok);
		video.addEventListener('error', fail);
	});

export const videoContactSheet = async (file: File): Promise<File | null> => {
	const url = URL.createObjectURL(file);
	const video = document.createElement('video');
	video.muted = true;
	video.playsInline = true;
	video.preload = 'auto';
	try {
		const loaded = once(video, 'loadeddata');
		video.src = url;
		await loaded;
		const { duration, videoWidth, videoHeight } = video;
		if (!Number.isFinite(duration) || duration <= 0 || !videoWidth || !videoHeight) return null;

		const tileHeight = Math.round((TILE_WIDTH * videoHeight) / videoWidth);
		const rows = Math.ceil(FRAMES / COLUMNS);
		const canvas = document.createElement('canvas');
		canvas.width = TILE_WIDTH * COLUMNS;
		canvas.height = tileHeight * rows;
		const ctx = canvas.getContext('2d');
		if (!ctx) return null;
		ctx.fillStyle = '#000';
		ctx.fillRect(0, 0, canvas.width, canvas.height);
		ctx.font = '600 20px system-ui, sans-serif';
		ctx.textBaseline = 'middle';

		for (let i = 0; i < FRAMES; i++) {
			const time = (duration * (i + 0.5)) / FRAMES;
			const seeked = once(video, 'seeked');
			video.currentTime = time;
			await seeked;
			const x = (i % COLUMNS) * TILE_WIDTH;
			const y = Math.floor(i / COLUMNS) * tileHeight;
			ctx.drawImage(video, x, y, TILE_WIDTH, tileHeight);
			const label = `${i + 1} · ${formatTime(time)}`;
			const width = ctx.measureText(label).width + 16;
			ctx.fillStyle = 'rgba(0, 0, 0, 0.6)';
			ctx.fillRect(x + 8, y + 8, width, 30);
			ctx.fillStyle = '#fff';
			ctx.fillText(label, x + 16, y + 23);
		}

		const blob = await new Promise<Blob | null>((resolve) =>
			canvas.toBlob(resolve, 'image/jpeg', 0.85)
		);
		if (!blob) return null;
		const base = file.name.replace(/\.[^.]+$/, '') || 'video';
		return new File([blob], `${base} · 画面拼图.jpg`, { type: 'image/jpeg' });
	} catch {
		return null;
	} finally {
		video.removeAttribute('src');
		video.load();
		URL.revokeObjectURL(url);
	}
};
