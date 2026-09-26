import { describe, expect, it } from 'vitest';

import {
	describeBackgroundRun,
	extractToolCallTokens,
	formatRunDuration,
	summarizeRunActivity
} from './run-activity';

const call = (name: string, result?: object) =>
	result
		? `<details type="tool_calls" done="true" id="h" name="${name}" arguments="{&quot;input&quot;: &quot;x&quot;}" result="${JSON.stringify(result).replace(/"/g, '&quot;')}">\n<summary>Tool Executed</summary>\n</details>`
		: `<details type="tool_calls" done="false" id="h" name="${name}" arguments="{}">\n<summary>Executing...</summary>\n</details>`;

describe('run activity summary', () => {
	it('counts steps by tool, time and failures', () => {
		const content = [
			call('terminal', { status: 'success', duration: 1 }),
			call('terminal', { status: 'error', duration: 1 }),
			call('read_file', { status: 'success', duration: 1 }),
			call('terminal', { status: 'success', duration: 1 }),
			call('browser_click', { status: 'success', duration: 1 }),
			call('patch'),
			'结论',
			'````html\n<div></div>\n````'
		].join('\n');
		const tokens = extractToolCallTokens(content);
		expect(tokens).toHaveLength(6);
		expect(summarizeRunActivity(tokens, 97)).toBe(
			'6 步 · 终端 3 · 读文件 1 · 浏览器 1 · 1 分 37 秒 · 1 个失败 · 1 个中断'
		);
	});

	it('is empty without tool calls', () => {
		expect(summarizeRunActivity(extractToolCallTokens('只有文字'))).toBe('');
	});

	it('formats durations in words', () => {
		expect(formatRunDuration(0.4)).toBe('');
		expect(formatRunDuration(42)).toBe('42 秒');
		expect(formatRunDuration(120)).toBe('2 分');
		expect(formatRunDuration(3725)).toBe('1 小时 2 分');
	});

	it('describes a background runner', () => {
		expect(describeBackgroundRun({ agent: 'reclaude', started_at: 1000, step: 198 }, 1000 + 12 * 60 + 5)).toBe(
			'reclaude · 已运行 12 分钟 · 第 198 步'
		);
		expect(describeBackgroundRun({ agent: 'codex', started_at: 0 }, 3 * 3600 + 120)).toBe('codex');
		expect(describeBackgroundRun({ agent: 'agy', started_at: 10 }, 10 + 3660)).toBe(
			'agy · 已运行 1 小时 1 分钟'
		);
	});
});
