"""OKF-style frontmatter/body split for knowledge base documents.

Uploaded documents may carry a YAML frontmatter block (metadata: tags, status,
stale_after, sources, generated, verified, ...) followed by a markdown body,
per the Open Knowledge Format convention
(https://github.com/GoogleCloudPlatform/open-knowledge-format). Only the body
is ever chunked/embedded — frontmatter is stored as structured metadata.
"""

import re

import yaml

from app.exceptions.invalid_parameter_error import InvalidParameterError

# Anchored at the very start of the document, DOTALL so the YAML block (which
# may itself contain newlines) is captured non-greedily up to the closing
# `---`. A naive str.split("---") would also match a markdown horizontal rule
# appearing later in the body.
_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)


def split_frontmatter(raw: str) -> tuple[dict, str]:
    """Split OKF-style '---\\nYAML\\n---\\nbody' content into (metadata, body).

    Returns ({}, raw) unchanged when there is no frontmatter block. Raises
    InvalidParameterError if a frontmatter block is present but fails to
    parse as YAML, or does not parse to a mapping.

    Uses yaml.safe_load() exclusively — never yaml.load()'s default loader,
    which allows arbitrary Python object construction via YAML tags (e.g.
    `!!python/object/apply:os.system`) and would let a document upload
    achieve remote code execution.
    """
    match = _FRONTMATTER_RE.match(raw)
    if not match:
        return {}, raw

    frontmatter_text, body = match.groups()
    try:
        metadata = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError as exc:
        raise InvalidParameterError(f"Invalid YAML frontmatter: {exc}")

    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise InvalidParameterError(
            "YAML frontmatter must parse to a mapping (key: value pairs)"
        )

    return metadata, body
