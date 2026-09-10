// codemirror-shiki dispatches from its plugin constructor when given a loaded
// highlighter. A compartment reconfiguration constructs plugins inside an
// EditorView update, where nested dispatch is forbidden. Its Promise branch
// schedules initialization after that update has finished.
export const createEditorHighlighter = <T, R>(
	create: (options: T) => R,
	options: T & { highlighter: unknown }
): R => create({ ...options, highlighter: Promise.resolve(options.highlighter) });
