"""Exercise the real MessageInput in Chromium with synthetic data and a mocked settings API.

Requires the frontend node_modules, Python Playwright and its Chromium browser.
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH can select an already installed Chromium.
HALO_PICKER_ARTIFACTS optionally retains screenshots in the specified directory.
Runs a temporary Vite dev server (no build/backend/proxy), one browser context at
a time; removes its server, browser and temporary files even when a check fails.
"""

import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

from playwright.sync_api import expect, sync_playwright


REPO = Path(__file__).resolve().parents[1]
TEMPLATES = [
    {
        "id": f"template-{i}",
        "name": f"{'长名称用于区分不同画面构图与风格' * 4}-{i}",
        "tags": ["水彩" if i == 22 else "摄影"],
        "createdAt": 1,
        "updatedAt": 23 - i,
        "config": {
            "prompt": f"完整提示词 {i}\n"
            + ("Unique Lighthouse" if i == 22 else "mountains")
            + "\n保留正文与已有输入  "
        },
    }
    for i in range(23)
]
# Also check wrapping for long names without any natural word boundaries.
TEMPLATES[0]["name"] = "LongUnbrokenTemplateName" * 5


def write_fixture(root):
    (root / "node_modules").symlink_to(REPO / "node_modules", target_is_directory=True)
    (root / "package.json").write_text('{"type":"module"}')
    (root / "index.html").write_text(
        '<!doctype html><html><head><meta name="viewport" '
        'content="width=device-width, initial-scale=1"></head>'
        '<body><div id="app"></div><script type="module" src="/main.js"></script></body></html>'
    )
    (root / "environment.js").write_text(
        "export const browser=true, dev=true, building=false, version='test';"
    )
    (root / "navigation.js").write_text(
        "export const goto=async()=>{}, invalidate=async()=>{}, invalidateAll=async()=>{}, "
        "beforeNavigate=()=>{}, afterNavigate=()=>{}, onNavigate=()=>{};"
    )
    (root / "app-stores.js").write_text(
        "import {writable} from 'svelte/store';"
        "export const page=writable({url:new URL(location.href),params:{},data:{}}), "
        "navigating=writable(null), updated=writable(false);"
    )
    (root / "main.js").write_text(
        f"import '/@fs{REPO}/src/tailwind.css';\n"
        f"import '/@fs{REPO}/src/app.css';\n"
        "import App from './App.svelte'; new App({target:document.getElementById('app')});"
    )
    (root / "App.svelte").write_text(
        """<script>
import {setContext, tick, onMount} from 'svelte';
import {writable, get} from 'svelte/store';
import MessageInput from '$lib/components/chat/MessageInput.svelte';
import {config, user, models, settings, prompts, imageStudioTemplates, mobile} from '$lib/stores';
import {getUserSettings} from '$lib/apis/users';
import {applyUserSettingsSnapshot} from '$lib/utils/user-settings';
import zh from '$lib/i18n/locales/zh-CN/translation.json';
const tr = {language:'zh-CN', resolvedLanguage:'zh-CN',
 t:(key, opts)=>zh[key] || opts?.defaultValue || key, exists:(key)=>!!zh[key]};
setContext('i18n', writable(tr));
config.set({features:{enable_image_generation:true}, file:{}});
user.set({id:'fixture', role:'admin', permissions:{}});
models.set([
 {id:'gpt-4o', name:'gpt-4o', info:{meta:{capabilities:{vision:true}}}},
 {id:'gpt-image-1', name:'gpt-image-1', info:{meta:{capabilities:{vision:true}}}},
]);
settings.set({richTextInput:false});
onMount(async()=>applyUserSettingsSnapshot(await getUserSettings('fixture')));
mobile.set(matchMedia('(pointer: coarse)').matches);
prompts.set([{command:'/chat', title:'Chat only', content:'Chat instruction'},
 ...Array.from({length:11},(_,i)=>({id:'chat-'+i, command:'/chat-'+i, name:'Chat '+i, content:'Instruction '+i}))]);
imageStudioTemplates.set(TEMPLATE_DATA);
let prompt='已有输入';
let imageMode=true;
let selectedModels=['gpt-4o'];
let submits=0;
window.fixture = {
 mode:async(value)=>{imageMode=value; await tick();},
 model:async(value)=>{selectedModels=[value]; await tick();},
 rich:async(value)=>{settings.set({richTextInput:value}); await tick();},
 prompt:async(value)=>{prompt=value; await tick();},
 templates:()=>get(imageStudioTemplates),
 submits:()=>submits,
};
</script>
<main id="chat-container" class="mx-auto max-w-3xl p-3">
 <h1 class="mb-4">提示词选择验证</h1>
 <MessageInput bind:prompt bind:imageGenerationEnabled={imageMode} {selectedModels}
  history={{messages:{}, currentId:null}} createMessagePair={()=>submits++}
  stopResponse={()=>{}} />
</main>
""".replace(
            "TEMPLATE_DATA", json.dumps(TEMPLATES, ensure_ascii=False)
        )
    )
    (root / "server.mjs").write_text(
        """import {createServer} from 'vite';
import {svelte, vitePreprocess} from '@sveltejs/vite-plugin-svelte';
import tailwind from '@tailwindcss/postcss';
const root=process.cwd();
const server=await createServer({
 configFile:false, root, publicDir:false, cacheDir:root+'/.vite',
 plugins:[svelte({configFile:false, preprocess:vitePreprocess()})],
 resolve:{alias:{'$lib':REPO+'/src/lib', '$app/environment':root+'/environment.js',
 '$app/navigation':root+'/navigation.js', '$app/stores':root+'/app-stores.js'}},
 css:{postcss:{plugins:[tailwind()]}},
 define:{APP_VERSION:'"test"', APP_BUILD_HASH:'"test"', APP_ENABLE_PYODIDE:'false',
 APP_PYODIDE_INDEX_URL:'""'},
 server:{host:'127.0.0.1', port:0, fs:{allow:[root,REPO]},
 watch:{ignored:['**/vite.log']}},
});
await server.listen();
console.log('READY '+server.resolvedUrls.local[0]);
process.on('SIGTERM',async()=>{await server.close();process.exit(0);});
""".replace(
            "REPO", json.dumps(str(REPO))
        )
    )


