// HaloWebUI adapter: upstream renders tree labels with marked plus a raw-HTML filter. Card diagrams
// come from text inside the designer's HTML, so labels are escaped and get only **bold** and `code`.
import { esc } from './svg/text.js';

export function mdInline(text) {
	return esc(text)
		.replace(/`([^`]+)`/g, '<code>$1</code>')
		.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
}
