// HaloWebUI adapter: answer cards are laid out left to right, so upstream's right-to-left isolation
// (src/bidi.js) is not needed. Same signature: the line is returned unchanged.
export const svgLine = (line) => line;
