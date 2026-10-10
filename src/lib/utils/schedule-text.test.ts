import { describe, expect, it } from 'vitest';
import {
	buildSchedule,
	countdownParts,
	cronText,
	cycleProgress,
	defaultScheduleForm,
	deliverText,
	dialText,
	scheduleFormOf,
	scheduleText
} from './schedule-text';

describe('scheduleText', () => {
	it('says the common cron shapes in words', () => {
		expect(cronText('0 7 * * 1')).toBe('每周一 07:00');
		expect(cronText('0 3 * * 4')).toBe('每周四 03:00');
		expect(cronText('30 9 * * *')).toBe('每天 09:30');
		expect(cronText('0 9 * * 1-5')).toBe('工作日 09:00');
		expect(cronText('0 9 * * 1,3,5')).toBe('每周一、三、五 09:00');
		expect(cronText('0 8 15 * *')).toBe('每月 15 日 08:00');
		expect(cronText('*/15 * * * *')).toBe('每 15 分钟');
		expect(cronText('0 */2 * * *')).toBe('每 2 小时');
		expect(cronText('5 * * * *')).toBe('每小时第 5 分');
		expect(cronText('0 9 1 1 *')).toBeNull();
	});

	it('falls back to hermes words for anything else', () => {
		expect(scheduleText({ kind: 'cron', expr: '0 9 1 1 *', display: '0 9 1 1 *' })).toBe('0 9 1 1 *');
		expect(scheduleText({ kind: 'interval', minutes: 120 })).toBe('每 2 小时');
		expect(scheduleText({ kind: 'interval', minutes: 1440 })).toBe('每 1 天');
		expect(scheduleText({ kind: 'once', run_at: '2026-10-12T08:05:00' })).toBe('一次 · 10 月 12 日 08:05');
		expect(scheduleText(null, '—')).toBe('—');
	});
});

describe('buildSchedule', () => {
	const form = (patch: object) => ({ ...defaultScheduleForm(), ...patch });

	it('makes the cron hermes parses', () => {
		expect(buildSchedule(form({ frequency: 'daily', time: '07:30' }))).toEqual({ schedule: '30 7 * * *' });
		expect(buildSchedule(form({ frequency: 'weekdays', time: '09:00' }))).toEqual({ schedule: '0 9 * * 1-5' });
		expect(buildSchedule(form({ frequency: 'weekly', time: '03:00', weekday: 4 }))).toEqual({
			schedule: '0 3 * * 4'
		});
		expect(buildSchedule(form({ frequency: 'monthly', time: '08:00', day: 15 }))).toEqual({
			schedule: '0 8 15 * *'
		});
		expect(buildSchedule(form({ frequency: 'every', every: 6, unit: 'h' }))).toEqual({ schedule: 'every 6h' });
		const once = buildSchedule(form({ frequency: 'once', at: '2099-01-02T08:30' }));
		expect('schedule' in once && once.schedule).toMatch(/^2099-01-02T08:30:00[+-]\d{2}:\d{2}$/);
		expect(buildSchedule(form({ frequency: 'custom', custom: ' every monday 9am ' }))).toEqual({
			schedule: 'every monday 9am'
		});
	});

	it('says what is wrong instead of sending it', () => {
		expect('error' in buildSchedule(form({ frequency: 'daily', time: '25:00' }))).toBe(true);
		expect('error' in buildSchedule(form({ frequency: 'monthly', day: 31 }))).toBe(true);
		expect('error' in buildSchedule(form({ frequency: 'every', every: 1, unit: 'm' }))).toBe(true);
		expect('error' in buildSchedule(form({ frequency: 'once', at: '2020-01-01T08:00' }))).toBe(true);
		expect('error' in buildSchedule(form({ frequency: 'custom', custom: '  ' }))).toBe(true);
	});

	it('round-trips a job schedule into the picker', () => {
		expect(scheduleFormOf({ kind: 'cron', expr: '0 7 * * 1' })).toMatchObject({
			frequency: 'weekly',
			time: '07:00',
			weekday: 1
		});
		expect(scheduleFormOf({ kind: 'cron', expr: '0 7 * * 7' })).toMatchObject({ weekday: 0 });
		expect(scheduleFormOf({ kind: 'cron', expr: '0 9 * * 1-5' }).frequency).toBe('weekdays');
		expect(scheduleFormOf({ kind: 'interval', minutes: 90 })).toMatchObject({ every: 90, unit: 'm' });
		expect(scheduleFormOf({ kind: 'cron', expr: '0 9 1 1 *' })).toMatchObject({
			frequency: 'custom',
			custom: '0 9 1 1 *'
		});
		const once = scheduleFormOf({ kind: 'once', run_at: '2026-10-12T08:05:00' });
		expect(once).toMatchObject({ frequency: 'once', at: '2026-10-12T08:05' });
	});
});

describe('deliverText', () => {
	it('names where a result goes', () => {
		expect(deliverText('telegram:5231')).toBe('发到 Telegram');
		expect(deliverText('local')).toBe('只保存在 Hermes');
		expect(deliverText('origin')).toBe('发回创建它的会话');
	});
});

describe('dials and countdown', () => {
	it('reads a job time as a dial', () => {
		expect(dialText('每周一 07:00')).toEqual({ main: '07:00', sub: '每周一' });
		expect(dialText('工作日 08:30')).toEqual({ main: '08:30', sub: '工作日' });
		expect(dialText('一次 · 10 月 12 日 08:00')).toEqual({ main: '08:00', sub: '10 月 12 日' });
		expect(dialText('每 2 小时')).toEqual({ main: '2', sub: '小时一次' });
		expect(dialText('每小时')).toEqual({ main: '1', sub: '小时一次' });
		expect(dialText('每 30 分钟')).toEqual({ main: '30', sub: '分钟一次' });
		expect(dialText('every monday 9am').main).toBe('∗');
	});

	it('measures the way from the last run to the next', () => {
		const now = Date.parse('2026-10-10T08:00:00+08:00');
		const job = (next: string | null, last: string | null, schedule: any = { kind: 'cron', expr: '0 7 * * 1' }) => ({
			next_run_at: next,
			last_run_at: last,
			schedule
		});
		expect(cycleProgress(job('2026-10-12T07:00:00+08:00', '2026-10-05T07:00:00+08:00'), now)).toBeCloseTo(
			(7 * 24 - 47) / (7 * 24)
		);
		expect(cycleProgress(job('2026-10-10T09:00:00+08:00', null, { kind: 'interval', minutes: 120 }), now)).toBeCloseTo(0.5);
		expect(cycleProgress(job('2026-10-10T09:00:00+08:00', null), now)).toBe(0);
		expect(cycleProgress(job(null, '2026-10-05T07:00:00+08:00'), now)).toBeNull();
	});

	it('counts down in the two largest units', () => {
		const now = Date.parse('2026-10-10T08:00:00+08:00');
		expect(countdownParts('2026-10-12T07:00:00+08:00', now)).toEqual([['1', '天'], ['23', '小时']]);
		expect(countdownParts('2026-10-10T08:05:30+08:00', now)).toEqual([['5', '分'], ['30', '秒']]);
		expect(countdownParts('2026-10-10T07:00:00+08:00', now)).toEqual([]);
		expect(countdownParts(null, now)).toEqual([]);
	});
});
