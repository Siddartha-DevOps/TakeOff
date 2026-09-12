"""Pattern/count search aggregation helpers (Togal-style 'find all like this')."""

from .aggregate import (
    count_and_group,
    filter_by_similarity,
    similarity_to_max_distance,
)

__all__ = ["count_and_group", "filter_by_similarity", "similarity_to_max_distance"]
