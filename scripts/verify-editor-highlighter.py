"""Local Chromium regression for CodeMirror + the installed Shiki plugin.

Builds only a small test entry (not the application or a container). Exercises
the pre-fix synchronous options and the actual application's fixed adapter.
"""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading

from playwright.sync_api import sync_playwright


REPO = Path(__file__).resolve().parents[1]
BUILD = r"""
import {build} from 'esbuild';
const entry = `
import {EditorState, Compartment} from '@codemirror/state';
import {EditorView} from '@codemirror/view';
import shiki from 'codemirror-shiki';
import {createHighlighterCore} from 'shiki/core';
import {createJavaScriptRegexEngine} from 'shiki/engine/javascript';
import javascript from 'shiki/langs/javascript.mjs';
import githubDark from 'shiki/themes/github-dark.mjs';
import {createEditorHighlighter} from './src/lib/utils/editor-highlighter.ts';
const highlighter = await createHighlighterCore({langs:[javascript],themes:[githubDark],engine:createJavaScriptRegexEngine()});
const errors = [];
const syntax = new Compartment();
const view = new EditorView({parent:document.body,state:EditorState.create({doc:'const response = "waiting";',extensions:[EditorView.exceptionSink.of(error=>errors.push(String(error))),syntax.of([])]})});
const options = {highlighter,language:'javascript',theme:'github-dark'};
const extension = location.search.includes('unsafe') ? shiki(options) : createEditorHighlighter(shiki,options);
view.dispatch({effects:syntax.reconfigure(extension)});
await new Promise(resolve=>setTimeout(resolve,100));
view.dispatch({changes:{from:0,to:view.state.doc.length,insert:'const response = "updated";'}});
await new Promise(resolve=>setTimeout(resolve,150));
window.result = {errors,text:view.state.doc.toString(),coloredTokens:document.querySelectorAll('.cm-content span[style]').length};
`;
await build({stdin:{contents:entry,resolveDir:process.cwd(),sourcefile:'editor-regression.ts',loader:'ts'},bundle:true,format:'esm',target:'es2022',outfile:process.argv[2]+'/app.js',logLevel:'warning'});
"""


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass


with tempfile.TemporaryDirectory(prefix="halo-editor-regression-") as directory:
    root = Path(directory)
    subprocess.run(
        ["node", "--input-type=module", "-", directory],
        input=BUILD,
        text=True,
        cwd=REPO,
        check=True,
    )
    (root / "index.html").write_text(
        '<!doctype html><script type="module" src="/app.js"></script>'
    )
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(QuietHandler, directory=directory)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    results = {}
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE"),
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            for mode in ["unsafe", "fixed"]:
                page = browser.new_page()
                page.goto(f"http://127.0.0.1:{server.server_port}/?{mode}")
                page.wait_for_function("window.result !== undefined", timeout=15000)
                results[mode] = page.evaluate("window.result")
                assert (
                    page.locator(".cm-content").inner_text()
                    == 'const response = "updated";'
                )
                page.close()
            browser.close()
        assert any(
            "Calls to EditorView.update" in error
            for error in results["unsafe"]["errors"]
        ), results
        assert results["fixed"]["errors"] == [], results
        assert results["fixed"]["coloredTokens"] > 0, results
        print(json.dumps({"result": "passed", **results}))
    finally:
        server.shutdown()
        server.server_close()
