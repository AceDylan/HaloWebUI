/**
 * KaTeX's default `strict: 'warn'` logs one `console.warn` per offending character, and the
 * most common offender by far is ordinary CJK prose written inside math mode (`$能量$`), which
 * models emit constantly. A single long answer can therefore push tens of thousands of
 * identical `unicodeTextInMathMode` warnings into the console; with devtools open that alone
 * is enough to lock up the tab. The warnings are advisory only — KaTeX renders exactly the
 * same markup whether they are emitted or not.
 */
export const KATEX_STRICT = 'ignore' as const;
