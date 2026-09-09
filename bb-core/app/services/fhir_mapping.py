"""
BB-Core — FHIR R5 resource mapping contracts

Maps internal data model to HL7 FHIR R5 resources for interoperability.
This is the "data contract" layer — writing the adapter is Phase 2, but
having the contract defined now proves the system is FHIR-ready.

FHIR R5 resources used:
- BiologicallyDerivedProduct (blood unit)
- SupplyRequest (transfer request)
- SupplyDelivery (shipment)
- InventoryItem / InventoryReport (inventory tracking)
- Location (facility with geospatial data)
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# ── FHIR R5 BiologicallyDerivedProduct ──────────────────────────

class FHIRBiologicallyDerivedProduct(BaseModel):
    """
    FHIR R5 BiologicallyDerivedProduct mapping for a blood unit.

    See: https://hl7.org/fhir/biologicallyderivedproduct.html
    """
    resource_type: str = "BiologicallyDerivedProduct"
    id: str                                        # internal UUID
    identifier: list[dict]                          # [{system: "ISBT128", value: isbt_din}]
    product_category: dict                          # {coding: [{system: "http://hl7.org/fhir/biologicallyderived-productcategory", code: "blood"}]}
    product_code: dict                              # {coding: [{system: "ISBT128", code: component_code}]}
    biological_source_event: Optional[str] = None   # donation event reference
    collection_date: Optional[str] = None            # collected_at as ISO 8601
    expiration_date: Optional[str] = None            # expires_at as ISO 8601
    storage_temp_requirements: Optional[dict] = None # {low: X, high: Y, unit: "Cel", mode: "storage|transport"}
    processing_facility: Optional[dict] = None      # {reference: "Location/fac-xxx"}
    property_: list[dict] = Field(default_factory=list, alias="property")

    @classmethod
    def from_blood_unit(cls, unit: "BloodUnit", facility_name: str = "") -> "FHIRBiologicallyDerivedProduct":
        """Convert internal BloodUnit to FHIR R5 resource."""
        from app.config import settings

        # Component code → ISBT 128 coding
        component_map = {
            "RBC":  {"system": "http://hl7.org/fhir/biologicallyderived-productcode", "code": "E7001", "display": "Red Blood Cells"},
            "PLT":  {"system": "http://hl7.org/fhir/biologicallyderived-productcode", "code": "E7004", "display": "Platelets"},
            "FFP":  {"system": "http://hl7.org/fhir/biologicallyderived-productcode", "code": "E7002", "display": "Fresh Frozen Plasma"},
            "CRYO": {"system": "http://hl7.org/fhir/biologicallyderived-productcode", "code": "E7003", "display": "Cryoprecipitate"},
        }

        abo_map = {"O": "O", "A": "A", "B": "B", "AB": "AB"}
        rh_map = {"+": "positive", "-": "negative"}

        # Temperature requirements with TWO modes (Art 20 TT 26/2013/TT-BYT)
        comp_code = unit.component_code.value if hasattr(unit.component_code, 'value') else str(unit.component_code)
        thresholds = settings.temp_thresholds.get(comp_code, {})

        properties = [
            # ABO group
            {"type": {"coding": [{"system": "http://hl7.org/fhir/biologicallyderived-property", "code": "ABORhD"}]},
             "valueCodeableConcept": {"coding": [
                 {"system": "http://terminology.hl7.org/CodeSystem/v3-ABORhD",
                  "code": f"{abo_map.get(unit.abo.value, unit.abo.value)}{rh_map.get(unit.rh.value, unit.rh.value)}"}
             ]}},
            # Volume
            {"type": {"coding": [{"system": "http://hl7.org/fhir/biologicallyderived-property", "code": "volume"}]},
             "valueQuantity": {"value": unit.volume_ml, "unit": "mL"}},
        ]

        if unit.irradiated:
            properties.append(
                {"type": {"coding": [{"system": "http://hl7.org/fhir/biologicallyderived-property", "code": "irradiated"}]},
                 "valueBoolean": True}
            )
        if unit.leukoreduced:
            properties.append(
                {"type": {"coding": [{"system": "http://hl7.org/fhir/biologicallyderived-property", "code": "leukoreduced"}]},
                 "valueBoolean": True}
            )

        return cls(
            id=unit.id,
            identifier=[{"system": "ISBT128", "value": unit.isbt_din}],
            product_category={"coding": [
                {"system": "http://hl7.org/fhir/biologicallyderived-productcategory", "code": "blood"}
            ]},
            product_code={"coding": [component_map.get(comp_code, {"code": comp_code})]},
            collection_date=unit.collected_at.isoformat() if unit.collected_at else None,
            expiration_date=unit.expires_at.isoformat() if unit.expires_at else None,
            storage_temp_requirements=thresholds,
            processing_facility={"reference": f"Location/{unit.held_by_facility_id}",
                                  "display": facility_name} if facility_name else None,
            property_=properties,
        )


# ── FHIR R5 SupplyRequest (transfer request) ────────────────────

class FHIRSupplyRequest(BaseModel):
    """FHIR R5 SupplyRequest mapping for a transfer request."""
    resource_type: str = "SupplyRequest"
    id: str
    status: str = "active"  # draft | active | suspended | cancelled | completed
    category: dict = {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/supply-kind",
                                    "code": "blood", "display": "Blood Supply"}]}
    item: dict  # {concept: {coding: [{code: component_code}]}}
    quantity: int = 1
    parameter: list[dict] = Field(default_factory=list)  # ABO, RhD requirements
    occurrence_date_time: Optional[str] = None  # needed_by
    requester: Optional[dict] = None  # {reference: "Location/fac-xxx"}


# ── FHIR R5 SupplyDelivery (shipment) ───────────────────────────

class FHIRSupplyDelivery(BaseModel):
    """FHIR R5 SupplyDelivery mapping for a shipment."""
    resource_type: str = "SupplyDelivery"
    id: str
    status: str = "in-progress"  # in-progress | completed | abandoned
    supplied_item: dict = Field(default_factory=dict)
    destination: Optional[dict] = None  # {reference: "Location/fac-xxx"}
    occurrence_date_time: Optional[str] = None


# ── FHIR R5 Location (facility) ─────────────────────────────────

class FHIRLocation(BaseModel):
    """FHIR R5 Location mapping for a blood bank facility."""
    resource_type: str = "Location"
    id: str
    status: str = "active"
    name: str
    type: list[dict] = Field(default_factory=list)
    position: Optional[dict] = None  # {longitude: x, latitude: y}
    physical_type: dict = {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/location-physical-type",
                                        "code": "bu", "display": "Building"}]}


# ── FHIR R5 contract summary ─────────────────────────────────────

FHIR_RESOURCE_CONTRACTS = {
    "BiologicallyDerivedProduct": {
        "description": "Mỗi đơn vị chế phẩm máu → 1 FHIR BiologicallyDerivedProduct resource",
        "key_fields": ["identifier (ISBT128 DIN)", "productCode (component)", "property (ABO, RhD, volume)", "expirationDate"],
        "mode": "storage + transport temperature thresholds per Art 20 TT 26/2013/TT-BYT",
    },
    "SupplyRequest": {
        "description": "Mỗi yêu cầu điều chuyển → 1 FHIR SupplyRequest",
        "key_fields": ["category=blood", "item (component)", "parameter (ABO, RhD)", "occurrenceDateTime (needed_by)"],
        "mode": "active → completed | cancelled",
    },
    "SupplyDelivery": {
        "description": "Mỗi lô vận chuyển → 1 FHIR SupplyDelivery",
        "key_fields": ["suppliedItem", "destination", "occurrenceDateTime"],
        "mode": "in-progress → completed",
    },
    "InventoryReport": {
        "description": "Báo cáo tồn kho theo giờ còn lại → FHIR InventoryReport",
        "key_fields": ["reportType", "reportPeriod", "inventoryListing"],
        "mode": "snapshot per facility per time window",
    },
}