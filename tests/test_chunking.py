from ai_pipeline.utils.chunking import chunk_text


def test_chunking_preserves_content_boundaries():
    text = "\n\n".join(["paragraph " + str(index) + " x" * 40 for index in range(8)])
    chunks = chunk_text(text, max_chars=180, overlap=20)
    assert len(chunks) > 1
    assert all(len(chunk) <= 180 + 25 for chunk in chunks)
    assert "paragraph 0" in chunks[0]
    assert "paragraph 7" in chunks[-1]