def verify_context(browser, url, *, phone=False, width=1280, rich=False):
    context = browser.new_context(
        viewport={"width": width, "height": 780 if phone else 900},
        is_mobile=phone,
        has_touch=phone,
        device_scale_factor=1,
        color_scheme="dark" if phone else "light",
    )
    errors, api_writes = [], []
    saved_settings = {"ui": {"richTextInput": False}, "revision": 0}
    page = context.new_page()
    page.set_default_timeout(15000)
    page.on("pageerror", lambda error: errors.append(str(error)))

    def route_request(route):
        request = route.request
        if "/api/" in request.url:
            if request.url.endswith("/users/user/settings/update"):
                patch = request.post_data_json
                assert patch["revision"] == saved_settings["revision"]
                assert set(patch["ui"]).issubset({"chatPromptOrder", "imagePromptOrder"})
                saved_settings["ui"].update(patch["ui"])
                saved_settings["revision"] += 1
                route.fulfill(status=200, content_type="application/json", body=json.dumps(saved_settings))
            elif request.url.endswith("/users/user/settings"):
                route.fulfill(status=200, content_type="application/json", body=json.dumps(saved_settings))
            else:
                if request.method != "GET":
                    api_writes.append(request.method + " " + request.url)
                route.fulfill(status=200, content_type="application/json", body="[]")
        elif request.url.startswith(url):
            route.continue_()
        else:
            route.abort()

    context.route("**/*", route_request)
    try:
        page.goto(url, wait_until="networkidle", timeout=120000)
        if phone:
            page.evaluate("document.documentElement.classList.add('dark')")
        if rich:
            page.evaluate("fixture.rich(true)")
        editor = page.locator("#chat-input")
        expect(editor).to_be_visible()
        trigger = page.locator('[data-halo-quick-commands="image"]')
        expect(trigger).to_be_in_viewport(ratio=1)
        expect(trigger).to_contain_text("23")
        (trigger.tap if phone else trigger.click)()
        dialog = page.get_by_role("dialog", name="生图提示词", exact=True)
        expect(dialog).to_be_visible()
        search = dialog.get_by_role("searchbox")
        if phone:
            expect(
                search
            ).not_to_be_focused()  # Opening should not summon the soft keyboard.
        else:
            expect(search).to_be_focused()
        expect(dialog.locator("[data-prompt-select]")).to_have_count(23)
        first = dialog.get_by_role("button", name=TEMPLATES[0]["name"], exact=True)
        assert first.evaluate("el => el.scrollWidth <= el.clientWidth + 1")
        assert first.locator("span").first.evaluate(
            "el => el.clientHeight > parseFloat(getComputedStyle(el).lineHeight)"
        ), "Long names should wrap, including an unbroken Latin name"
        assert dialog.evaluate("el => el.scrollWidth <= el.clientWidth + 1")
        box = dialog.bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= width
        if os.environ.get("HALO_PICKER_ARTIFACTS"):
            artifacts = Path(os.environ["HALO_PICKER_ARTIFACTS"])
            artifacts.mkdir(parents=True, exist_ok=True)
            page.screenshot(
                path=str(
                    artifacts / f"picker-{width}-{'rich' if rich else 'plain'}.png"
                )
            )

        # Actual mouse wheel / touch scroll reaches the oldest (23rd) template.
        last = dialog.get_by_role("button", name=TEMPLATES[22]["name"], exact=True)
        expect(last).not_to_be_in_viewport()
        if phone:
            session = context.new_cdp_session(page)
            scroller = dialog.locator("[aria-busy]")
            for _ in range(30):
                before = scroller.evaluate("el => el.scrollTop")
                x = box["x"] + box["width"] / 2
                y = box["y"] + box["height"] * 0.8
                session.send(
                    "Input.dispatchTouchEvent",
                    {
                        "type": "touchStart",
                        "touchPoints": [{"x": x, "y": y}],
                    },
                )
                for step in range(1, 11):
                    session.send(
                        "Input.dispatchTouchEvent",
                        {
                            "type": "touchMove",
                            "touchPoints": [{"x": x, "y": y - step * 30}],
                        },
                    )
                    page.wait_for_timeout(16)
                session.send(
                    "Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []}
                )
                page.wait_for_timeout(80)
                if scroller.evaluate(
                    "el => el.scrollTop + el.clientHeight >= el.scrollHeight - 1"
                ):
                    break
                assert (
                    scroller.evaluate("el => el.scrollTop") > before
                ), "Touch should scroll the list"
            session.detach()
        else:
            first.hover()
            page.mouse.wheel(0, 10000)
        expect(last).to_be_in_viewport()
        (last.tap if phone else last.click)()
        expect(dialog).to_have_count(0)
        expected = TEMPLATES[22]["config"]["prompt"].rstrip() + "\n已有输入"
        if rich:
            expect(editor).to_have_text(
                expected.replace("\n", " "), use_inner_text=True
            )
        else:
            expect(editor).to_have_value(expected)
        expect(editor).to_be_focused()

        trigger.click()
        for query in ["-22", "水彩", "  unique LIGHTHOUSE  "]:
            search.fill(query)
            expect(last).to_be_visible()
            expect(dialog.locator("[data-prompt-select]")).to_have_count(1)
        search.fill("missing-query")
        expect(
            dialog.get_by_text("没有匹配的模板，换个关键词或标签试试")
        ).to_be_visible()
        search.fill("-22")
        search.press("ArrowDown")
        expect(last).to_be_focused()
        # Tab is trapped in the dialog, including its footer link.
        page.keyboard.press("Tab")
        expect(dialog.get_by_role("link", name="管理生图提示词")).to_be_focused()
        page.keyboard.press("Tab")
        expect(dialog.get_by_role("button", name="关闭", exact=True)).to_be_focused()
        page.keyboard.press("Escape")
        expect(dialog).to_have_count(0)
        expect(trigger).to_be_focused()
        trigger.click()
        expect(search).to_have_value("")
        expect(dialog.locator("[data-prompt-select]")).to_have_count(23)
        search.fill("-22")
        search.press("ArrowDown")
        page.keyboard.press("Enter")
        expect(dialog).to_have_count(0)
        expect(editor).to_be_focused()

        # Switch modes while the portal is open; the dialog and scroll lock must go away.
        trigger.click()
        page.evaluate("fixture.mode(false)")
        expect(dialog).to_have_count(0)
        expect(trigger).to_have_count(0)
        assert page.evaluate("getComputedStyle(document.body).overflow") != "hidden"
        page.evaluate("fixture.prompt('原有问题')")
        chat_trigger = page.locator('[data-halo-quick-commands="chat"]')
        expect(chat_trigger).to_be_in_viewport(ratio=1)
        chat = page.get_by_role("button", name="Chat only", exact=True)
        expect(chat).to_have_count(0)
        chat_trigger.click()
        expect(page.get_by_role("dialog").locator("[data-prompt-select]")).to_have_count(12)
        expect(chat).to_be_visible()
        chat.click()
        if rich:
            expect(editor).to_contain_text("Chat instruction")
            expect(editor).to_contain_text("原有问题")
        else:
            expect(editor).to_have_value("Chat instruction\n原有问题")
        expect(editor).to_be_focused()
        page.evaluate("fixture.model('gpt-image-1')")
        expect(
            trigger
        ).to_be_visible()  # Dedicated image model also enables image mode.
        expect(chat).to_have_count(0)
        # Persist both families through the real client settings API, then reload.
        for image_mode, item_id, setting in [
            (True, "template-22", "imagePromptOrder"),
            (False, "id:chat-10", "chatPromptOrder"),
        ]:
            page.evaluate("fixture.model('gpt-4o')")
            page.evaluate("value=>fixture.mode(value)", image_mode)
            page.locator('[data-halo-quick-commands]').click()
            picker = page.get_by_role("dialog")
            picker.get_by_role("button", name="排序提示词", exact=True).click()
            expect(picker.get_by_role("searchbox")).to_be_disabled()
            row = picker.locator(f'[data-prompt-id="{item_id}"]')
            row.get_by_role("button", name="置顶", exact=True).click()
            expect(picker.locator("[data-prompt-id]").first).to_have_attribute("data-prompt-id", item_id)
            expect(picker.get_by_role("status").last).to_have_text("提示词顺序已保存。")
            expect(row.get_by_role("button", name="上移", exact=True)).to_be_disabled()
            row.get_by_role("button", name="下移", exact=True).click()
            expect(picker.locator("[data-prompt-id]").nth(1)).to_have_attribute("data-prompt-id", item_id)
            row.get_by_role("button", name="上移", exact=True).click()
            expect(picker.locator("[data-prompt-id]").first).to_have_attribute("data-prompt-id", item_id)
            picker.get_by_role("button", name="完成", exact=True).click()
            picker.get_by_role("button", name="关闭", exact=True).click()
            assert saved_settings["ui"][setting][0] == item_id

        page.reload(wait_until="networkidle")
        for image_mode, item_id in [(True, "template-22"), (False, "id:chat-10")]:
            page.evaluate("value=>fixture.mode(value)", image_mode)
            page.locator('[data-halo-quick-commands]').click()
            picker = page.get_by_role("dialog")
            expect(picker.locator("[data-prompt-id]").first).to_have_attribute("data-prompt-id", item_id)
            picker.get_by_role("button", name="关闭", exact=True).click()
        assert page.evaluate("fixture.templates()") == TEMPLATES
        assert page.evaluate("fixture.submits()") == 0
        assert not api_writes, api_writes
        assert not errors, errors
        print(
            f"PASS: {'phone' if phone else 'desktop'} {width}px, "
            f"{'rich text' if rich else 'textarea'}; scrolling/search/keyboard/insertion/modes/sorting/reload",
            flush=True,
        )
    except Exception:
        print("Browser errors:", errors, flush=True)
        raise
    finally:
        context.close()


