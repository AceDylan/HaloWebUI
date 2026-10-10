// 定时任务: hermes schedules in words ("每周一 07:00"), and the page's 时间 picker turned into the
// schedule string hermes parses (a cron expression, "every 2h", or an ISO time for once).

export type ScheduleLike = {
	kind?: string;
	expr?: string;
	minutes?: number;
	run_at?: string;
	display?: string;
} | null;

const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六', '日'];
const pad = (n: number) => String(n).padStart(2, '0');
const isNum = (s: string) => /^\d+$/.test(s);

export const everyMinutesText = (minutes: number) => {
	if (minutes % 1440 === 0) return `每 ${minutes / 1440} 天`;
	if (minutes % 60 === 0) return minutes === 60 ? '每小时' : `每 ${minutes / 60} 小时`;
	return `每 ${minutes} 分钟`;
};

const weekdaysText = (dow: string) => {
	if (dow === '1-5') return '工作日';
	if (dow === '0,6' || dow === '6,0') return '周末';
	const parts = dow.split(',');
	if (!parts.every((p) => isNum(p) && Number(p) <= 7)) return null;
	return `每周${parts.map((p) => WEEKDAYS[Number(p)]).join('、')}`;
};

/** A 5-field cron expression in words; null when it is not one of the common shapes. */
export const cronText = (expr: string): string | null => {
	const fields = expr.trim().split(/\s+/);
	if (fields.length !== 5) return null;
	const [m, h, dom, mon, dow] = fields;
	if (mon !== '*') return null;
	if (isNum(m) && isNum(h)) {
		const at = `${pad(Number(h))}:${pad(Number(m))}`;
		if (dom === '*' && dow === '*') return `每天 ${at}`;
		if (dom === '*') {
			const days = weekdaysText(dow);
			return days ? `${days} ${at}` : null;
		}
		if (isNum(dom) && dow === '*') return `每月 ${Number(dom)} 日 ${at}`;
		return null;
	}
	if (dom !== '*' || dow !== '*') return null;
	const every = /^\*\/(\d+)$/;
	if (h === '*' && every.test(m)) return everyMinutesText(Number(m.match(every)![1]));
	if (h === '*' && isNum(m)) return `每小时第 ${Number(m)} 分`;
	if (isNum(m) && every.test(h)) {
		const n = Number(h.match(every)![1]);
		return `${n === 1 ? '每小时' : `每 ${n} 小时`}${Number(m) ? `（第 ${Number(m)} 分）` : ''}`;
	}
	return null;
};

