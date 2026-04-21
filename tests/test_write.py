import pytest

from src.write import kebab_slug


@pytest.mark.parametrize("raw,expected", [
    ("Anthropic AI", "anthropic-ai"),
    ("How Prompt Caching Actually Works", "how-prompt-caching-actually-works"),
    ("  Leading/trailing  ", "leading-trailing"),
    ("With !@# punctuation?", "with-punctuation"),
    ("Mix CASE and numbers 2026", "mix-case-and-numbers-2026"),
])
def test_kebab_slug(raw, expected):
    assert kebab_slug(raw) == expected
