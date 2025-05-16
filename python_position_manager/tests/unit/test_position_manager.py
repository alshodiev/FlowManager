# python_position_manager/tests/unit/test_position_manager.py
import pytest
import time
import uuid
from unittest.mock import call, ANY

from app.position_manager import PositionManager # Assuming app is on PYTHONPATH or accessible
from app.brokers.broker_interface import TradeConfirmationMessage, OrderDetails

# Helper to generate unique client order IDs for tests
def gen_cl_ord_id():
    return str(uuid.uuid4())

def test_pm_initialization(position_manager_with_mock_broker):
    pm = position_manager_with_mock_broker
    assert pm is not None
    assert pm.broker is not None
    # Check if the broker's callback registration was "called" by PM's init
    # This depends on how the mock_broker_interface is set up in conftest.
    # If using create_autospec, pm.broker.__init__ would have been called with pm._trade_confirmation_callback
    # For this test, pm.broker.start should be called when pm.run() is invoked.
    # For now, just checking pm.broker is set is enough.

def test_update_target_position_queues_update(position_manager_with_mock_broker):
    pm = position_manager_with_mock_broker
    pm.update_target_position("AAPL", 100)
    assert pm.target_updates_q.qsize() == 1
    symbol, amount = pm.target_updates_q.get_nowait()
    assert symbol == "AAPL"
    assert amount == 100

def test_process_target_updates(position_manager_with_mock_broker):
    pm = position_manager_with_mock_broker
    pm.target_updates_q.put(("MSFT", 50))
    symbols_affected = pm._process_target_updates() # Call protected method for testing
    assert "MSFT" in symbols_affected
    assert pm.target_positions["MSFT"] == 50

def test_trade_confirmation_callback_queues_confirmation(position_manager_with_mock_broker):
    pm = position_manager_with_mock_broker
    confirmation = TradeConfirmationMessage(
        order_id=1, client_order_id="cl_id_1", symbol="GOOG",
        filled_quantity=10, side_is_buy=True, price=100.0, status="FILLED"
    )
    pm._trade_confirmation_callback(confirmation) # Call directly for test
    assert pm.trade_confirmations_q.qsize() == 1
    conf_from_q = pm.trade_confirmations_q.get_nowait()
    assert conf_from_q == confirmation

def test_process_trade_confirmations_updates_state(position_manager_with_mock_broker):
    pm = position_manager_with_mock_broker
    cl_ord_id = gen_cl_ord_id()
    broker_ord_id = 123 # Matches mock_broker submit_order default

    # Simulate an order being live
    pm.live_orders[cl_ord_id] = OrderDetails(
        client_order_id=cl_ord_id, broker_order_id=broker_ord_id, symbol="NVDA",
        quantity=20, side_is_buy=True, type="MARKET", price=None,
        status="WORKING", filled_quantity=0
    )
    pm.live_orders_by_symbol["NVDA"].append(cl_ord_id)

    confirmation = TradeConfirmationMessage(
        order_id=broker_ord_id, client_order_id=cl_ord_id, symbol="NVDA",
        filled_quantity=15, side_is_buy=True, price=200.0, status="PARTIALLY_FILLED"
    )
    pm.trade_confirmations_q.put(confirmation)
    
    symbols_affected = pm._process_trade_confirmations()
    assert "NVDA" in symbols_affected
    assert pm.positions["NVDA"] == 15
    assert pm.total_traded_by_symbol["NVDA"] == 15
    assert pm.live_orders[cl_ord_id].filled_quantity == 15
    assert pm.live_orders[cl_ord_id].status == "PARTIALLY_FILLED"

    confirmation_filled = TradeConfirmationMessage(
        order_id=broker_ord_id, client_order_id=cl_ord_id, symbol="NVDA",
        filled_quantity=5, side_is_buy=True, price=201.0, status="FILLED"
    )
    pm.trade_confirmations_q.put(confirmation_filled)
    symbols_affected = pm._process_trade_confirmations()
    assert pm.positions["NVDA"] == 20
    assert cl_ord_id not in pm.live_orders # Should be removed on FILLED
    assert not pm.live_orders_by_symbol.get("NVDA") # List should be empty and key removed


