"""Pluggable data-provider adapters.

The pipeline depends only on the ``Protocol`` classes here, so a live Zillow /
public-records / skip-trace integration can replace the bundled file-backed
implementations without touching pipeline code.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Iterator, Optional, Protocol, runtime_checkable

from .models import (
    Address,
    Buyer,
    Comparable,
    Contact,
    DistressSignal,
    Lead,
    PropertyCondition,
    PropertyData,
)


@runtime_checkable
class LeadSource(Protocol):
    """Yields raw motivated-seller leads (Zillow, public records, direct mail)."""

    name: str

    def fetch(self) -> Iterator[Lead]: ...


@runtime_checkable
class PropertyDataProvider(Protocol):
    """Resolves objective property facts and comparable sales for an address."""

    def lookup(self, address: Address) -> Optional[PropertyData]: ...


@runtime_checkable
class SkipTraceProvider(Protocol):
    """Resolves owner contact details."""

    def trace(self, owner_name: str, address: Address) -> tuple[Contact, ...]: ...


@runtime_checkable
class BuyerRepository(Protocol):
    """Source of cash buyers for disposition matching."""

    def all_buyers(self) -> tuple[Buyer, ...]: ...


class ProviderError(RuntimeError):
    """Raised when a provider payload cannot be interpreted."""


# Malformed payloads surface as any of these; the pipeline and the HTTP runtime
# only handle ProviderError, so every one of them is translated below.
_PARSE_ERRORS = (KeyError, TypeError, ValueError, InvalidOperation)


def _reason(exc: Exception) -> str:
    if isinstance(exc, KeyError):
        return f"missing field: {exc.args[0]}"
    return f"invalid field ({type(exc).__name__}: {exc})"


def _money(value) -> Decimal:
    return Decimal(str(value))


def _address(payload: dict) -> Address:
    try:
        return Address(
            street=payload["street"],
            city=payload["city"],
            state=payload["state"],
            postal_code=str(payload["postal_code"]),
        )
    except _PARSE_ERRORS as exc:
        raise ProviderError(f"address payload {_reason(exc)}") from exc


def _enum_by_value(enum_cls, raw: str):
    try:
        return enum_cls(raw)
    except ValueError as exc:
        raise ProviderError(f"unknown {enum_cls.__name__}: {raw!r}") from exc


def load_json(path: Path) -> list[dict]:
    """Read a JSON list-of-objects payload from disk."""
    try:
        payload = json.loads(Path(path).read_text())
    except FileNotFoundError as exc:
        raise ProviderError(f"provider data file not found: {path}") from exc
    except OSError as exc:
        raise ProviderError(f"provider data file is unreadable: {path} ({exc})") from exc
    except json.JSONDecodeError as exc:
        raise ProviderError(f"provider data file is not valid JSON: {path}") from exc
    if not isinstance(payload, list):
        raise ProviderError(f"expected a JSON list in {path}, got {type(payload).__name__}")
    for index, record in enumerate(payload):
        if not isinstance(record, dict):
            raise ProviderError(
                f"expected a JSON object at {path}[{index}], got {type(record).__name__}"
            )
    return payload


def parse_lead(payload: dict) -> Lead:
    try:
        signals = tuple(
            _enum_by_value(DistressSignal, raw) for raw in payload.get("distress_signals", ())
        )
        asking = payload.get("asking_price")
        return Lead(
            lead_id=payload["lead_id"],
            address=_address(payload["address"]),
            owner_name=payload["owner_name"],
            source=payload.get("source", "unknown"),
            distress_signals=signals,
            asking_price=_money(asking) if asking is not None else None,
            days_on_market=payload.get("days_on_market"),
        )
    except _PARSE_ERRORS as exc:
        raise ProviderError(f"lead payload {_reason(exc)}") from exc


def parse_property_data(payload: dict) -> PropertyData:
    try:
        comparables = tuple(
            Comparable(
                address=_address(comp["address"]),
                sold_price=_money(comp["sold_price"]),
                square_feet=int(comp["square_feet"]),
                sold_on=date.fromisoformat(comp["sold_on"]),
                distance_miles=_money(comp["distance_miles"]),
            )
            for comp in payload.get("comparables", ())
        )
        return PropertyData(
            address=_address(payload["address"]),
            square_feet=int(payload["square_feet"]),
            bedrooms=int(payload["bedrooms"]),
            bathrooms=_money(payload["bathrooms"]),
            year_built=int(payload["year_built"]),
            lot_size_sqft=int(payload["lot_size_sqft"]),
            condition=_enum_by_value(PropertyCondition, payload["condition"]),
            assessed_value=_money(payload["assessed_value"]),
            mortgage_balance=_money(payload.get("mortgage_balance", 0)),
            comparables=comparables,
        )
    except _PARSE_ERRORS as exc:
        raise ProviderError(f"property payload {_reason(exc)}") from exc


def parse_buyer(payload: dict) -> Buyer:
    try:
        return Buyer(
            buyer_id=payload["buyer_id"],
            name=payload["name"],
            markets=tuple(payload["markets"]),
            min_price=_money(payload["min_price"]),
            max_price=_money(payload["max_price"]),
            max_repair_tolerance=_money(payload["max_repair_tolerance"]),
            proof_of_funds=bool(payload["proof_of_funds"]),
            close_days=int(payload["close_days"]),
            deals_closed=int(payload.get("deals_closed", 0)),
        )
    except _PARSE_ERRORS as exc:
        raise ProviderError(f"buyer payload {_reason(exc)}") from exc


def parse_contact(payload: dict) -> Contact:
    try:
        return Contact(
            name=payload["name"],
            phone=payload.get("phone"),
            email=payload.get("email"),
            confidence=_money(payload.get("confidence", "0.5")),
        )
    except _PARSE_ERRORS as exc:
        raise ProviderError(f"contact payload {_reason(exc)}") from exc


class JsonLeadSource:
    """A ``LeadSource`` backed by a JSON file of lead payloads."""

    def __init__(self, path: Path, name: str = "json_file"):
        self.path = Path(path)
        self.name = name

    def fetch(self) -> Iterator[Lead]:
        for payload in load_json(self.path):
            yield parse_lead(payload)


class InMemoryLeadSource:
    """A ``LeadSource`` over an existing iterable, useful for replay and tests."""

    def __init__(self, leads: Iterable[Lead], name: str = "in_memory"):
        self._leads = tuple(leads)
        self.name = name

    def fetch(self) -> Iterator[Lead]:
        yield from self._leads


class JsonPropertyDataProvider:
    """Property data keyed by ``Address.one_line``, loaded from a JSON file."""

    def __init__(self, path: Path):
        self._by_address: dict[str, PropertyData] = {}
        for payload in load_json(Path(path)):
            data = parse_property_data(payload)
            key = data.address.one_line
            if key in self._by_address:
                raise ProviderError(f"duplicate property record for {key} in {path}")
            self._by_address[key] = data

    def lookup(self, address: Address) -> Optional[PropertyData]:
        return self._by_address.get(address.one_line)


class JsonSkipTraceProvider:
    """Contacts keyed by owner name, loaded from a JSON file."""

    def __init__(self, path: Path):
        self._by_owner: dict[str, list[Contact]] = {}
        for payload in load_json(Path(path)):
            try:
                owner = payload["owner_name"]
                contacts = payload["contacts"]
            except _PARSE_ERRORS as exc:
                raise ProviderError(f"skip trace payload {_reason(exc)}") from exc
            self._by_owner.setdefault(self._key(owner), []).extend(
                parse_contact(contact) for contact in contacts
            )

    @staticmethod
    def _key(owner_name: str) -> str:
        return owner_name.strip().lower()

    def trace(self, owner_name: str, address: Address) -> tuple[Contact, ...]:
        return tuple(self._by_owner.get(self._key(owner_name), ()))


class JsonBuyerRepository:
    """Cash buyers loaded from a JSON file."""

    def __init__(self, path: Path):
        self._buyers = tuple(parse_buyer(payload) for payload in load_json(Path(path)))

    def all_buyers(self) -> tuple[Buyer, ...]:
        return self._buyers
