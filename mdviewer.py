"""Markdown ビューア（Windows）。

使い方:
    MarkdownViewer.exe [ファイル.md | フォルダー]
    MarkdownViewer.exe --register     エクスプローラーの「プログラムから開く」に登録
    MarkdownViewer.exe --unregister   登録を解除

描画は Edge の WebView2（Windows 11 に標準で入っている）。Markdown は
Python 側で HTML にして画面へ渡す。文書に埋め込まれた HTML は sanitize.py で
許可したタグだけ残す（表などは表示し、スクリプトは動かさない）。
"""
import base64
import gzip
import ctypes
import json
import mimetypes
import os
import re
import sys
import webbrowser

import dialogs
import printing
from sanitize import sanitize

MD_EXTENSIONS = (".md", ".markdown", ".mdown", ".mkd")
PROG_ID = "MarkdownViewer.File"
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}
MAX_FILES = 5000
MAX_INLINE_IMAGE = 20 * 1024 * 1024


def resource_path(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def settings_path():
    return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                        "MarkdownViewer", "settings.json")


def load_settings():
    try:
        with open(settings_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(data):
    try:
        os.makedirs(os.path.dirname(settings_path()), exist_ok=True)
        with open(settings_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except OSError:
        pass


def read_text(path):
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8-sig", "cp932"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def is_markdown(path):
    return path.lower().endswith(MD_EXTENSIONS)


def list_markdown(folder):
    """フォルダー以下の Markdown を相対パスで返す（サブフォルダーも含む）。"""
    found = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs
                         if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(files):
            if is_markdown(name):
                rel = os.path.relpath(os.path.join(root, name), folder)
                found.append(rel.replace("\\", "/"))
                if len(found) >= MAX_FILES:
                    return found
    return found


from markdown_it.common.utils import escapeHtml


def make_renderer():
    from markdown_it import MarkdownIt
    from mdit_py_plugins.anchors import anchors_plugin
    from mdit_py_plugins.tasklists import tasklists_plugin

    md = MarkdownIt("commonmark", {"html": True})
    md.enable(["table", "strikethrough"])
    md.use(tasklists_plugin)
    md.use(anchors_plugin, min_level=1, max_level=6)

    def image(self, tokens, idx, options, env):
        tok = tokens[idx]
        tok.attrSet("src", inline_image(tok.attrGet("src") or "", env.get("base", "")))
        tok.attrSet("alt", self.renderInlineAsText(tok.children, options, env))
        return self.renderToken(tokens, idx, options, env)

    def fence(self, tokens, idx, options, env):
        tok = tokens[idx]
        if tok.info.strip().split(" ")[0].lower() == "mermaid":
            return ('<pre class="mermaid-src"><code>'
                    + escapeHtml(tok.content) + "</code></pre>")
        return default_fence(tokens, idx, options, env)

    default_fence = md.renderer.fence
    md.add_render_rule("image", image)
    md.add_render_rule("fence", fence)
    return md


def inline_image(src, base):
    """相対パスの画像は data URI にして埋め込む（読み込み元を持たない画面のため）。"""
    if not src or src.startswith(("http://", "https://", "data:")):
        return src
    from urllib.parse import unquote
    path = unquote(src.split("#")[0].split("?")[0])
    if path.startswith("file:///"):
        path = path[8:]
    if not os.path.isabs(path):
        path = os.path.join(base, path)
    try:
        if os.path.getsize(path) > MAX_INLINE_IMAGE:
            return src
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
    except OSError:
        return src
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return f"data:{mime};base64,{data}"


def initial_dir(initial):
    """ダイアログの開始位置。開いているフォルダー → 前回 → 起動したフォルダー の順。"""
    if initial and os.path.isdir(initial):
        return initial
    last = load_settings().get("last_folder")
    if last and os.path.isdir(last):
        return last
    return os.getcwd()


class Api:
    def __init__(self, start_path):
        self._window = None
        self.md = make_renderer()
        self.start_path = start_path
        self._mermaid = None

    # --- 画面から呼ばれる ---------------------------------------------------
    def get_initial(self):
        settings = load_settings()
        start = self.start_path
        result = {"folder": None, "file": None,
                  "last_folder": settings.get("last_folder"), "error": None}
        if start:
            if os.path.isdir(start):
                result["folder"] = start
            elif os.path.isfile(start):
                result["file"] = start
                result["folder"] = os.path.dirname(start)
            else:
                result["error"] = f"見つかりません: {start}"
        return result

    def pick_folder(self, initial=None):
        return dialogs.pick_folder(initial_dir(initial))

    def pick_file(self, initial=None):
        return dialogs.pick_file(initial_dir(initial))

    def list_files(self, folder):
        if not os.path.isdir(folder):
            return {"error": f"フォルダーが見つかりません: {folder}", "files": []}
        settings = load_settings()
        settings["last_folder"] = folder
        save_settings(settings)
        return {"error": None, "files": list_markdown(folder),
                "truncated": False}

    def open_file(self, path):
        try:
            text = read_text(path)
        except OSError as e:
            return {"error": f"開けません: {e}"}
        base = os.path.dirname(path)
        html = sanitize(self.md.render(text, {"base": base}),
                        lambda src: inline_image(src, base))
        try:
            self._window.set_title(f"{os.path.basename(path)} - Markdown ビューア")
        except Exception:
            pass
        return {"error": None, "html": html, "path": path,
                "name": os.path.basename(path)}

    def resolve_link(self, current, href):
        """文書内の相対リンクを開く先に解決する。Markdown 以外は開かない。"""
        from urllib.parse import unquote
        target = unquote(href.split("#")[0])
        if not target:
            return None
        path = os.path.normpath(os.path.join(os.path.dirname(current), target))
        if os.path.isfile(path) and is_markdown(path):
            return path
        return None

    # --- Mermaid の追加アイコン（Architecture Diagram の `logos:slack-icon` など）---------
    def list_icon_packs(self):
        folder = resource_path(os.path.join("vendor", "icons"))
        try:
            return sorted(n[:-8] for n in os.listdir(folder) if n.endswith(".json.gz"))
        except OSError:
            return []

    def get_icon_pack(self, name):
        """アイコン集（iconify の JSON）を返す。図でそのアイコンが要るときだけ画面が取りに来る。"""
        if not re.fullmatch(r"[a-z0-9-]+", name or ""):
            return None
        path = os.path.join(resource_path(os.path.join("vendor", "icons")), name + ".json.gz")
        try:
            with gzip.open(path, "rt", encoding="utf-8") as f:
                return f.read()
        except OSError:
            return None

    def get_mermaid(self):
        """Mermaid 本体。図があるときだけ画面が取りに来る（3.5MB あるため）。"""
        if self._mermaid is None:
            with open(resource_path("vendor/mermaid.min.js"), encoding="utf-8") as f:
                self._mermaid = f.read()
        return self._mermaid

    # --- 印刷・PDF ----------------------------------------------------------
    def get_print_prefs(self):
        return load_settings().get("print", {})

    def set_print_prefs(self, prefs):
        settings = load_settings()
        settings["print"] = prefs
        save_settings(settings)

    def print_printers(self):
        try:
            return printing.list_printers()
        except Exception:
            return {"printers": [], "default": ""}

    def print_check_ranges(self, text, total):
        try:
            return {"ok": True, "ranges": printing.parse_ranges(text, total or None)}
        except ValueError as e:
            return {"ok": False, "error": str(e)}

    def _print_call(self, fn):
        try:
            return {"ok": True, **(fn() or {})}
        except printing.PrintError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:                      # 画面へは文言で返す（原因が分かるように）
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def print_count(self, opts):
        return self._print_call(lambda: {"pages": printing.count_pages(self._window, opts)})

    def print_preview(self, opts, ranges):
        return self._print_call(lambda: printing.preview_pdf(
            self._window, opts, printing.parse_ranges(ranges)) and None)

    def print_save_pdf(self, opts, ranges, path):
        return self._print_call(lambda: printing.save_pdf(
            self._window, opts, printing.parse_ranges(ranges), path) and None)

    def print_send(self, opts, ranges):
        return self._print_call(lambda: printing.send_to_printer(
            self._window, opts, printing.parse_ranges(ranges)) and None)

    def pick_pdf_path(self, name, initial_dir_=None):
        return dialogs.pick_save(initial_dir(initial_dir_), name, "pdf")

    def open_external(self, url):
        if url.startswith(("http://", "https://", "mailto:")):
            webbrowser.open(url)


# --- エクスプローラー連携 ----------------------------------------------------
def message(text, title="Markdown ビューア"):
    ctypes.windll.user32.MessageBoxW(0, text, title, 0x40)


def register_association():
    import winreg
    if not getattr(sys, "frozen", False):
        message("exe 版から実行してください。")
        return
    exe = sys.executable
    base = r"Software\Classes"

    def put(key, value, name=""):
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)

    put(rf"{base}\{PROG_ID}", "Markdown 文書")
    put(rf"{base}\{PROG_ID}\DefaultIcon", f'"{exe}",0')
    put(rf"{base}\{PROG_ID}\shell\open", "Markdown ビューアで開く")
    put(rf"{base}\{PROG_ID}\shell\open\command", f'"{exe}" "%1"')
    for ext in (".md", ".markdown"):
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                              rf"{base}\{ext}\OpenWithProgids") as k:
            winreg.SetValueEx(k, PROG_ID, 0, winreg.REG_NONE, b"")
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
    message("登録しました。\n\nMarkdown ファイルを右クリック →「プログラムから開く」→"
            "「別のプログラムを選択」で「Markdown ビューアで開く」を選び、"
            "「常に使う」を押すと、ダブルクリックで開けます。")


