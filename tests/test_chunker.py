from app.ingestion.chunker import Chunker, Chunk


def test_chunker_splits_text():
    chunker = Chunker(chunk_size=50, chunk_overlap=10)
    text = "word " * 200  # ~200 tokens
    chunks = chunker.chunk_text(text, section_title="Section 1", page_number=1)
    assert len(chunks) > 1
    assert all(isinstance(c, Chunk) for c in chunks)


def test_chunk_has_metadata():
    chunker = Chunker(chunk_size=50, chunk_overlap=10)
    text = "word " * 200
    chunks = chunker.chunk_text(text, section_title="Wiring Rules", page_number=5)
    assert chunks[0].section_title == "Wiring Rules"
    assert chunks[0].page_number == 5
    assert chunks[0].chunk_index == 0
    assert chunks[1].chunk_index == 1


def test_chunk_respects_size_limit():
    chunker = Chunker(chunk_size=50, chunk_overlap=10)
    text = "word " * 200
    chunks = chunker.chunk_text(text, section_title="Test", page_number=1)
    for chunk in chunks:
        assert chunker._token_count(chunk.content) <= 55  # small tolerance


def test_chunk_overlap():
    chunker = Chunker(chunk_size=50, chunk_overlap=10)
    text = "word " * 200
    chunks = chunker.chunk_text(text, section_title="Test", page_number=1)
    # Verify overlap: end of chunk N should overlap with start of chunk N+1
    if len(chunks) >= 2:
        words_0 = chunks[0].content.split()
        words_1 = chunks[1].content.split()
        overlap_words = words_0[-10:]
        assert overlap_words == words_1[:10]


def test_short_text_single_chunk():
    chunker = Chunker(chunk_size=500, chunk_overlap=50)
    text = "Short text that fits in one chunk."
    chunks = chunker.chunk_text(text, section_title="Intro", page_number=1)
    assert len(chunks) == 1
    assert chunks[0].content == "Short text that fits in one chunk."


def test_chunk_from_reducto_sections():
    chunker = Chunker(chunk_size=100, chunk_overlap=20)
    sections = [
        {"title": "Overview", "content": "word " * 50, "page": 1},
        {"title": "Wiring", "content": "wire " * 150, "page": 3},
    ]
    all_chunks = chunker.chunk_sections(sections)
    assert all_chunks[0].section_title == "Overview"
    wiring_chunks = [c for c in all_chunks if c.section_title == "Wiring"]
    assert len(wiring_chunks) > 1
    assert wiring_chunks[0].page_number == 3


def test_chunk_has_no_token_count():
    from app.ingestion.chunker import Chunk
    assert "token_count" not in Chunk.__dataclass_fields__
