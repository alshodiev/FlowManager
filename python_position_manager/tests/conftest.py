# python_position_manager/tests/conftest.py
import pytest
from unittest.mock import MagicMock, create_autospec
from queue import Queue
import logging

# Make sure app components are importable
# This might require adjusting PYTHONPATH or using `python -m pytest`
# from app.brokers.broker_interface import BrokerInterface, TradeConfirmationMessage, OrderDetails
# from app.position_manager import PositionManager

# For simplicity, if running tests from `python_position_manager` dir, these imports might work:
from app.brokers.broker_interface import BrokerInterface, TradeConfirmationMessage, OrderDetails
from app.position_manager import PositionManager

# Suppress noisy logs during tests, unless specifically needed
logging.basicConfig(level=logging.WARNING)
logging.getLogger("PositionManager").setLevel(logging.WARNING)
logging.getLogger("SimulatedBroker").setLevel(logging.WARNING)


@pytest.fixture
def mock_broker_interface():
    """
    Provides a MagicMock instance that autospecs BrokerInterface.
    Autospeccing means the mock will only have methods and attributes
    of the actual BrokerInterface, and calls with wrong signatures will fail.
    """
    mock_broker = create_autospec(BrokerInterface, instance=True)
    
    # Set up default return values or side effects if needed for most tests
    mock_broker.submit_order.return_value = 123 # Example broker_order_id
    mock_broker.cancel_order.return_value = True
    # The callback will be set by PositionManager during its init
    mock_broker.trade_confirmation_callback = None 
    
    # We need a way for the mock broker to simulate receiving confirmations
    # and calling the callback. This is tricky with a strict mock.
    # For unit tests, we often call the PM's callback method directly.
    return mock_broker

@pytest.fixture
def position_manager_with_mock_broker(mock_broker_interface):
    """
    Provides a PositionManager instance initialized with the mock_broker_interface.
    The mock_broker's trade_confirmation_callback will be set by the PM.
    """
    pm = PositionManager(broker=mock_broker_interface)
    # The PM constructor calls broker.register_client_trade_confirmation_callback,
    # which in our BrokerInterface setup, means the broker's constructor would
    # store the callback. Our mock_broker_interface above has a placeholder.
    # The PM's constructor *should* have set the broker's callback.
    # Let's assume the mock_broker_interface's constructor (implicitly called by create_autospec)
    # would store the callback passed to it by PM.
    # So, `pm.broker.trade_confirmation_callback` should now be `pm._trade_confirmation_callback`
    
    # We can explicitly assign it here if the mock's spec doesn't handle it,
    # or if the PM's init doesn't directly set an attribute on the broker
    # but expects the broker to have stored it.
    # For BrokerInterface, the constructor takes the callback.
    # So, the mock_broker_interface should have its trade_confirmation_callback attribute set.
    # The PositionManager will use its own _trade_confirmation_callback to pass to the broker.

    # Let's assert the callback is set on the mock (it should be from PM's init)
    # The mock_broker_interface itself doesn't *have* a trade_confirmation_callback attribute
    # in its spec to be set. The PM calls `broker_constructor(callback)`.
    # So, the mock `__init__` would have been called with the callback.
    # We can verify this by checking the mock's `call_args` for `__init__` if needed,
    # or more simply, allow tests to directly call `pm._trade_confirmation_callback`.

    return pm

# You might also want a fixture for the SimulatedBroker if you do integration-style tests
# that don't hit the API but test PM + SimulatedBroker
from app.brokers.simulated_broker import SimulatedBroker

@pytest.fixture
def simulated_broker():
    # This broker needs a callback. We can provide a dummy one for setup,
    # or tests using this will need to re-assign it.
    # Typically, the PM would provide its callback.
    broker = SimulatedBroker(trade_confirmation_callback=lambda conf: print(f"SimBroker Fixture CB: {conf}"))
    broker.start()
    yield broker
    broker.stop()

@pytest.fixture
def position_manager_with_sim_broker(simulated_broker):
    pm = PositionManager(broker=simulated_broker)
    # Crucially, re-assign the callback from PM to the broker instance
    simulated_broker.trade_confirmation_callback = pm._trade_confirmation_callback
    return pm