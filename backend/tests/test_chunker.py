from app.services.chunker import TARGET_WORDS, chunk
from app.services.parser import Block, ParsedDoc, ParsedPage


def doc(blocks_per_page):
    return ParsedDoc("pdf", [ParsedPage(i + 1, bl) for i, bl in enumerate(blocks_per_page)], len(blocks_per_page))


def test_heading_splits_and_tracks_section():
    d = doc([[Block("1 Purpose", True), Block("word " * 30), Block("2 Procedure", True), Block("step " * 30)]])
    cs = chunk(d)
    assert [c.section for c in cs] == ["1 Purpose", "2 Procedure"]
    assert all(c.page == 1 for c in cs)


def test_never_crosses_pages():
    d = doc([[Block("alpha " * 50)], [Block("beta " * 50)]])
    cs = chunk(d)
    assert [c.page for c in cs] == [1, 2]
    assert "beta" not in cs[0].text


def test_long_block_is_split_with_overlap():
    cs = chunk(doc([[Block(" ".join(f"w{i}" for i in range(1000)))]]))
    assert len(cs) >= 3
    assert all(len(c.text.split()) <= TARGET_WORDS + 1 for c in cs)
    assert set(cs[0].text.split()[-10:]) & set(cs[1].text.split()[:60])  # overlap


def test_tiny_fragments_dropped():
    assert chunk(doc([[Block("ok")]])) == []