def main():
    with tempfile.TemporaryDirectory(prefix="halo-prompt-picker-") as temporary:
        root = Path(temporary)
        write_fixture(root)
        with (root / "vite.log").open("w+") as log:
            process = subprocess.Popen(
                ["node", "--max-old-space-size=1536", "server.mjs"],
                cwd=root,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env={**os.environ, "GOMAXPROCS": "2"},
            )
            try:
                deadline = time.monotonic() + 45
                url = None
                while time.monotonic() < deadline and process.poll() is None:
                    log.seek(0)
                    for line in log.read().splitlines():
                        if line.startswith("READY "):
                            url = line.removeprefix("READY ")
                    if url:
                        break
                    time.sleep(0.2)
                if not url:
                    raise RuntimeError("Temporary Vite server did not start")
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(
                        args=["--disable-dev-shm-usage"],
                        executable_path=os.environ.get(
                            "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"
                        ),
                    )
                    try:
                        verify_context(browser, url)
                        verify_context(browser, url, phone=True, width=390)
                        verify_context(browser, url, phone=True, width=320)
                        verify_context(browser, url, rich=True)
                        verify_context(browser, url, phone=True, width=390, rich=True)
                    finally:
                        browser.close()
            except Exception:
                log.seek(0)
                print("Vite log (tail):", log.read()[-5000:], flush=True)
                raise
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=5)


if __name__ == "__main__":
    main()
