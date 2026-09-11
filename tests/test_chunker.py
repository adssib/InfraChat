"""F3 — chunk windows. Four bugs lived here, and every one produced *plausible* output:
chunks came out with ids and line ranges, so nothing looked wrong at ingest time. Each
test below is one of them.

  (a) the word-splitter could not split whitespace-free text — one 2001-character line
      of the digits of pi stayed whole and was silently truncated by the embedder;
  (b) the carried overlap was added *on top* of a full window, so `chunk.size: 800`
      actually meant 900 and the number in config meant nothing;
  (c) the overlap carried whole *paragraphs* small enough to fit inside `chunk.overlap`.
      Real documentation paragraphs are longer than that, so on the live corpus **59% of
      boundaries carried nothing** and the context bridge silently did not exist;
  (d) chunks that are wholly contained in a neighbour — a duplicate embedding that adds
      no information but can still be returned as a hit.

Chunking sets the ceiling on every later measurement, and nothing downstream errors when
it is wrong; the eval score just sits lower than it should.
"""

import itertools

from infrachat.ingest.chunker import chunk_text

SIZE, OVERLAP = 200, 50   # small so a window boundary is visible in one screen


def chunks_of(text: str, size: int = SIZE, overlap: int = OVERLAP):
    return chunk_text(text, source="docker", source_doc="build/x.md", size=size, overlap=overlap)


def _new_content(chunk_text_: str) -> str:
    """A chunk minus its carried overlap prefix.

    The carry is a synthetic first paragraph, so dropping everything up to the first
    blank line leaves what this chunk contributed that its predecessor did not.
    """
    return chunk_text_.split("\n\n", 1)[1] if "\n\n" in chunk_text_ else chunk_text_


def test_a_line_with_no_whitespace_in_it_is_still_split_to_size() -> None:
    # The real pathology: one 2001-character line holding the digits of pi, 7 spaces in
    # the whole file. A splitter that only breaks on whitespace returns it unchanged.
    pi_line = ("3.14159265358979323846264338327950288419716939937510" * 40)[:2001]

    chunks = chunks_of(pi_line, size=800, overlap=100)

    assert len(chunks) > 1, "a whitespace-free line came back as one chunk"
    assert max(len(c.text) for c in chunks) <= 800, "oversized chunk — the embedder truncates it"

    # Chunks now overlap, so plain concatenation no longer reconstructs the source.
    # Dropping each carried prefix must still recover it exactly: nothing lost, nothing
    # reordered, and the duplication is only the overlap we asked for.
    rebuilt = chunks[0].text + "".join(_new_content(c.text) for c in chunks[1:])
    assert rebuilt == pi_line, "the hard split lost or reordered text"


def test_the_overlap_is_actually_carried_and_still_fits_inside_size() -> None:
    # Paragraphs deliberately LONGER than `overlap`. Under the old whole-paragraph carry
    # this produced no overlap at all, which is exactly bug (c) — on the real corpus it
    # silenced the bridge at 59% of boundaries.
    doc = "\n\n".join(
        f"Paragraph {i:02d} of the cleaned document, long enough that it cannot fit "
        f"inside the overlap budget on its own." for i in range(14)
    )

    chunks = chunks_of(doc)
    assert len(chunks) > 2

    for prev, nxt in zip(chunks, chunks[1:]):
        assert prev.text[-20:] in nxt.text, (
            "no overlap was carried between two chunks — an answer spanning this "
            "boundary lands whole in neither, and the size check below is vacuous"
        )

    biggest = max(len(c.text) for c in chunks)
    assert biggest <= SIZE, (
        f"chunk grew to {biggest} with size={SIZE}: "
        "the carried overlap is being added on top of a full window"
    )


def test_no_chunk_is_wholly_contained_in_another() -> None:
    # A chunk that is a subset of its neighbour costs an embedding, occupies a retrieval
    # slot, and contributes nothing a reader could not get from the neighbour.
    doc = "\n\n".join(
        [f"Paragraph {i:02d} of the cleaned document." for i in range(13)] + ["Done."]
    )

    chunks = chunks_of(doc)
    assert len(chunks) > 1, "this doc should span several windows"

    for a, b in itertools.permutations(chunks, 2):
        assert a.text not in b.text, "one chunk is contained in another in full"

    assert _new_content(chunks[-1].text).strip(), (
        "the final chunk is nothing but carried overlap — it adds no new content"
    )
