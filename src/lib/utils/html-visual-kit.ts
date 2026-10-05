// Design kit for AI-designed answer cards. The designer writes compact semantic
// HTML with `hv-*` classes under a `<div class="hv" data-theme="…">` root; the
// preview frame supplies this stylesheet. Classes instead of inline styles keep
// the designer's output (and so its latency) about three times smaller, and the
// themes give each kind of question its own look. The class vocabulary is
// documented to the designer in backend html_visual_prompt.py
// (HTML_VISUAL_AGY_HTML_REQUEST_PROMPT); keep both in step.
//
// Dark mode: the frame's <html> carries data-halo-color-scheme, which tells the
// generic dark-adaptation bridge to leave kit cards alone.

export const HTML_VISUAL_KIT_THEMES = [
	'ion',
	'aurora',
	'terminal',
	'paper',
	'sunset',
	'mint',
	'finance'
] as const;

const KIT_ROOT_RE = /<[a-z][^>]*\bclass\s*=\s*["'](?:[^"']*\s)?hv(?:\s[^"']*)?["']/i;

export const usesHtmlVisualKit = (html: unknown): boolean =>
	typeof html === 'string' && KIT_ROOT_RE.test(html);

export const HTML_VISUAL_KIT_CSS = `
html,body{margin:0;padding:0}
.hv{--a:#2c56f1;--a2:#7c3aed;--ink:#11141b;--ink2:#3a3f4b;--muted:#6b7080;--line:#e4e6ec;--surface:#fff;--panel:#f5f6f9;--hero-ink:var(--ink);--hero-bg:radial-gradient(120% 140% at 0% 0%,color-mix(in oklab,var(--a) 16%,transparent),transparent 55%),radial-gradient(90% 120% at 100% 0%,color-mix(in oklab,var(--a2) 14%,transparent),transparent 60%),var(--panel);--hero-line:color-mix(in oklab,var(--a) 22%,var(--line));--ok:#16a34a;--warn:#d97706;--risk:#dc2626;--note:var(--a);--radius:16px;--font:-apple-system,BlinkMacSystemFont,"SF Pro Text","PingFang SC","HarmonyOS Sans SC","MiSans","Microsoft YaHei","Noto Sans CJK SC",sans-serif;--head:var(--font);--mono:"JetBrains Mono","SF Mono",ui-monospace,Menlo,Consolas,monospace;box-sizing:border-box;max-width:920px;margin:0 auto;padding:20px 16px 24px;color:var(--ink2);font:15px/1.7 var(--font);-webkit-font-smoothing:antialiased;overflow-wrap:anywhere}
.hv *,.hv *::before,.hv *::after{box-sizing:border-box}
.hv>*+*{margin-top:18px}
.hv h1,.hv h2,.hv h3,.hv h4{font-family:var(--head);color:var(--ink);margin:0;line-height:1.3;letter-spacing:-.01em}
.hv h1{font-size:28px;font-weight:750}
.hv h2{font-size:19px;font-weight:700}
.hv h3{font-size:16px;font-weight:650}
.hv p{margin:0}.hv p+p{margin-top:8px}
.hv ul,.hv ol{margin:0;padding-left:1.3em}.hv li+li{margin-top:4px}.hv li::marker{color:var(--a)}
.hv strong,.hv b{color:var(--ink);font-weight:650}
.hv a{color:var(--a);text-decoration:none;border-bottom:1px solid color-mix(in oklab,var(--a) 35%,transparent)}
.hv code{font:.88em/1.5 var(--mono);background:color-mix(in oklab,var(--a) 9%,var(--panel));color:var(--ink);padding:.12em .42em;border-radius:6px}
.hv pre{margin:0;background:#0d1017;color:#e4e7ee;border-radius:12px;padding:14px 16px;overflow:auto;font:13px/1.65 var(--mono);white-space:pre-wrap;border:1px solid #1d2230}
.hv pre code{background:none;color:inherit;padding:0;font:inherit}
.hv hr{border:0;height:1px;background:var(--line);margin:4px 0}
.hv-grad{background:linear-gradient(100deg,var(--a),var(--a2));-webkit-background-clip:text;background-clip:text;color:transparent}
.hv-hero{position:relative;overflow:hidden;padding:26px 26px 24px;border-radius:calc(var(--radius) + 4px);background:var(--hero-bg);border:1px solid var(--hero-line);color:var(--hero-ink)}
.hv-hero::after{content:"";position:absolute;inset:0;pointer-events:none;background:repeating-linear-gradient(90deg,color-mix(in oklab,var(--hero-ink) 5%,transparent) 0 1px,transparent 1px 28px),repeating-linear-gradient(0deg,color-mix(in oklab,var(--hero-ink) 5%,transparent) 0 1px,transparent 1px 28px);-webkit-mask-image:linear-gradient(120deg,#000,transparent 70%);mask-image:linear-gradient(120deg,#000,transparent 70%)}
.hv-hero>*{position:relative;z-index:1}
.hv-hero>*+*{margin-top:10px}
.hv-hero h1{color:var(--hero-ink)}
.hv-lead{font-size:16px;color:color-mix(in oklab,var(--hero-ink) 72%,transparent);max-width:46em}
.hv-eyebrow{display:inline-flex;align-items:center;gap:8px;font-size:12px;font-weight:650;letter-spacing:.1em;text-transform:uppercase;color:var(--a)}
.hv-eyebrow::before{content:"";width:8px;height:8px;border-radius:50%;background:linear-gradient(135deg,var(--a),var(--a2));box-shadow:0 0 0 4px color-mix(in oklab,var(--a) 18%,transparent)}
.hv-hero .hv-stats{margin-top:18px}
.hv-tldr{position:relative;padding:16px 18px 16px 20px;border-radius:var(--radius);background:linear-gradient(100deg,color-mix(in oklab,var(--a) 10%,var(--surface)),var(--surface) 70%);border:1px solid color-mix(in oklab,var(--a) 26%,var(--line));color:var(--ink);font-size:16px;font-weight:500}
.hv-tldr::before{content:"";position:absolute;left:0;top:14px;bottom:14px;width:4px;border-radius:0 4px 4px 0;background:linear-gradient(var(--a),var(--a2))}
.hv-tldr>b:first-child,.hv-tldr>strong:first-child{display:block;font-size:12px;letter-spacing:.08em;color:var(--a);margin-bottom:4px}
.hv-sec>*+*{margin-top:12px}
.hv-sec>h2{display:flex;align-items:center;gap:10px}
.hv-sec>h2::before{content:"";flex:none;width:6px;height:20px;border-radius:3px;background:linear-gradient(var(--a),var(--a2))}
.hv-sub{color:var(--muted);font-size:14px}
.hv-grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(230px,1fr))}
.hv-grid[data-cols="2"]{grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}
.hv-card{position:relative;padding:16px 16px 15px;border-radius:var(--radius);background:var(--surface);border:1px solid var(--line);box-shadow:0 1px 2px rgba(17,20,27,.04),0 6px 18px -10px rgba(17,20,27,.12);transition:transform .2s ease,box-shadow .2s ease,border-color .2s ease}
.hv-card:hover{transform:translateY(-2px);border-color:color-mix(in oklab,var(--a) 40%,var(--line));box-shadow:0 12px 28px -14px color-mix(in oklab,var(--a) 45%,transparent)}
.hv-card>*+*{margin-top:6px}
.hv-card p,.hv-card li{font-size:14px}
.hv-card[data-tone]{border-top:3px solid var(--tone)}
.hv-card[data-tone="accent"]{--tone:var(--a)}
.hv-ico{display:inline-grid;place-items:center;width:38px;height:38px;border-radius:12px;font-size:20px;line-height:1;background:linear-gradient(135deg,color-mix(in oklab,var(--a) 16%,var(--surface)),color-mix(in oklab,var(--a2) 14%,var(--surface)));border:1px solid color-mix(in oklab,var(--a) 22%,var(--line));margin-bottom:4px}
.hv [data-tone="ok"]{--tone:var(--ok)}.hv [data-tone="warn"]{--tone:var(--warn)}.hv [data-tone="risk"]{--tone:var(--risk)}.hv [data-tone="note"],.hv [data-tone="tip"]{--tone:var(--note)}
.hv-stats{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(140px,1fr))}
.hv-stat{padding:14px 14px 12px;border-radius:14px;background:var(--surface);border:1px solid var(--line)}
.hv-hero .hv-stat{background:color-mix(in oklab,var(--surface) 70%,transparent);backdrop-filter:blur(6px)}
.hv-stat>b{display:block;font:750 26px/1.15 var(--head);font-variant-numeric:tabular-nums;letter-spacing:-.02em;background:linear-gradient(100deg,var(--a),var(--a2));-webkit-background-clip:text;background-clip:text;color:transparent}
.hv-stat>span{display:block;margin-top:4px;font-size:13px;color:var(--muted)}
.hv-delta{display:inline-block;font-style:normal;margin-top:6px;font-size:12px;font-weight:600;padding:1px 8px;border-radius:999px;color:var(--tone,var(--ok));background:color-mix(in oklab,var(--tone,var(--ok)) 12%,transparent)}
.hv-bars{display:grid;gap:10px}
.hv-bar{display:grid;grid-template-columns:minmax(80px,30%) 1fr auto;align-items:center;gap:12px;font-size:14px}
.hv-bar::after{content:"";grid-column:2;grid-row:1;height:10px;border-radius:999px;background:linear-gradient(90deg,var(--a),var(--a2)) 0/var(--v,50%) 100% no-repeat,color-mix(in oklab,var(--a) 10%,var(--panel))}
.hv-bar>span{grid-column:1;grid-row:1;color:var(--ink2)}
.hv-bar>b{grid-column:3;grid-row:1;font-variant-numeric:tabular-nums;color:var(--ink);min-width:3em;text-align:right}
.hv-steps,.hv-timeline{list-style:none;padding:0;margin:0;counter-reset:hv}
.hv-steps>li,.hv-timeline>li{position:relative;padding:0 0 18px 48px;margin:0}
.hv-steps>li:last-child,.hv-timeline>li:last-child{padding-bottom:0}
.hv-steps>li::before{counter-increment:hv;content:counter(hv);position:absolute;left:0;top:0;width:32px;height:32px;border-radius:10px;display:grid;place-items:center;font:700 14px/1 var(--head);color:#fff;background:linear-gradient(135deg,var(--a),var(--a2));box-shadow:0 6px 14px -6px color-mix(in oklab,var(--a) 70%,transparent)}
.hv-steps>li::after,.hv-timeline>li::after{content:"";position:absolute;left:15px;top:38px;bottom:4px;width:2px;background:linear-gradient(color-mix(in oklab,var(--a) 40%,transparent),transparent)}
.hv-steps>li:last-child::after,.hv-timeline>li:last-child::after{display:none}
.hv-timeline>li::before{content:"";position:absolute;left:9px;top:6px;width:14px;height:14px;border-radius:50%;background:var(--surface);border:3px solid var(--a);box-shadow:0 0 0 4px color-mix(in oklab,var(--a) 15%,transparent)}
.hv-timeline>li::after{left:15px;top:26px}
.hv-steps>li>*+*,.hv-timeline>li>*+*{margin-top:4px}
.hv-steps h3,.hv-timeline h3{padding-top:4px}
.hv-when{display:inline-block;font:600 12px/1.6 var(--mono);color:var(--a);background:color-mix(in oklab,var(--a) 10%,transparent);padding:1px 8px;border-radius:6px}
.hv-table{overflow-x:auto;border-radius:var(--radius);border:1px solid var(--line);background:var(--surface)}
.hv table{width:100%;border-collapse:collapse;font-size:14px}
.hv th{text-align:left;font-weight:650;color:var(--ink);background:color-mix(in oklab,var(--a) 7%,var(--panel));padding:10px 14px;border-bottom:1px solid var(--line);white-space:nowrap}
.hv td{padding:10px 14px;border-bottom:1px solid var(--line);vertical-align:top;overflow-wrap:break-word}
.hv td:first-child{min-width:5em}
.hv tr:last-child td{border-bottom:0}
.hv tbody tr:hover td{background:color-mix(in oklab,var(--a) 4%,transparent)}
.hv-yes,.hv-no,.hv-mid{display:inline-flex;align-items:center;gap:4px;font-size:13px;font-weight:600;padding:1px 9px;border-radius:999px;white-space:nowrap}
.hv-yes{color:var(--ok);background:color-mix(in oklab,var(--ok) 12%,transparent)}
.hv-no{color:var(--risk);background:color-mix(in oklab,var(--risk) 12%,transparent)}
.hv-mid{color:var(--warn);background:color-mix(in oklab,var(--warn) 13%,transparent)}
.hv-callout{--tone:var(--note);padding:14px 16px;border-radius:14px;background:color-mix(in oklab,var(--tone) 8%,var(--surface));border:1px solid color-mix(in oklab,var(--tone) 28%,var(--line));font-size:14px}
.hv-callout>b:first-child,.hv-callout>strong:first-child{display:block;color:var(--tone);margin-bottom:4px;font-size:14px}
.hv-callout>*+*{margin-top:4px}
.hv-quote{margin:0;padding:6px 0 6px 18px;border-left:3px solid var(--a);font-family:var(--head);font-size:17px;color:var(--ink);font-style:normal}
.hv-quote cite{display:block;margin-top:6px;font-size:13px;color:var(--muted);font-style:normal;font-family:var(--font)}
.hv-tags{display:flex;flex-wrap:wrap;gap:6px}
.hv-tag,.hv-badge{display:inline-flex;align-items:center;gap:4px;font-size:12px;font-weight:600;padding:3px 10px;border-radius:999px;color:var(--tone,var(--a));background:color-mix(in oklab,var(--tone,var(--a)) 11%,transparent);border:1px solid color-mix(in oklab,var(--tone,var(--a)) 22%,transparent);white-space:nowrap}
.hv-badge{padding:1px 8px;vertical-align:.1em}
.hv-kv{display:grid;grid-template-columns:minmax(90px,max-content) 1fr;gap:0;margin:0;border:1px solid var(--line);border-radius:var(--radius);overflow:hidden;background:var(--surface);font-size:14px}
.hv-kv dt,.hv-kv dd{margin:0;padding:10px 14px;border-bottom:1px solid var(--line)}
.hv-kv dt{color:var(--muted);background:var(--panel);font-weight:600}
.hv-kv dt:last-of-type,.hv-kv dd:last-of-type{border-bottom:0}
.hv-split{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}
.hv-code{border-radius:12px;overflow:hidden;border:1px solid #1d2230;background:#0d1017}
.hv-code>.hv-code-h{display:flex;align-items:center;gap:6px;padding:8px 14px;font:600 12px/1 var(--mono);color:#8b93a7;background:#141925;border-bottom:1px solid #1d2230}
.hv-code>.hv-code-h::before{content:"";width:10px;height:10px;border-radius:50%;background:#ff5f57;box-shadow:16px 0 0 #febc2e,32px 0 0 #28c840;margin-right:40px}
.hv-code>pre{border:0;border-radius:0}
.hv-foot{font-size:12.5px;color:var(--muted);padding-top:12px;border-top:1px dashed var(--line)}

.hv[data-theme="aurora"]{--a:#22d3ee;--a2:#a855f7;--hero-ink:#eef2ff;--hero-line:#26304d;--hero-bg:radial-gradient(70% 120% at 10% 0%,rgba(34,211,238,.32),transparent 60%),radial-gradient(60% 110% at 95% 10%,rgba(168,85,247,.38),transparent 60%),radial-gradient(80% 80% at 50% 120%,rgba(59,130,246,.3),transparent 70%),#0a0f1f}
.hv[data-theme="aurora"] .hv-hero .hv-eyebrow{color:#67e8f9}
.hv[data-theme="aurora"] .hv-hero .hv-stat{background:rgba(255,255,255,.06);border-color:rgba(255,255,255,.12)}
.hv[data-theme="aurora"] .hv-hero .hv-stat>span{color:#a5b0cc}
.hv[data-theme="aurora"] .hv-hero .hv-tag{color:#c4f1ff;background:rgba(34,211,238,.12);border-color:rgba(34,211,238,.3)}
.hv[data-theme="aurora"] .hv-card{background:linear-gradient(var(--surface),var(--surface)) padding-box,linear-gradient(135deg,color-mix(in oklab,var(--a) 50%,var(--line)),var(--line) 40%,color-mix(in oklab,var(--a2) 45%,var(--line))) border-box;border:1px solid transparent}
.hv[data-theme="terminal"]{--a:#16a34a;--a2:#0ea5e9;--hero-ink:#d7ffe4;--hero-line:#1f3b2b;--hero-bg:radial-gradient(80% 120% at 0% 0%,rgba(34,197,94,.22),transparent 60%),linear-gradient(180deg,#0b1410,#07100c);--head:var(--mono)}
.hv[data-theme="terminal"] .hv-hero h1::before{content:"$ ";color:#4ade80}
.hv[data-theme="terminal"] .hv-hero .hv-eyebrow{color:#4ade80}
.hv[data-theme="terminal"] .hv-hero .hv-stat{background:rgba(74,222,128,.06);border-color:rgba(74,222,128,.22)}
.hv[data-theme="terminal"] .hv-hero .hv-stat>span{color:#86a896}
.hv[data-theme="terminal"] .hv-hero .hv-tag{color:#bbf7d0;background:rgba(74,222,128,.1);border-color:rgba(74,222,128,.28)}
.hv[data-theme="terminal"] h1{font-size:24px}
.hv[data-theme="terminal"] .hv-card,.hv[data-theme="terminal"] .hv-stat,.hv[data-theme="terminal"] .hv-table,.hv[data-theme="terminal"] .hv-callout{border-radius:10px}
.hv[data-theme="paper"]{--a:#9f1239;--a2:#b45309;--ink:#1f1a17;--ink2:#3f3833;--muted:#7a6f66;--line:#e9e1d6;--panel:#f7f2ea;--surface:#fffdf9;--head:"Songti SC","Noto Serif CJK SC","Source Han Serif SC",STSong,Georgia,serif;--hero-bg:linear-gradient(135deg,#fbf6ee,#f3e9dc);--hero-line:#e4d6c3;--radius:10px}
.hv[data-theme="paper"] h1{font-size:30px;font-weight:700;letter-spacing:.01em}
.hv[data-theme="paper"] .hv-hero::after{display:none}
.hv[data-theme="paper"] .hv-hero{border-left:4px solid var(--a)}
.hv[data-theme="paper"] .hv-card{box-shadow:none}
.hv[data-theme="paper"] .hv-quote{font-size:19px;border-left-color:var(--a2)}
.hv[data-theme="sunset"]{--a:#f97316;--a2:#ec4899;--hero-bg:radial-gradient(90% 140% at 0% 0%,rgba(251,146,60,.3),transparent 60%),radial-gradient(80% 120% at 100% 10%,rgba(236,72,153,.26),transparent 60%),linear-gradient(135deg,#fff7ed,#fdf2f8);--hero-line:#fbd5c0;--radius:20px}
.hv[data-theme="mint"]{--a:#0d9488;--a2:#22c55e;--hero-bg:radial-gradient(90% 140% at 0% 0%,rgba(20,184,166,.24),transparent 60%),radial-gradient(70% 120% at 100% 0%,rgba(34,197,94,.2),transparent 60%),linear-gradient(135deg,#f0fdfa,#f0fdf4);--hero-line:#bfe9df}
.hv[data-theme="finance"]{--a:#b8860b;--a2:#1d4ed8;--hero-ink:#f7f3e8;--hero-line:#2a3550;--hero-bg:radial-gradient(70% 120% at 100% 0%,rgba(234,179,8,.25),transparent 60%),linear-gradient(135deg,#0f1a33,#111827);--radius:12px}
.hv[data-theme="finance"] .hv-hero .hv-eyebrow{color:#facc15}
.hv[data-theme="finance"] .hv-hero .hv-stat{background:rgba(255,255,255,.05);border-color:rgba(250,204,21,.22)}
.hv[data-theme="finance"] .hv-hero .hv-stat>span{color:#aab3c5}
.hv[data-theme="finance"] .hv-hero .hv-stat>b{background:linear-gradient(100deg,#fde68a,#facc15);-webkit-background-clip:text;background-clip:text}
.hv[data-theme="finance"] .hv-hero .hv-tag{color:#fde68a;background:rgba(250,204,21,.1);border-color:rgba(250,204,21,.3)}
.hv[data-theme="finance"] .hv-stat>b,.hv[data-theme="finance"] .hv-bar>b{font-family:var(--mono)}

html[data-halo-color-scheme="dark"] .hv{--ink:#eef0f5;--ink2:#c9cdd8;--muted:#8e94a3;--line:#3a3d48;--surface:#2d2f37;--panel:#33363f;color-scheme:dark}
html[data-halo-color-scheme="dark"] .hv:not([data-theme="aurora"]):not([data-theme="terminal"]):not([data-theme="finance"]){--hero-ink:var(--ink);--hero-bg:radial-gradient(120% 140% at 0% 0%,color-mix(in oklab,var(--a) 26%,transparent),transparent 55%),radial-gradient(90% 120% at 100% 0%,color-mix(in oklab,var(--a2) 22%,transparent),transparent 60%),#1f2128;--hero-line:color-mix(in oklab,var(--a) 30%,#3a3d48)}
html[data-halo-color-scheme="dark"] .hv{--ok:#4ade80;--warn:#fbbf24;--risk:#f87171}
html[data-halo-color-scheme="dark"] .hv:not([data-theme]),html[data-halo-color-scheme="dark"] .hv[data-theme="ion"]{--a:#81a7ff;--a2:#b48cff}
html[data-halo-color-scheme="dark"] .hv[data-theme="terminal"]{--a:#4ade80;--a2:#38bdf8}
html[data-halo-color-scheme="dark"] .hv[data-theme="paper"]{--a:#fb7185;--a2:#fbbf24;--head:"Songti SC","Noto Serif CJK SC","Source Han Serif SC",STSong,Georgia,serif}
html[data-halo-color-scheme="dark"] .hv[data-theme="sunset"]{--a:#fb923c;--a2:#f472b6}
html[data-halo-color-scheme="dark"] .hv[data-theme="mint"]{--a:#2dd4bf;--a2:#4ade80}
html[data-halo-color-scheme="dark"] .hv[data-theme="finance"]{--a:#facc15;--a2:#60a5fa}
html[data-halo-color-scheme="dark"] .hv pre,html[data-halo-color-scheme="dark"] .hv-code{background:#0b0d12;border-color:#232733}
html[data-halo-color-scheme="dark"] .hv-card{box-shadow:none}
html[data-halo-color-scheme="dark"] .hv-steps>li::before{color:#0b0d12}
@media (max-width:560px){.hv{padding:14px 10px 18px;font-size:14.5px}.hv h1{font-size:23px}.hv-hero{padding:20px 18px}.hv-bar{grid-template-columns:1fr auto}.hv-bar>span{grid-column:1/-1}.hv-bar::after{grid-column:1;grid-row:2}.hv-bar>b{grid-row:2;grid-column:2}}
@media (prefers-reduced-motion:reduce){.hv-card{transition:none}.hv-card:hover{transform:none}}
`
	.trim()
	.replace(/\n+/g, '');

/** Copied card source keeps its look outside the preview frame (light palette). */
export const withHtmlVisualKitStyles = (html: string): string =>
	usesHtmlVisualKit(html) ? `<style>${HTML_VISUAL_KIT_CSS}</style>\n${html}` : html;
