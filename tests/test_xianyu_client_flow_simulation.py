"""Offline simulation of the documented Xianyu partner order flow.

This is a protocol feasibility test, not a live Xianyu integration. It makes no
network requests, does not use account credentials, and cannot create real orders.
"""
from dataclasses import dataclass
import unittest


class ClientRuntimeUnavailable(RuntimeError):
    """Raised when a Xianyu-only client API is requested from a normal website."""


@dataclass
class SimulatedOrder:
    order_id: str
    status: int = 1


class SimulatedXianyuPartner:
    """Model only the documented create/query/payment state transitions."""

    def __init__(self):
        self.order = None

    def create_virtual_order(self, *, item_id, biz_code, amount_fen, virtual_code):
        if not item_id or not biz_code or amount_fen <= 0 or not virtual_code:
            raise ValueError("official virtual-order fields are required")
        self.order = SimulatedOrder("mock-order-001")
        return self.order.order_id

    def trade_pay(self, *, order_id, runtime):
        if runtime != "xianyu-miniapp":
            raise ClientRuntimeUnavailable("Goosefish.tradePay requires the Xianyu client runtime")
        if self.order is None or order_id != self.order.order_id:
            raise ValueError("unknown order")
        self.order.status = 2

    def query_order_status(self, order_id):
        if self.order is None or order_id != self.order.order_id:
            raise ValueError("unknown order")
        return self.order.status


class XianyuClientFlowSimulationTests(unittest.TestCase):
    def setUp(self):
        self.partner = SimulatedXianyuPartner()

    def test_virtual_order_requires_partner_assigned_business_fields(self):
        with self.assertRaisesRegex(ValueError, "required"):
            self.partner.create_virtual_order(
                item_id=123, biz_code="", amount_fen=200, virtual_code="INTERVIEW-3"
            )

    def test_order_creation_is_not_payment_confirmation(self):
        order_id = self.partner.create_virtual_order(
            item_id=123, biz_code="partner-assigned-code", amount_fen=200,
            virtual_code="INTERVIEW-3",
        )
        self.assertEqual(order_id, "mock-order-001")
        self.assertEqual(self.partner.query_order_status(order_id), 1)

    def test_web_link_cannot_invoke_xianyu_client_payment_api(self):
        order_id = self.partner.create_virtual_order(
            item_id=123, biz_code="partner-assigned-code", amount_fen=200,
            virtual_code="INTERVIEW-3",
        )
        with self.assertRaisesRegex(ClientRuntimeUnavailable, "Xianyu client runtime"):
            self.partner.trade_pay(order_id=order_id, runtime="ordinary-web")
        self.assertEqual(self.partner.query_order_status(order_id), 1)

    def test_only_server_verified_paid_status_is_a_payment_signal(self):
        order_id = self.partner.create_virtual_order(
            item_id=123, biz_code="partner-assigned-code", amount_fen=200,
            virtual_code="INTERVIEW-3",
        )
        self.partner.trade_pay(order_id=order_id, runtime="xianyu-miniapp")
        self.assertEqual(self.partner.query_order_status(order_id), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
