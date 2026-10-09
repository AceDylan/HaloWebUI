import { describe, expect, it } from 'vitest';
import {
	buildSchedule,
	cronText,
	defaultScheduleForm,
	deliverText,
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
