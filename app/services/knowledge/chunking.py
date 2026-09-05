"""Chunking strategies for knowledge document bodies.

Strategy/chunk_size/chunk_overlap come from the active embedding ModelConfig's
`params` (validated by app.schemas.embedding_config_params.EmbeddingConfigParams),
so they're tunable via the ModelConfig admin API without a redeploy.
"""

from app.exceptions.invalid_parameter_error import InvalidParameterError

MAX_CHUNKS_PER_DOCUMENT = 1000


def _fixed_size(content: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    if not content:
        return []
    step = chunk_size - chunk_overlap
    chunks = []
    start = 0
    length = len(content)
    while start < length:
        chunks.append(content[start : start + chunk_size])
        start += step
    return chunks


_STRATEGIES = {
    "fixed_size": _fixed_size,
}


def chunk_text(
    content: str, chunk_size: int, chunk_overlap: int, strategy: str
) -> list[str]:
    """Split `content` into chunks per `strategy`. Raises InvalidParameterError
    if `strategy` isn't registered or the result would exceed
    MAX_CHUNKS_PER_DOCUMENT (the PRD's ingestion-time cap)."""
    fn = _STRATEGIES.get(strategy)
    if fn is None:
        raise InvalidParameterError(
            f"Unknown chunking strategy '{strategy}'; must be one of "
            f"{sorted(_STRATEGIES)}"
        )
    chunks = fn(content, chunk_size, chunk_overlap)
    if len(chunks) > MAX_CHUNKS_PER_DOCUMENT:
        raise InvalidParameterError(
            f"Document would produce {len(chunks)} chunks, exceeding the "
            f"{MAX_CHUNKS_PER_DOCUMENT}-chunk limit; reduce content size or "
            f"increase chunk_size"
        )
    return chunks
