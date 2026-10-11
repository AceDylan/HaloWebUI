// HaloWebUI adapter: upstream imports @dagrejs/dagre. The same layout engine already ships with
// mermaid as dagre-d3-es (graphlib + dagre layout, MIT); only its layout half is imported, not d3.
import { Graph } from 'dagre-d3-es/src/graphlib/index.js';
import { layout } from 'dagre-d3-es/src/dagre/index.js';

export default { graphlib: { Graph }, layout };
