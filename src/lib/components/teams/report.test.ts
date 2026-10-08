import { describe, expect, it } from 'vitest';

import { formatBytes, memberRunner, prepareReport, reportHref, taskRunner } from './model';

const opts = {
	workspace: '/root/work/agent-teams/halo-abc',
	fileUrl: (p: string) => `/api/v1/teams/t1/files/${p}`,
	files: ['shots/home.png', 'report.md']
};

describe('prepareReport', () => {
	it('keeps official Claude as the explicit member runner', () => {
		expect(memberRunner({ executor: 'officlaude', runner: 'officlaude' })).toMatchObject({
			chosen: 'officlaude',
			actual: 'officlaude'
		});
	});

	it('keeps ordinary Markdown and rewrites workspace links and images', () => {
		const md =
			'# 结论\n\n见 [报告](report.md) 和 ![首页](./shots/home.png "首页")，官网 [x](https://a.b/c)。';
		const out = prepareReport(md, opts);
		expect(out).toContain('[报告](/api/v1/teams/t1/files/report.md)');
		expect(out).toContain('![首页](/api/v1/teams/t1/files/shots/home.png "首页")');
		expect(out).toContain('[x](https://a.b/c)');
	});

	it('maps absolute paths inside the workspace, leaves other absolute paths alone', () => {
		const md = '![a](/root/work/agent-teams/halo-abc/shots/home.png) ![b](/etc/x.png) [c](#top)';
		const out = prepareReport(md, opts);
		expect(out).toContain('![a](/api/v1/teams/t1/files/shots/home.png)');
		expect(out).toContain('![b](/etc/x.png)');
		expect(out).toContain('[c](#top)');
	});

	it('turns bare image URLs and known image files on their own line into images', () => {
		const md =
			'截图：\nhttps://cdn.example.com/a/shot.webp?x=1\n`shots/home.png`\n/root/work/agent-teams/halo-abc/shots/home.png\nreport.md';
		const lines = prepareReport(md, opts).split('\n');
		expect(lines[1]).toBe('![](https://cdn.example.com/a/shot.webp?x=1)');
		expect(lines[2]).toBe('![shots/home.png](/api/v1/teams/t1/files/shots/home.png)');
		expect(lines[3]).toBe('![shots/home.png](/api/v1/teams/t1/files/shots/home.png)');
		expect(lines[4]).toBe('report.md'); // not an image: stays text
	});

	it('wraps a whole-JSON or YAML reply in a code block', () => {
		expect(prepareReport('{"ok": true, "items": [1, 2]}', opts)).toBe(
			'```json\n{\n  "ok": true,\n  "items": [\n    1,\n    2\n  ]\n}\n```'
		);
		const yaml = 'name: demo\nversion: 2\nsteps:\n  - build\n  - test';
		expect(prepareReport(yaml, opts)).toBe('```yaml\n' + yaml + '\n```');
		expect(prepareReport('# 标题\n\n- 要点：一\n- 要点：二\n- 要点：三', opts)).not.toContain(
			'```yaml'
		);
	});

	it('never touches fenced code', () => {
		const md = '```md\n![x](shots/home.png)\nhttps://a.b/c.png\n```\n![x](shots/home.png)';
		const out = prepareReport(md, opts).split('\n');
		expect(out[1]).toBe('![x](shots/home.png)');
		expect(out[2]).toBe('https://a.b/c.png');
		expect(out[4]).toBe('![x](/api/v1/teams/t1/files/shots/home.png)');
	});

	it('handles empty and broken input', () => {
		expect(prepareReport('', opts)).toBe('');
		expect(prepareReport('{not json', opts)).toBe('{not json');
		expect(reportHref('../secret.png', opts)).toBe('../secret.png');
		expect(reportHref('100%.png', opts)).toBe('/api/v1/teams/t1/files/100%.png');
	});
});

describe('runner decisions', () => {
	it('member: chosen vs actual with the reason', () => {
		expect(
			memberRunner({ executor: 'cchclaude', runner: 'anyclaude', runner_note: 'cchclaude 连不上' })
		).toEqual({
			chosen: 'cchclaude',
			actual: 'anyclaude',
			changed: true,
			reason: 'cchclaude 连不上',
			source: 'auto'
		});
		expect(memberRunner({ executor: 'codex', executor_source: 'user' })).toMatchObject({
			actual: 'codex',
			changed: false,
			source: 'user'
		});
		expect(
			memberRunner({ executor: 'agy', runner: null, runner_note: '全部不可用' })
		).toMatchObject({ actual: null, changed: true });
	});

	it('task: the last move explains it', () => {
		const t = taskRunner({
			executor: 'agy',
			chosen: 'codex',
			chosen_by: 'user',
			trail: [{ from: 'codex', to: 'agy', reason: '登录失效' }]
		});
		expect(t).toMatchObject({
			chosen: 'codex',
			actual: 'agy',
			changed: true,
			reason: '登录失效',
			source: 'user'
		});
		expect(taskRunner({ executor: 'hermes' })).toMatchObject({ chosen: 'hermes', changed: false });
	});
});

describe('formatBytes', () => {
	it('is short', () => {
		expect(formatBytes(512)).toBe('512 B');
		expect(formatBytes(2048)).toBe('2.0 KB');
		expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 MB');
	});
});
