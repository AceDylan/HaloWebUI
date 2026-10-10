// 协作台定时 in words: when the next (or last) run is, read in the browser's time.

const pad = (n: number) => String(n).padStart(2, '0');
const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六'];

/** "10 月 12 日 周一 09:00" for a time in seconds. */
export const scheduleWhen = (seconds: number | null | undefined): string => {
	if (!seconds) return '';
	const d = new Date(seconds * 1000);
	return `${d.getMonth() + 1} 月 ${d.getDate()} 日 周${WEEKDAYS[d.getDay()]} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
};
