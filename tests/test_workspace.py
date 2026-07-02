from app.workspace import Workspace, parse_script_md, segment_id


# ---- parse_script_md ----

def test_parse_basic():
    md = """# 我的播客

## host | 开场 | warm and curious
欢迎收听本期节目。

## cohost | 展开 | excited
今天聊聊 AI。
"""
    title, segs = parse_script_md(md)
    assert title == "我的播客"
    assert len(segs) == 2
    assert segs[0].speaker == "host"
    assert segs[0].title == "开场"
    assert segs[0].style == "warm and curious"
    assert "欢迎收听" in segs[0].text
    assert segs[1].speaker == "cohost"


def test_parse_missing_title_and_style():
    md = """## host
只有 speaker。
"""
    _, segs = parse_script_md(md)
    assert len(segs) == 1
    assert segs[0].title == ""
    assert segs[0].style is None


def test_parse_empty():
    assert parse_script_md("") == ("", [])
    assert parse_script_md("# 只有标题") == ("只有标题", [])


def test_segment_id_stable():
    a = segment_id("host", "相同文本")
    b = segment_id("host", "相同文本")
    c = segment_id("cohost", "相同文本")
    assert a == b
    assert a != c


def test_parse_id_changes_when_text_changes():
    _, segs1 = parse_script_md("## host\n内容A")
    _, segs2 = parse_script_md("## host\n内容B")
    assert segs1[0].id != segs2[0].id


# ---- 工具 ----

def test_write_read_list():
    ws = Workspace()
    assert "source.txt" not in ws.files
    assert "已写入" in ws.write_file("source.txt", "hello")
    assert ws.read_file("source.txt") == "hello"
    assert "source.txt" in ws.list_files()


def test_read_missing_file():
    ws = Workspace()
    assert "错误" in ws.read_file("nope.txt")


def test_edit_unique_replace():
    ws = Workspace()
    ws.write_file("script.md", "aaa bbb aaa")
    assert "1 处替换" in ws.edit_file("script.md", "bbb", "ccc")
    assert ws.files["script.md"] == "aaa ccc aaa"


def test_edit_not_found():
    ws = Workspace()
    ws.write_file("script.md", "aaa")
    assert "未找到" in ws.edit_file("script.md", "zzz", "yyy")


def test_edit_not_unique():
    ws = Workspace()
    ws.write_file("script.md", "aaa aaa")
    assert "不唯一" in ws.edit_file("script.md", "aaa", "b")


def test_grep_hit():
    ws = Workspace()
    ws.write_file("source.txt", "机器学习是AI的子领域。\n深度学习属于机器学习。")
    out = ws.grep("机器学习")
    assert "source.txt:1" in out
    assert "source.txt:2" in out


def test_grep_no_match():
    ws = Workspace()
    ws.write_file("source.txt", "hello")
    assert "无匹配" in ws.grep("zzz")


def test_grep_bad_regex():
    ws = Workspace()
    assert "非法正则" in ws.grep("(")
