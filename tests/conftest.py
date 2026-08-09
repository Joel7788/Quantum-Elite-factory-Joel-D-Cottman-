import importlib.util
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PIPELINE_PATH = REPO_ROOT / "quantum elite wholesaleing pipeline.py"
DATA_DIR = REPO_ROOT / "data"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from quantum_elite.models import (  # noqa: E402  (path bootstrap must run first)
    Address,
    Buyer,
    Comparable,
    Contact,
    DistressSignal,
    Lead,
    PropertyCondition,
    PropertyData,
)

AS_OF = date(2026, 8, 9)


def load_module_from_path(path, module_name):
    """Import a module from an arbitrary file path (the pipeline filename has spaces)."""
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def pipeline():
    return load_module_from_path(PIPELINE_PATH, "quantum_pipeline")


def make_address(street="118 Halyard Ln", city="Norfolk", state="VA", postal_code="23503"):
    return Address(street=street, city=city, state=state, postal_code=postal_code)


def make_comparable(
    sold_price="240000",
    square_feet=1600,
    sold_on=date(2026, 5, 1),
    distance_miles="0.4",
    street="120 Halyard Ln",
):
    return Comparable(
        address=make_address(street=street),
        sold_price=Decimal(sold_price),
        square_feet=square_feet,
        sold_on=sold_on,
        distance_miles=Decimal(distance_miles),
    )


def make_property(
    condition=PropertyCondition.MODERATE,
    square_feet=1600,
    year_built=2005,
    assessed_value="210000",
    comparables=None,
    address=None,
):
    if comparables is None:
        comparables = (
            make_comparable(street="120 Halyard Ln"),
            make_comparable(street="122 Halyard Ln", sold_price="248000"),
            make_comparable(street="124 Halyard Ln", sold_price="232000"),
        )
    return PropertyData(
        address=address or make_address(),
        square_feet=square_feet,
        bedrooms=3,
        bathrooms=Decimal("2"),
        year_built=year_built,
        lot_size_sqft=6000,
        condition=condition,
        assessed_value=Decimal(assessed_value),
        comparables=tuple(comparables),
    )


def make_lead(
    lead_id="QE-TEST",
    signals=(DistressSignal.PRE_FORECLOSURE, DistressSignal.VACANT),
    asking_price=None,
    days_on_market=90,
    contacts=(),
    property_data=None,
    address=None,
):
    return Lead(
        lead_id=lead_id,
        address=address or make_address(),
        owner_name="Marcus Webb",
        source="test",
        distress_signals=tuple(signals),
        asking_price=Decimal(asking_price) if asking_price is not None else None,
        days_on_market=days_on_market,
        contacts=tuple(contacts),
        property_data=property_data,
    )


def make_contact(name="Marcus Webb", phone="757-555-0101", email=None, confidence="0.9"):
    return Contact(name=name, phone=phone, email=email, confidence=Decimal(confidence))


def make_buyer(
    buyer_id="CB-TEST",
    name="Test Capital",
    markets=("norfolk|VA",),
    min_price="50000",
    max_price="400000",
    max_repair_tolerance="120000",
    proof_of_funds=True,
    close_days=14,
    deals_closed=20,
):
    return Buyer(
        buyer_id=buyer_id,
        name=name,
        markets=tuple(markets),
        min_price=Decimal(min_price),
        max_price=Decimal(max_price),
        max_repair_tolerance=Decimal(max_repair_tolerance),
        proof_of_funds=proof_of_funds,
        close_days=close_days,
        deals_closed=deals_closed,
    )
