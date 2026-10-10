"""Donor SOS starts immediately for uncovered hospital transfer quantities."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.database import (
    ABO,
    ComponentCode,
    RequestUrgency,
    RhD,
    SOSEvent,
    TransferOffer,
    TransferOrder,
    TransferRequest,
    TransferState,
)
from app.services import transfer_sos
from app.services.sos_dispatch import DispatchResult, build_message


async def prepare_transfer_tables(db_session):
    """The shared SQLite fixture omits transfer tables that reference PostGIS Facility."""
    async with db_session.bind.begin() as connection:
        for table in (TransferRequest.__table__, TransferOffer.__table__, TransferOrder.__table__):
            await connection.run_sync(table.create)


async def run_reconciliation(db_session, monkeypatch, *, qty, offer_specs):
    await prepare_transfer_tables(db_session)
    request_id = "request-test"
    db_session.add(TransferRequest(
        id=request_id,
        requester_facility_id="facility-requester",
        component_code=ComponentCode.WB,
        abo=ABO.O,
        rh=RhD.POS,
        qty=qty,
        urgency=RequestUrgency.EMERGENCY,
        needed_by=datetime.now(timezone.utc) + timedelta(hours=1),
        created_at=datetime.now(timezone.utc),
        state=TransferState.PENDING,
    ))
    for index, (status, offered_qty) in enumerate(offer_specs):
        db_session.add(TransferOffer(
            id=f"offer-{index}",
            request_id=request_id,
            source_facility_id=f"facility-source-{index}",
            priority_rank=index,
            available_qty=offered_qty,
            offered_qty=offered_qty,
            accepted_qty=0,
            status=status,
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        ))
    await db_session.commit()

    dispatched = []

    async def facility_cell(_db, _facility_id):
        return "8928308280fffff"

    async def dispatch_initial_rings(_db, event):
        dispatched.append((event.ring, event.target_count))
        return DispatchResult(ring=event.ring, matched=1, notified=1), 0

    monkeypatch.setattr(transfer_sos, "facility_cell", facility_cell)
    monkeypatch.setattr(transfer_sos, "dispatch_initial_rings", dispatch_initial_rings)
    event = await transfer_sos.start_sos_if_transfer_exhausted(db_session, request_id)
    return event, dispatched


@pytest.mark.parametrize(
    ("offers", "qty", "shortfall"),
    [
        ([('declined', 4), ('expired', 2)], 6, 6),
        ([('pending', 3), ('declined', 2)], 8, 5),
        ([('no_source', 0)], 4, 4),
    ],
)
async def test_uncovered_transfer_quantity_opens_ring_zero_sos(
    db_session, monkeypatch, offers, qty, shortfall
):
    event, dispatched = await run_reconciliation(
        db_session, monkeypatch, qty=qty, offer_specs=offers
    )

    assert event is not None
    assert event.status == "open"
    assert event.ring == 0
    assert event.target_count == shortfall
    assert dispatched == [(0, shortfall)]


async def test_pending_hospital_capacity_covering_request_does_not_open_sos(
    db_session, monkeypatch
):
    event, dispatched = await run_reconciliation(
        db_session,
        monkeypatch,
        qty=5,
        offer_specs=[("pending", 5)],
    )

    assert event is None
    assert dispatched == []
    assert (await db_session.execute(select(SOSEvent))).scalars().all() == []


def test_mock_sos_message_is_unmistakably_not_a_real_emergency():
    event = SOSEvent(urgency="mock_test", target_count=1, component_code="WB")

    title, body = build_message(event, None)

    assert title == "KIỂM THỬ — SOS mô phỏng vòng 0"
    assert "không phải yêu cầu hiến máu thật" in body
