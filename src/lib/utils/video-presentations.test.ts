import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { VIDEO_PRESENTATIONS, videoSamplePath } from './video-presentations';
import { ALL_VIDEO_STYLES } from './video-styles';

describe('knowledge demonstration catalog', () => {
	it('exposes fifteen distinct forms without collisions with retained appearance presets', () => {
		expect(VIDEO_PRESENTATIONS).toHaveLength(15);
		expect(new Set(ALL_VIDEO_STYLES.map((s) => s.key)).size).toBe(ALL_VIDEO_STYLES.length);
	});

	it.each(VIDEO_PRESENTATIONS)(
		'$label has a playable sample and a lightweight poster in the shipped assets',
		(preset) => {
			for (const extension of ['mp4', 'jpg'] as const) {
				const path = videoSamplePath(preset.key, extension);
				expect(existsSync(resolve('static', path.slice(1)))).toBe(true);
			}
		}
	);
});