const timeText = (iso: string) => {
	const d = new Date(iso);
	if (Number.isNaN(d.getTime())) return iso;
	return `${d.getMonth() + 1} 月 ${d.getDate()} 日 ${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

/** "每周一 07:00", "每 2 小时", "一次 · 10 月 12 日 08:00"; hermes' own words otherwise. */
export const scheduleText = (schedule: ScheduleLike, fallback = ''): string => {
	if (!schedule) return fallback;
	if (schedule.kind === 'cron' && schedule.expr) {
		return cronText(schedule.expr) ?? schedule.display ?? schedule.expr;
	}
	if (schedule.kind === 'interval' && schedule.minutes) return everyMinutesText(schedule.minutes);
	if (schedule.kind === 'once' && schedule.run_at) return `一次 · ${timeText(schedule.run_at)}`;
	return schedule.display ?? fallback;
};

// ---- the page's 时间 picker ----

export type ScheduleFrequency = 'daily' | 'weekdays' | 'weekly' | 'monthly' | 'every' | 'once' | 'custom';

export type ScheduleForm = {
	frequency: ScheduleFrequency;
	/** "HH:MM" for daily / weekdays / weekly / monthly */
	time: string;
	/** 0–6, Sunday first, for weekly */
	weekday: number;
	/** 1–28 for monthly */
	day: number;
	/** every N unit */
	every: number;
	unit: 'm' | 'h' | 'd';
	/** "YYYY-MM-DDTHH:MM" (datetime-local) for once */
	at: string;
	/** anything hermes parses, for custom */
	custom: string;
};

export const defaultScheduleForm = (): ScheduleForm => ({
	frequency: 'daily',
	time: '09:00',
	weekday: 1,
	day: 1,
	every: 2,
	unit: 'h',
	at: '',
	custom: ''
});

const hm = (time: string) => {
	const match = /^(\d{1,2}):(\d{2})$/.exec(time.trim());
	if (!match) return null;
	const h = Number(match[1]);
	const m = Number(match[2]);
	return h < 24 && m < 60 ? { h, m } : null;
};

/** The schedule string for hermes, or an error to show next to the picker. */
export const buildSchedule = (form: ScheduleForm): { schedule: string } | { error: string } => {
	switch (form.frequency) {
		case 'daily':
		case 'weekdays':
		case 'weekly':
		case 'monthly': {
			const t = hm(form.time);
			if (!t) return { error: '时间要写成 时:分，例如 09:00' };
			const dom = form.frequency === 'monthly' ? String(form.day) : '*';
			if (form.frequency === 'monthly' && !(form.day >= 1 && form.day <= 28)) {
				return { error: '每月只能选 1–28 日（每个月都有的日子）' };
			}
			const dow =
				form.frequency === 'weekdays' ? '1-5' : form.frequency === 'weekly' ? String(form.weekday) : '*';
			return { schedule: `${t.m} ${t.h} ${dom} * ${dow}` };
		}
		case 'every': {
			const n = Math.floor(Number(form.every));
			if (!(n >= 1)) return { error: '间隔至少是 1' };
			if (form.unit === 'm' && n < 5) return { error: '间隔太短：至少 5 分钟' };
			return { schedule: `every ${n}${form.unit}` };
		}
		case 'once': {
			if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(form.at)) return { error: '选一个运行的日期和时间' };
			const when = new Date(form.at);
			if (when.getTime() <= Date.now()) return { error: '这个时间已经过去了' };
			// With this browser's offset: the time picked here, whatever zone hermes is set to.
			const offset = -when.getTimezoneOffset();
			const sign = offset >= 0 ? '+' : '-';
			const abs = Math.abs(offset);
			return { schedule: `${form.at}:00${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}` };
		}
		default: {
			const text = form.custom.trim();
			return text ? { schedule: text } : { error: '写一个时间，例如 0 9 * * * 或 every 2h' };
		}
	}
};

/** The picker for an existing job's schedule (custom when it is not one the picker makes). */
export const scheduleFormOf = (schedule: ScheduleLike): ScheduleForm => {
	const form = defaultScheduleForm();
	if (!schedule) return form;
	if (schedule.kind === 'interval' && schedule.minutes) {
		const minutes = schedule.minutes;
		if (minutes % 1440 === 0) return { ...form, frequency: 'every', every: minutes / 1440, unit: 'd' };
		if (minutes % 60 === 0) return { ...form, frequency: 'every', every: minutes / 60, unit: 'h' };
		return { ...form, frequency: 'every', every: minutes, unit: 'm' };
	}
	if (schedule.kind === 'once' && schedule.run_at) {
		const d = new Date(schedule.run_at);
		if (!Number.isNaN(d.getTime())) {
			const at = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
			return { ...form, frequency: 'once', at };
		}
	}
	if (schedule.kind === 'cron' && schedule.expr) {
		const [m, h, dom, mon, dow] = schedule.expr.trim().split(/\s+/);
		if (isNum(m ?? '') && isNum(h ?? '') && mon === '*') {
			const time = `${pad(Number(h))}:${pad(Number(m))}`;
			if (dom === '*' && dow === '*') return { ...form, frequency: 'daily', time };
			if (dom === '*' && dow === '1-5') return { ...form, frequency: 'weekdays', time };
			if (dom === '*' && isNum(dow) && Number(dow) <= 7) {
				return { ...form, frequency: 'weekly', time, weekday: Number(dow) % 7 };
			}
			if (isNum(dom) && Number(dom) <= 28 && dow === '*') {
				return { ...form, frequency: 'monthly', time, day: Number(dom) };
			}
		}
		return { ...form, frequency: 'custom', custom: schedule.expr };
	}
	return { ...form, frequency: 'custom', custom: schedule.display ?? '' };
};

/** Where a job's result goes, in words. */
export const deliverText = (deliver: string | null | undefined) => {
	const value = String(deliver ?? '').trim();
	if (!value || value === 'local') return '只保存在 Hermes';
	if (value === 'origin') return '发回创建它的会话';
	const platform = value.split(':')[0];
	const names: Record<string, string> = { telegram: 'Telegram', qqbot: 'QQ', discord: 'Discord', slack: 'Slack' };
	return `发到 ${names[platform] ?? platform}`;
};

// ---- the page's dials and countdown ----

/** A job's time for its dial: "07:00" over "每周一", "2" over "小时一次". */
export const dialText = (text: string): { main: string; sub: string } => {
	const at = text.match(/\d{1,2}:\d{2}/);
	if (at) {
		const sub = text
			.replace(at[0], '')
			.replace(/^一次 · /, '')
			.replace(/\s+/g, ' ')
			.trim();
		return { main: at[0], sub };
	}
	const every = text.match(/^每\s*(\d+)?\s*(分钟|小时|天)/);
	if (every) return { main: every[1] ?? '1', sub: `${every[2]}一次` };
	return { main: '∗', sub: text.slice(0, 8) };
};

const toMs = (iso: string | null | undefined) => {
	const ms = iso ? new Date(iso).getTime() : NaN;
	return Number.isNaN(ms) ? null : ms;
};

/** How far a job is from its last run to its next one, 0–1; null when there is no next run. */
export const cycleProgress = (
	job: { next_run_at: string | null; last_run_at: string | null; schedule: ScheduleLike },
	now = Date.now()
): number | null => {
	const next = toMs(job.next_run_at);
	if (next === null) return null;
	const last = toMs(job.last_run_at);
	const period =
		job.schedule?.kind === 'interval' && job.schedule.minutes
			? job.schedule.minutes * 60_000
			: last !== null && next > last
				? next - last
				: null;
	if (!period) return 0;
	return Math.min(1, Math.max(0, 1 - (next - now) / period));
};

/** The time left until *iso* in its two largest units: [["2", "天"], ["23", "小时"]]. */
export const countdownParts = (iso: string | null | undefined, now = Date.now()) => {
	const at = toMs(iso);
	if (at === null) return [];
	const left = Math.max(0, Math.floor((at - now) / 1000));
	const units: [number, string][] = [
		[Math.floor(left / 86400), '天'],
		[Math.floor((left % 86400) / 3600), '小时'],
		[Math.floor((left % 3600) / 60), '分'],
		[left % 60, '秒']
	];
	const first = units.findIndex(([n]) => n > 0);
	if (first === -1) return [];
	return units.slice(first, first + 2).map(([n, unit]) => [String(n), unit] as [string, string]);
};
