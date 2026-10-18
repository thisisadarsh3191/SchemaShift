"""Pure helpers for turning different field-name styles into comparable tokens."""

import re
from typing import List

from .config import IRREGULAR_SINGULARS, MIN_SINGULARIZE_LENGTH, STRIP_ID_TOKEN


def tokenize(name: str) -> List[str]:
    """Split a name into lowercase words, handling paths and common name styles.

    Separators are treated alike so, for example, ``address.city`` and
    ``address_city`` produce the same tokens.
    """
    # Array markers are separators too; removing them first avoids a stray
    # "[]" being interpreted as a word.
    normalized_name = name.replace("[]", " ")

    # The first pattern splits lower-to-upper transitions such as "phoneNumbers".
    normalized_name = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", normalized_name)

    # The second pattern splits the final capital of an acronym from a title
    # word, so "HTTPServer" becomes "HTTP Server".
    normalized_name = re.sub(r"([A-Z])([A-Z][a-z])", r"\1 \2", normalized_name)

    # Replace punctuation and underscores with spaces while retaining Unicode
    # letters and digits as valid word characters.
    normalized_name = re.sub(r"[\W_]", " ", normalized_name, flags=re.UNICODE)

    return normalized_name.lower().split()


def singularizeToken(token: str) -> str:
    """Convert one lowercase word token to a common singular form.

    This logic is intentionally copied from ``schema.py``'s ``singular()``
    rather than imported; keep the two implementations in sync when rules change.
    """
    normalized_token = token.lower()

    if normalized_token in IRREGULAR_SINGULARS:
        return IRREGULAR_SINGULARS[normalized_token]

    if len(normalized_token) < MIN_SINGULARIZE_LENGTH:
        return normalized_token

    if normalized_token.endswith("ies"):
        return normalized_token[:-3] + "y"

    if normalized_token.endswith(("sses", "xes", "ches", "shes")):
        return normalized_token[:-2]

    if normalized_token.endswith("s") and not normalized_token.endswith(
        ("ss", "us", "is")
    ):
        return normalized_token[:-1]

    return normalized_token


def normalizeToTokens(name: str) -> List[str]:
    """Tokenize a name, singularize its words, and optionally remove a final ID.

    A name consisting only of ``_id`` remains ``["id"]`` because removing the
    sole token would erase the entire identifier name.
    """
    tokens = [singularizeToken(token) for token in tokenize(name)]

    if STRIP_ID_TOKEN and len(tokens) > 1 and tokens[-1] == "id":
        tokens.pop()

    return tokens


def normalizeName(name: str) -> str:
    """Return a normalized name as lowercase tokens joined with underscores.

    Later pipeline stages can compare this single string form, while this
    function remains unaware of schemas and decides nothing about which names
    should be compared.
    """
    return "_".join(normalizeToTokens(name))