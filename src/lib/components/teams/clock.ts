import { readable } from 'svelte/store';

/** Seconds since the epoch, ticking once a second while anything on the page shows a timer. */
export const now = readable(Date.now() / 1000, (set) => {
	set(Date.now() / 1000);
	const timer = setInterval(() => set(Date.now() / 1000), 1000);
	return () => clearInterval(timer);
});

/** "3 秒前" / "12 分钟前" / "昨天 21:40" / "9月30日" — for lists and the activity line. */
export const timeAgo = (ts: number | null | undefined, at: number = Date.now() / 1000): string => {
	if (!ts) return '';
	const s = Math.max(0, at - ts);
	if (s < 10) return '刚刚';
	if (s < 60) return `${Math.floor(s)} 秒前`;
	if (s < 3600) return `${Math.floor(s / 60)} 分钟前`;
	const d = new Date(ts * 1000);
	const today = new Date(at * 1000);
	const hm = d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false });
	if (d.toDateString() === today.toDateString()) return `今天 ${hm}`;
	const y = new Date(today);
	y.setDate(today.getDate() - 1);
	if (d.toDateString() === y.toDateString()) return `昨天 ${hm}`;
	return d.getFullYear() === today.getFullYear()
		? `${d.getMonth() + 1}月${d.getDate()}日 ${hm}`
		: `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`;
};

/** Elapsed time, compact: "42s", "3m 05s", "1h 12m". */
export const elapsed = (seconds: number): string => {
	const s = Math.max(0, Math.floor(seconds));
	if (s < 60) return `${s}s`;
	const m = Math.floor(s / 60);
	if (m < 60) return `${m}m ${String(s % 60).padStart(2, '0')}s`;
	const h = Math.floor(m / 60);
	return `${h}h ${String(m % 60).padStart(2, '0')}m`;
};
