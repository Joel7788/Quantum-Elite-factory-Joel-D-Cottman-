"""Domain models for the Quantum Elite wholesaling pipeline.

Money is always ``Decimal``; ratios are ``Decimal`` in the 0-1 range.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from typing import Optional

MONEY_ZERO = Decimal("0")


class LeadStage(enum.Enum):
    """Stages a lead moves through, in pipeline order."""

    INGESTED = "ingested"
    ENRICHED = "enriched"
    SKIP_TRACED = "skip_traced"
    SCORED = "scored"
    UNDERWRITTEN = "underwritten"
    OFFER_SENT = "offer_sent"
    UNDER_CONTRACT = "under_contract"
    ASSIGNED = "assigned"
    REJECTED = "rejected"


class PropertyCondition(enum.Enum):
    """Physical condition bands used by the repair estimator."""

    TURNKEY = "turnkey"
    COSMETIC = "cosmetic"
    MODERATE = "moderate"
    HEAVY = "heavy"
    TEARDOWN = "teardown"


class DistressSignal(enum.Enum):
    """Public-record and behavioural signals that indicate seller motivation."""

    PRE_FORECLOSURE = "pre_foreclosure"
    TAX_DELINQUENT = "tax_delinquent"
    PROBATE = "probate"
    DIVORCE = "divorce"
    CODE_VIOLATION = "code_violation"
    VACANT = "vacant"
    ABSENTEE_OWNER = "absentee_owner"
    TIRED_LANDLORD = "tired_landlord"
    EXPIRED_LISTING = "expired_listing"


@dataclass(frozen=True)
class Address:
    street: str
    city: str
    state: str
    postal_code: str

    def __post_init__(self):
        if not self.street.strip():
            raise ValueError("street is required")
        if len(self.state) != 2:
            raise ValueError(f"state must be a 2-letter code, got {self.state!r}")

    @property
    def one_line(self) -> str:
        return f"{self.street}, {self.city}, {self.state} {self.postal_code}"

    @property
    def market_key(self) -> str:
        """Key used to match buyer buy-boxes and comparable-sales markets."""
        return f"{self.city.strip().lower()}|{self.state.strip().upper()}"


@dataclass(frozen=True)
class Comparable:
    """A comparable sale used to derive ARV."""

    address: Address
    sold_price: Decimal
    square_feet: int
    sold_on: date
    distance_miles: Decimal

    def __post_init__(self):
        if self.square_feet <= 0:
            raise ValueError("square_feet must be positive")
        if self.sold_price <= MONEY_ZERO:
            raise ValueError("sold_price must be positive")

    @property
    def price_per_square_foot(self) -> Decimal:
        return self.sold_price / Decimal(self.square_feet)


@dataclass(frozen=True)
class PropertyData:
    """Objective property facts, sourced from a property-data provider."""

    address: Address
    square_feet: int
    bedrooms: int
    bathrooms: Decimal
    year_built: int
    lot_size_sqft: int
    condition: PropertyCondition
    assessed_value: Decimal
    mortgage_balance: Decimal = MONEY_ZERO
    comparables: tuple[Comparable, ...] = ()

    def __post_init__(self):
        if self.square_feet <= 0:
            raise ValueError("square_feet must be positive")
        if self.mortgage_balance < MONEY_ZERO:
            raise ValueError("mortgage_balance cannot be negative")


@dataclass(frozen=True)
class Contact:
    """A phone/email pair resolved by skip tracing, with a confidence score."""

    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    confidence: Decimal = Decimal("0.5")

    def __post_init__(self):
        if not (MONEY_ZERO <= self.confidence <= Decimal("1")):
            raise ValueError("confidence must be within 0-1")

    @property
    def is_reachable(self) -> bool:
        return bool(self.phone or self.email)


@dataclass(frozen=True)
class Underwriting:
    """Output of the underwriting engine for a single property."""

    arv: Decimal
    repair_estimate: Decimal
    max_allowable_offer: Decimal
    assignment_fee: Decimal
    confidence: Decimal

    @property
    def spread(self) -> Decimal:
        """Gross margin left in the deal after repairs, at MAO."""
        return self.arv - self.repair_estimate - self.max_allowable_offer

    @property
    def is_viable(self) -> bool:
        return self.max_allowable_offer > MONEY_ZERO and self.spread > MONEY_ZERO


@dataclass(frozen=True)
class Buyer:
    """A cash buyer and their buy-box, used for predictive disposition matching."""

    buyer_id: str
    name: str
    markets: tuple[str, ...]
    min_price: Decimal
    max_price: Decimal
    max_repair_tolerance: Decimal
    proof_of_funds: bool
    close_days: int
    deals_closed: int = 0

    def __post_init__(self):
        if self.min_price > self.max_price:
            raise ValueError("min_price cannot exceed max_price")

    def covers_market(self, market_key: str) -> bool:
        return market_key in self.markets


@dataclass
class Lead:
    """A motivated-seller lead as it moves through the pipeline."""

    lead_id: str
    address: Address
    owner_name: str
    source: str
    distress_signals: tuple[DistressSignal, ...] = ()
    asking_price: Optional[Decimal] = None
    days_on_market: Optional[int] = None
    stage: LeadStage = LeadStage.INGESTED
    property_data: Optional[PropertyData] = None
    contacts: tuple[Contact, ...] = ()
    motivation_score: Optional[Decimal] = None
    underwriting: Optional[Underwriting] = None
    rejection_reason: Optional[str] = None

    @property
    def best_contact(self) -> Optional[Contact]:
        reachable = [c for c in self.contacts if c.is_reachable]
        if not reachable:
            return None
        return max(reachable, key=lambda c: c.confidence)

    def advance(self, stage: LeadStage) -> None:
        """Move the lead forward; rejection is terminal."""
        if self.stage is LeadStage.REJECTED:
            raise ValueError(f"lead {self.lead_id} is rejected and cannot advance")
        self.stage = stage

    def reject(self, reason: str) -> None:
        self.stage = LeadStage.REJECTED
        self.rejection_reason = reason


@dataclass(frozen=True)
class Offer:
    """A generated offer to the seller."""

    lead_id: str
    amount: Decimal
    earnest_money: Decimal
    inspection_days: int
    close_days: int
    expires_on: date


@dataclass(frozen=True)
class Assignment:
    """The disposition side: a matched buyer and the fee earned."""

    buyer: Buyer
    fee: Decimal
    match_score: Decimal


@dataclass
class DealPacket:
    """Everything produced for one lead: underwriting, offer, buyer, documents."""

    lead: Lead
    offer: Optional[Offer] = None
    assignment: Optional[Assignment] = None
    documents: dict[str, str] = field(default_factory=dict)

    @property
    def is_closed_loop(self) -> bool:
        """True when acquisition and disposition sides are both resolved."""
        return self.offer is not None and self.assignment is not None

    def with_documents(self, documents: dict[str, str]) -> "DealPacket":
        return replace(self, documents={**self.documents, **documents})
