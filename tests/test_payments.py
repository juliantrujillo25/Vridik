"""
Vridik — tests/test_payments.py (Sprint S7)
Prueba api/payments_endpoint.py: POST /orders/{id}/pay (dueño o admin) y
POST /webhooks/wompi (firma HMAC real vía core.wompi.verify_signature,
nunca se mockea) — end-to-end (FastAPI TestClient) sobre un fake mínimo,
mismo estilo que tests/test_orders.py. create_transaction() nunca se
alcanza de verdad en estos tests (sin WOMPI_PRIVATE_KEY, el endpoint
atrapa el RuntimeError y sigue devolviendo el payment 'pending').
"""

from __future__ import annotations

import hashlib
import os
import uuid

os.environ.setdefault("JWT_SECRET", "vridik-test-secret-nunca-usar-en-produccion")
os.environ.setdefault("WOMPI_EVENTS_SECRET", "test-events-secret-nunca-produccion")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.payments_endpoint import router as payments_router
from core.auth import create_jwt


class _DummyTx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePaymentsDB:
    """Fake de `users` (con role, S2) + `orders` (S4) + `payments` (S7)."""

    def __init__(self):
        self.users: dict[str, dict] = {}
        self.orders: dict[str, dict] = {}
        self.payments: dict[str, dict] = {}

    def seed_user(self, *, email: str, role: str = "customer") -> dict:
        user_id = str(uuid.uuid4())
        self.users[user_id] = {"id": user_id, "email": email, "role": role}
        return self.users[user_id]

    def seed_order(self, *, user_id: str, total_cents: int = 10000, status: str = "pending") -> dict:
        order_id = str(uuid.uuid4())
        self.orders[order_id] = {
            "id": order_id, "user_id": user_id, "status": status, "total_cents": total_cents,
            "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00",
        }
        return self.orders[order_id]

    def transaction(self):
        return _DummyTx()

    async def execute(self, query: str, *args):
        return "OK"

    async def fetchrow(self, query: str, *args):
        if "SELECT id, email, role FROM users WHERE id" in query:
            (user_id,) = args
            u = self.users.get(user_id)
            return dict(u) if u else None
        if "FROM orders WHERE id" in query:
            (order_id,) = args
            o = self.orders.get(order_id)
            return dict(o) if o else None
        if "INSERT INTO payments" in query and "RETURNING" in query:
            order_id, reference, amount_cents = args
            payment_id = str(uuid.uuid4())
            pago = {
                "id": payment_id, "order_id": order_id, "reference": reference, "transaction_id": None,
                "amount_cents": amount_cents, "status": "pending",
                "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00",
            }
            self.payments[reference] = pago
            return dict(pago)
        if "FROM payments WHERE reference" in query:
            (reference,) = args
            p = self.payments.get(reference)
            return dict(p) if p else None
        if query.strip().startswith("UPDATE payments SET status"):
            reference, status, transaction_id = args
            p = self.payments.get(reference)
            if p is None:
                return None
            p["status"] = status
            if transaction_id is not None:
                p["transaction_id"] = transaction_id
            return dict(p)
        if query.strip().startswith("UPDATE orders SET status"):
            order_id, nuevo_status = args
            o = self.orders.get(order_id)
            if o is None:
                return None
            o["status"] = nuevo_status
            return dict(o)
        return None

    async def fetch(self, query: str, *args):
        return []


@pytest.fixture
def payments_db():
    return _FakePaymentsDB()


@pytest.fixture
def payments_client(payments_db):
    app = FastAPI()
    app.include_router(payments_router)
    app.state.db_connection = payments_db
    return TestClient(app)


def _token_de(usuario: dict) -> str:
    return create_jwt(sub=usuario["id"], email=usuario["email"])


def _firmar_evento(*, reference: str, status: str, transaction_id: str, events_secret: str, timestamp: int = 1234567890):
    propiedades = ["transaction.id", "transaction.status", "transaction.reference"]
    transaccion = {"id": transaction_id, "status": status, "reference": reference, "amount_in_cents": 10000}
    valores = [str(transaccion[prop.split(".")[1]]) for prop in propiedades]
    cadena = "".join(valores) + str(timestamp) + events_secret
    checksum = hashlib.sha256(cadena.encode("utf-8")).hexdigest()
    return {
        "event": "transaction.updated",
        "data": {"transaction": transaccion},
        "signature": {"properties": propiedades, "checksum": checksum},
        "timestamp": timestamp,
    }


