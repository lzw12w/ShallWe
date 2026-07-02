from app import extractor


def test_extract_txt():
    assert extractor.extract_from_bytes(b"hello world", "note.txt") == "hello world"


def test_extract_md():
    text = extractor.extract_from_bytes(b"# Title\nbody text", "a.md")
    assert "Title" in text
    assert "body text" in text


def test_extract_unknown_extension_falls_back_to_text():
    assert extractor.extract_from_bytes(b"plain content", "noext") == "plain content"


def test_truncate():
    assert extractor.truncate("abc", 10) == "abc"
    assert extractor.truncate("abcde", 3) == "abc"
