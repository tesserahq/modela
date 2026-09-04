import pytest

from app.exceptions.invalid_parameter_error import InvalidParameterError
from app.services.knowledge.frontmatter import split_frontmatter


def test_valid_frontmatter_splits_into_metadata_and_body():
    raw = (
        "---\n"
        "title: GA4 Events\n"
        "tags: [ecommerce, events]\n"
        "status: current\n"
        "---\n"
        "# Body\n\nSome prose.\n"
    )
    metadata, body = split_frontmatter(raw)
    assert metadata == {
        "title": "GA4 Events",
        "tags": ["ecommerce", "events"],
        "status": "current",
    }
    assert body == "# Body\n\nSome prose.\n"


def test_no_frontmatter_returns_empty_metadata_and_full_body():
    raw = "# Just a document\n\nNo frontmatter here.\n"
    metadata, body = split_frontmatter(raw)
    assert metadata == {}
    assert body == raw


def test_body_containing_horizontal_rule_is_not_corrupted():
    raw = "---\ntitle: Doc\n---\n# Heading\n\nSection one\n\n---\n\nSection two\n"
    metadata, body = split_frontmatter(raw)
    assert metadata == {"title": "Doc"}
    assert body == "# Heading\n\nSection one\n\n---\n\nSection two\n"


def test_malformed_yaml_is_rejected():
    raw = "---\ntitle: [unclosed\n---\nbody\n"
    with pytest.raises(InvalidParameterError):
        split_frontmatter(raw)


def test_non_mapping_frontmatter_is_rejected():
    raw = "---\n- just\n- a\n- list\n---\nbody\n"
    with pytest.raises(InvalidParameterError):
        split_frontmatter(raw)


def test_yaml_tag_payload_is_rejected_not_executed():
    """Regression test for the RCE risk in the PRD 0019 security review:
    yaml.load()'s default loader would construct arbitrary Python objects
    from tags like !!python/object/apply. safe_load must reject this."""
    raw = (
        "---\n"
        "evil: !!python/object/apply:os.system ['echo pwned']\n"
        "---\n"
        "body\n"
    )
    with pytest.raises(InvalidParameterError):
        split_frontmatter(raw)