def unregister_association():
    import winreg

    def delete_tree(root, sub):
        try:
            with winreg.OpenKey(root, sub, 0, winreg.KEY_ALL_ACCESS) as k:
                while True:
                    try:
                        child = winreg.EnumKey(k, 0)
                    except OSError:
                        break
                    delete_tree(root, rf"{sub}\{child}")
            winreg.DeleteKey(root, sub)
        except OSError:
            pass

    base = r"Software\Classes"
    delete_tree(winreg.HKEY_CURRENT_USER, rf"{base}\{PROG_ID}")
    for ext in (".md", ".markdown"):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                rf"{base}\{ext}\OpenWithProgids", 0,
                                winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, PROG_ID)
        except OSError:
            pass
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
    message("登録を解除しました。")


def main():
    args = sys.argv[1:]
    if args and args[0] == "--register":
        register_association()
        return
    if args and args[0] == "--unregister":
        unregister_association()
        return

    import webview
    start = os.path.abspath(args[0]) if args else None
    api = Api(start)
    with open(resource_path("ui.html"), encoding="utf-8") as f:
        html = f.read()
    with open(resource_path("print.js"), encoding="utf-8") as f:
        html = html.replace("/*PRINT_JS*/", f.read())
    api._window = webview.create_window(
        "Markdown ビューア", html=html, js_api=api,
        width=1200, height=800, min_size=(640, 400))
    webview.start()


if __name__ == "__main__":
    main()
