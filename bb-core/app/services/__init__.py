"""BB-Core services package."""
from .compatibility import is_compatible, compute_compatibility_score
from .matching import find_matching_units, TransferRequest, BloodUnitCandidate, MatchResult
from .fhir_mapping import FHIR_RESOURCE_CONTRACTS