def test_owner_can_create_payment(payments_db, payments_client):
    buyer = payments_db.seed_user(email="buyer1@vridik.local")
    orden = payments_db.seed_order(user_id=buyer["id"], total_cents=15000)
    token = _token_de(buyer)

    r = payments_client.post(f"/orders/{orden['id']}/pay", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["amount_cents"] == 15000
    assert body["status"] == "pending"
    assert "reference" in body


def test_non_owner_cannot_create_payment(payments_db, payments_client):
    buyer = payments_db.seed_user(email="buyer2@vridik.local")
    otro = payments_db.seed_user(email="otro@vridik.local")
    orden = payments_db.seed_order(user_id=buyer["id"], total_cents=15000)
    token = _token_de(otro)

    r = payments_client.post(f"/orders/{orden['id']}/pay", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_admin_can_create_payment_for_others_order(payments_db, payments_client):
    buyer = payments_db.seed_user(email="buyer3@vridik.local")
    admin = payments_db.seed_user(email="admin_pay@vridik.local", role="admin")
    orden = payments_db.seed_order(user_id=buyer["id"], total_cents=20000)
    token = _token_de(admin)

    r = payments_client.post(f"/orders/{orden['id']}/pay", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 201, r.text


def test_webhook_approved_marks_order_paid(payments_db, payments_client):
    buyer = payments_db.seed_user(email="buyer4@vridik.local")
    orden = payments_db.seed_order(user_id=buyer["id"], total_cents=15000)
    token = _token_de(buyer)
    reference = payments_client.post(
        f"/orders/{orden['id']}/pay", headers={"Authorization": f"Bearer {token}"},
    ).json()["reference"]

    events_secret = os.environ["WOMPI_EVENTS_SECRET"]
    evento = _firmar_evento(
        reference=reference, status="APPROVED", transaction_id="txn-123", events_secret=events_secret,
    )

    r = payments_client.post("/webhooks/wompi", json=evento)
    assert r.status_code == 200, r.text
    assert payments_db.orders[orden["id"]]["status"] == "paid"
    assert payments_db.payments[reference]["status"] == "approved"
    assert payments_db.payments[reference]["transaction_id"] == "txn-123"


def test_webhook_declined_does_not_mark_order_paid(payments_db, payments_client):
    buyer = payments_db.seed_user(email="buyer5@vridik.local")
    orden = payments_db.seed_order(user_id=buyer["id"], total_cents=15000)
    token = _token_de(buyer)
    reference = payments_client.post(
        f"/orders/{orden['id']}/pay", headers={"Authorization": f"Bearer {token}"},
    ).json()["reference"]

    events_secret = os.environ["WOMPI_EVENTS_SECRET"]
    evento = _firmar_evento(
        reference=reference, status="DECLINED", transaction_id="txn-456", events_secret=events_secret,
    )

    r = payments_client.post("/webhooks/wompi", json=evento)
    assert r.status_code == 200, r.text
    assert payments_db.orders[orden["id"]]["status"] == "pending"
    assert payments_db.payments[reference]["status"] == "declined"


def test_webhook_invalid_signature_rejected(payments_db, payments_client):
    buyer = payments_db.seed_user(email="buyer6@vridik.local")
    orden = payments_db.seed_order(user_id=buyer["id"], total_cents=15000)
    token = _token_de(buyer)
    reference = payments_client.post(
        f"/orders/{orden['id']}/pay", headers={"Authorization": f"Bearer {token}"},
    ).json()["reference"]

    evento_malo = _firmar_evento(
        reference=reference, status="APPROVED", transaction_id="txn-x", events_secret="secreto-incorrecto",
    )
    r = payments_client.post("/webhooks/wompi", json=evento_malo)
    assert r.status_code == 401
    assert payments_db.orders[orden["id"]]["status"] == "pending"
