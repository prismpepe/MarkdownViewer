"""画面（ui.html）に、部品（印刷・検索）が埋め込まれて組み上がること。"""
import mdviewer


def test_組み立てた画面に差し込み位置が残らない():
    html = mdviewer.build_html()
    for left in ("/*PRINT_JS*/", "/*FIND_JS*/", "__APP_VERSION__"):
        assert left not in html


def test_検索と印刷の部品が入る():
    html = mdviewer.build_html()
    assert "const MdSearch" in html
    assert "const MdPrint" in html
    assert mdviewer.APP_VERSION in html
