import { describe, expect, it } from 'vitest';
import {
	DEFAULT_VIDEO_SETTINGS,
	attachmentKind,
	buildVideoBrief,
	normalizeVideoSettings
} from './video-brief';

describe('buildVideoBrief', () => {
	const base = { ...DEFAULT_VIDEO_SETTINGS, idea: '  用 60 秒讲清楚 HTTPS  ' };

	it('writes the idea, the choices and how to deliver for Hermes itself', () => {
		const brief = buildVideoBrief({ ...base, seconds: 60 });
		expect(brief.startsWith('请制作一个视频')).toBe(true);
		expect(brief).toContain('用 60 秒讲清楚 HTTPS');
		expect(brief).toContain('做法：讲解动画');
		expect(brief).toContain('画幅：横屏 16:9（1920×1080，30fps）');
		expect(brief).toContain('时长：约 1 分钟');
		expect(brief).toContain('zh-CN-YunxiNeural');
		expect(brief).toContain('烧录中文字幕');
		expect(brief).toContain('/root/.hermes/skills/creative/video-studio/SKILL.md');
		expect(brief).toContain('「MEDIA:」');
		// no path that the media fetcher could take for a file to hand over
		expect(brief).not.toMatch(/MEDIA:\s*\//);
		expect(brief).not.toContain('参考附件');
	});

	it('puts the runner command in front and lists the attachments', () => {
		const brief = buildVideoBrief({
			...base,
			maker: 'codex',
			recipe: 'footage',
			frame: '9:16',
			voice: '',
			subtitles: false,
			seconds: 15,
			attachments: [
				{ name: 'a.mp4', kind: 'video' },
				{ name: 'b.png', kind: 'image' },
				{ name: 'c.png', kind: 'image' }
			]
		});
		expect(brief.startsWith('/codex 请制作一个视频')).toBe(true);
		expect(brief).toContain('做法：素材剪辑');
		expect(brief).toContain('竖屏 9:16（1080×1920');
		expect(brief).toContain('时长：约 15 秒');
		expect(brief).toContain('配音：不要配音');
		expect(brief).toContain('字幕：不要字幕');
		expect(brief).toContain('参考附件：1 个视频、2 个图片（a.mp4、b.png、c.png）');
		// 素材剪辑: the attached video is what gets cut
		expect(brief).not.toContain('只当风格参考');
		// otherwise a video attached as 「做成这样」 is a style reference unless the idea says to cut it in
		const styled = buildVideoBrief({ ...base, attachments: [{ name: 'ref.mp4', kind: 'video' }] });
		expect(styled).toContain('只当风格参考');
		expect(buildVideoBrief({ ...base, attachments: [{ name: 'b.png', kind: 'image' }] })).not.toContain('只当风格参考');
	});
});

describe('normalizeVideoSettings', () => {
	it('keeps what is valid and falls back for the rest', () => {
		expect(normalizeVideoSettings(null)).toEqual(DEFAULT_VIDEO_SETTINGS);
		expect(
			normalizeVideoSettings({ recipe: 'data', frame: '1:1', seconds: 90, voice: '', subtitles: false, maker: 'agy' })
		).toEqual({ recipe: 'data', frame: '1:1', seconds: 90, voice: '', subtitles: false, maker: 'agy' });
		expect(
			normalizeVideoSettings({ recipe: 'x', frame: '4:5', seconds: 9999, voice: 'nope', subtitles: 'yes', maker: 'rm' })
		).toEqual(DEFAULT_VIDEO_SETTINGS);
	});
});

describe('attachmentKind', () => {
	it('tells pictures, videos and sound from other files', () => {
		expect(attachmentKind('image/png', 'a.png')).toBe('image');
		expect(attachmentKind('video/quicktime', 'a.mov')).toBe('video');
		expect(attachmentKind('', 'clip.MP4')).toBe('video');
		expect(attachmentKind('audio/mpeg', 'bgm.mp3')).toBe('audio');
		expect(attachmentKind('', 'bgm.flac')).toBe('audio');
		expect(attachmentKind('application/pdf', '脚本.pdf')).toBe('file');
	});
});
