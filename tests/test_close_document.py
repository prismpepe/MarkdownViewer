"""フォルダーを変えて文書を閉じたとき、記憶している前回のファイルも忘れること。"""
import json
import os

import pytest

import mdviewer


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "a.md").write_text("# a", encoding="utf-8")
    a = mdviewer.Api(None)
    a._tmp = tmp_path
    a._folder = folder
    return a


def settings():
    with open(mdviewer.settings_path(), encoding="utf-8") as f:
        return json.load(f)


def test_文書を開くと前回のファイルが記憶され_閉じると忘れる(api):
    api.list_files(str(api._folder))
    api.open_file(str(api._folder / "a.md"))
    assert settings()["last_file"].endswith("a.md")
    assert api._doc_dir
    api.close_document()
    assert "last_file" not in settings()
    assert api._doc_dir is None
    assert settings()["last_folder"] == str(api._folder)       # フォルダーは覚えたまま


def test_閉じたあとに起動しても_前回のファイルは開かない(api):
    api.list_files(str(api._folder))
    api.open_file(str(api._folder / "a.md"))
    api.close_document()
    init = mdviewer.Api(None).get_initial()
    assert init["folder"] == str(api._folder) and init["file"] is None


def test_別のフォルダーへ移ると_前のフォルダーのファイルは復元されない(api):
    other = api._tmp / "other"
    other.mkdir()
    api.list_files(str(api._folder))
    api.open_file(str(api._folder / "a.md"))
    api.close_document()                       # 画面は、フォルダーを移る前に文書を閉じる
    api.list_files(str(other))
    init = mdviewer.Api(None).get_initial()
    assert init["folder"] == str(other) and init["file"] is None


def test_ファイル名を指定して起動した回は_設定に触れない(api):
    start = api._folder / "a.md"
    a = mdviewer.Api(str(start))
    before = None
    if os.path.exists(mdviewer.settings_path()):
        before = open(mdviewer.settings_path(), encoding="utf-8").read()
    a.close_document()
    after = open(mdviewer.settings_path(), encoding="utf-8").read() if os.path.exists(mdviewer.settings_path()) else None
    assert before == after


def test_開いていない状態で閉じても落ちない(api):
    api.close_document()
    api.close_document()
