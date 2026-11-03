"""画像の書き方（相対パス・絶対パス・file:///）が、どれでもプレビューに画像として出ること。"""
import base64
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mdviewer
from sanitize import sanitize

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def render(text, base):
    md = mdviewer.make_renderer()
    return sanitize(md.render(text, {"base": base}), lambda src: mdviewer.inline_image(src, base))


@pytest.fixture
def folder(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "doc").mkdir()
    (tmp_path / "images" / "a.png").write_bytes(PNG)
    (tmp_path / "images" / "pic one.png").write_bytes(PNG)
    return tmp_path


def test_絶対パスの書き方は_どれでも画像が出る(folder):
    """file:///… が文字のまま出ていた。ドライブを省いた /… も、文書と同じドライブとみなす。"""
    absolute = str(folder / "images" / "a.png").replace("\\", "/")
    spelled = [
        "file:///" + absolute,
        "file:///" + str(folder / "images" / "pic one.png").replace("\\", "/").replace(" ", "%20"),
        absolute,
        "../images/a.png",
    ]
    if os.name == "nt":
        spelled.append(absolute[2:])
    for src in spelled:
        html = render("![図](%s)\n" % src, str(folder / "doc"))
        assert "data:image/png;base64," in html, (src, html)
        assert "![図]" not in html, src


def test_危険なスキームは_従来どおり拒む(folder):
    html = render("[x](javascript:alert(1))\n\n![y](data:text/html;base64,AAAA)\n", str(folder))
    assert "<a " not in html and "<img" not in html
    assert "javascript:alert(1)" in html                   # 文字としては残る（リンクにならない）


def test_読めないfile画像は_中身を出さず_代替文字だけ(folder):
    html = render("![図](file:///C:/none/a.png)\n", str(folder))
    assert "src=" not in html and 'alt="図"' in html
