"""Recommendation layer (Phase 6).

Everything here is deterministic. A recommendation's reasons are catalogue
facts read back from the checks that were already performed, and an
alternative is a real product that failed fewer constraints than the rest. No
provider is called, so nothing in this package can invent a product, a price,
or a reason.
"""