def test_reconcile_buy_order_generation(position_manager_with_mock_broker):
    pm = position_manager_with_mock_broker
    mock_broker = pm.broker # This is the mock_broker_interface from conftest

    pm.target_positions["AAPL"] = 100
    pm.positions["AAPL"] = 0 # Start flat

    pm._reconcile_positions(symbols_to_check={"AAPL"})

    # Assert broker.submit_order was called correctly
    # The client_order_id is generated internally, so use ANY
    mock_broker.submit_order.assert_called_once_with(
        ANY, # client_order_id
        "AAPL", # symbol
        100,    # quantity
        True,   # side_is_buy
        "MARKET", # order_type (default)
        None      # price (default)
    )
    # Check that the order was added to live_orders
    assert len(pm.live_orders) == 1
    live_order_details = list(pm.live_orders.values())[0]
    assert live_order_details.symbol == "AAPL"
    assert live_order_details.quantity == 100
    assert live_order_details.side_is_buy is True

def test_reconcile_sell_order_generation(position_manager_with_mock_broker):
    pm = position_manager_with_mock_broker
    mock_broker = pm.broker

    pm.target_positions["TSLA"] = -50 # Target short
    pm.positions["TSLA"] = 0

    pm._reconcile_positions(symbols_to_check={"TSLA"})

    mock_broker.submit_order.assert_called_once_with(
        ANY, "TSLA", 50, False, "MARKET", None
    )
    assert len(pm.live_orders) == 1
    live_order_details = list(pm.live_orders.values())[0]
    assert live_order_details.symbol == "TSLA"
    assert live_order_details.quantity == 50
    assert live_order_details.side_is_buy is False

def test_reconcile_cancel_opposing_buy_before_sell(position_manager_with_mock_broker):
    pm = position_manager_with_mock_broker
    mock_broker = pm.broker
    
    # Setup: Live BUY order exists
    existing_buy_cl_id = gen_cl_ord_id()
    existing_buy_broker_id = 456
    pm.live_orders[existing_buy_cl_id] = OrderDetails(
        client_order_id=existing_buy_cl_id, broker_order_id=existing_buy_broker_id,
        symbol="AMD", quantity=20, side_is_buy=True, type="MARKET", price=None,
        status="WORKING", filled_quantity=5
    )
    pm.live_orders_by_symbol["AMD"].append(existing_buy_cl_id)
    pm.positions["AMD"] = 5 # From the partial fill of the buy

    # Target: Go short (requires selling more than current position + open buy)
    pm.target_positions["AMD"] = -30 

    # Mock broker.submit_order to return a new ID for the sell order
    mock_broker.submit_order.return_value = 789 

    pm._reconcile_positions(symbols_to_check={"AMD"})

    # Assert that cancel_order was called for the existing BUY order
    mock_broker.cancel_order.assert_called_once_with(existing_buy_cl_id)
    
    # Assert a new SELL order was placed.
    # Working position before new sell = 5 (actual) + (20-5) (working_buy) = 20
    # Delta = -30 (target) - 20 (working) = -50. Need to sell 50.
    mock_broker.submit_order.assert_called_once_with(
        ANY, "AMD", 50, False, "MARKET", None
    )
    # Check live orders: existing buy should be PENDING_CANCEL, new sell should be PENDING_NEW/ACK
    assert pm.live_orders[existing_buy_cl_id].status == "PENDING_CANCEL"
    
    new_sell_order_cl_id = mock_broker.submit_order.call_args[0][0] # Get the client_order_id from the call
    assert pm.live_orders[new_sell_order_cl_id].symbol == "AMD"
    assert pm.live_orders[new_sell_order_cl_id].quantity == 50


def test_reconcile_no_action_if_on_target(position_manager_with_mock_broker):
    pm = position_manager_with_mock_broker
    mock_broker = pm.broker

    pm.target_positions["MSFT"] = 100
    pm.positions["MSFT"] = 100 # Already on target

    pm._reconcile_positions(symbols_to_check={"MSFT"})

    mock_broker.submit_order.assert_not_called()
    mock_broker.cancel_order.assert_not_called()
    assert not pm.live_orders # No new orders created

# More tests to consider:
# - Reconciliation with existing SELL orders when target is BUY
# - FAK order handling (if you add specific FAK logic to PM beyond broker handling)
# - Multiple symbols reconciliation
# - What happens if broker.submit_order returns None (rejection)
# - What happens if broker.cancel_order returns False
# - Test _calculate_working_position directly with various scenarios