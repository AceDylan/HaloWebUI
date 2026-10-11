# answer-me-with-html diagram components (vendored)

Source: https://github.com/QingYunA/answer-me-with-html (MIT, see LICENSE), version 0.5.0, commit 43d5314.

Copied unchanged: `svg/text.js`, `svg/shapes.js`, `components/{error,delta,flow,sequence,tree}.js`,
except one line in `components/flow.js` that imports `../dagre.js` instead of `@dagrejs/dagre`.

HaloWebUI adapters: `dagre.js` (dagre-d3-es, already installed with mermaid), `bidi.js` (left to right
only) and `markdown.js` (escaped labels with bold and code).

Used by `src/lib/utils/html-visual-diagrams.ts`: answer cards write `<pre class="hv-dia" data-kind="flow LR">`
and the preview turns it into SVG. To update, copy the files above again from upstream `src/` and run
`npx vitest run src/lib/utils/html-visual-diagrams.test.ts`.
