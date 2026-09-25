/** "42s", "3m", "3m 5s": how long a reply has been generating. */
export const formatElapsedSeconds = (seconds: number): string => {
	if (seconds < 60) return `${seconds}s`;
	const minutes = Math.floor(seconds / 60);
	const rest = seconds % 60;
	return rest > 0 ? `${minutes}m ${rest}s` : `${minutes}m`;
};
