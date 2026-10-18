"""Central settings for the deterministic similarity pipeline."""

from math import isclose
from typing import Dict, Optional, Tuple


# These weights set how much the name, type, and structure scores contribute
# to a field's final similarity score. Their sum must be exactly one apart
# from a tiny floating-point rounding tolerance.
WEIGHTS = {"name": 0.40, "type": 0.40, "structure": 0.20}

# Scores below this boundary should later be surfaced for human review.
FLAG_THRESHOLD = 80

# Candidate rules below this confidence level should later be reviewed,
# even when their similarity score is high.
SAFE_CONFIDENCE = "high"

# These scores describe known source-to-SQL type pairs. Unlisted pairs use
# DEFAULT_TYPE_SCORE instead of assuming they are a perfect match.
TYPE_COMPATIBILITY = {
    ("integer", "INTEGER"): 100,
    ("integer", "NUMERIC"): 90,
    ("float", "NUMERIC"): 100,
    ("float", "INTEGER"): 40,
    ("string", "TEXT"): 100,
    ("boolean", "BOOLEAN"): 100,
    ("date-string", "TIMESTAMP"): 90,
}

# This is the cautious score for type pairs that have no explicit rule above.
DEFAULT_TYPE_SCORE = 50

# Mixed source types receive a separate score because one SQL type may not
# preserve every value exactly.
MIXED_TYPE_SCORE = 60

# These scores describe whether a source field keeps its place, is flattened,
# or is moved into a separate child table.
STRUCTURE_SCORES = {"unchanged": 100, "flattened": 90, "child_table": 90}

# A source field with no mapped SQL field represents data that would be lost.
UNMAPPED_FIELD_SCORE = 0

# These common plural forms do not follow the simple English suffix rules.
IRREGULAR_SINGULARS = {
    "statuses": "status",
    "addresses": "address",
    "people": "person",
    "children": "child",
    "data": "data",
}

# When enabled, a trailing ID token is removed to compare entity and key names.
STRIP_ID_TOKEN = True

# Words shorter than this are left alone because short endings are ambiguous.
MIN_SINGULARIZE_LENGTH = 4


def validateConfig(
    weights: Optional[Dict[str, float]] = None,
    flag_threshold: Optional[int] = None,
    type_compatibility: Optional[Dict[Tuple[str, str], int]] = None,
    default_type_score: Optional[int] = None,
    mixed_type_score: Optional[int] = None,
) -> None:
    """Validate settings, optionally checking temporary values instead of globals.

    Optional arguments let callers test or validate proposed settings without
    changing the module constants that other code imports.
    """
    weights_to_check = WEIGHTS if weights is None else weights
    threshold_to_check = (
        FLAG_THRESHOLD if flag_threshold is None else flag_threshold
    )
    compatibility_to_check = (
        TYPE_COMPATIBILITY
        if type_compatibility is None
        else type_compatibility
    )
    default_score_to_check = (
        DEFAULT_TYPE_SCORE
        if default_type_score is None
        else default_type_score
    )
    mixed_score_to_check = (
        MIXED_TYPE_SCORE if mixed_type_score is None else mixed_type_score
    )

    if not isclose(sum(weights_to_check.values()), 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError("WEIGHTS must sum to 1.0.")

    if not 0 <= threshold_to_check <= 100:
        raise ValueError("FLAG_THRESHOLD must be between 0 and 100 inclusive.")

    for type_pair, score in compatibility_to_check.items():
        if not 0 <= score <= 100:
            raise ValueError(
                "TYPE_COMPATIBILITY scores must be between 0 and 100 inclusive; "
                f"{type_pair!r} has score {score!r}."
            )

    for setting_name, score in (
        ("DEFAULT_TYPE_SCORE", default_score_to_check),
        ("MIXED_TYPE_SCORE", mixed_score_to_check),
    ):
        if not 0 <= score <= 100:
            raise ValueError(
                f"{setting_name} must be between 0 and 100 inclusive; "
                f"received {score!r}."
            )


# Fail during import if a shipped setting is accidentally edited to an invalid value.
validateConfig()