# python_position_manager/tests/integration/test_api_endpoints.py
import pytest
import time
import threading
from fastapi.testclient import TestClient

# We need to import the FastAPI app instance
# Adjust path as necessary, assuming 'app' module is in PYTHONPATH
from app.main_api import app as fastapi_app, lifespan_startup, lifespan_shutdown # Import the app and lifespan events
from app.position_manager import PositionManager
from app.brokers.simulated_broker import SimulatedBroker
from app.brokers.broker_interface import TradeConfirmationMessage

# Global variable to hold the PositionManager instance for inspection during tests
# This is a bit of a hack for testing, in real app, you wouldn't do this.
# Instead, the main_api module would expose it or have a way to get it.
# For now, we can access it via app.state if FastAPI stores it there after lifespan.
# Or, we can re-initialize a PM and broker specifically for these tests.

@pytest.fixture(scope="module", autouse=True)
async def manage_lifespan():
    """
    Fixture to run FastAPI startup and shutdown events for the test module.
    `autouse=True` makes it run automatically for all tests in this module.
    `scope="module"` means it runs once per test module.
    """
    # In main_api.py, pm_instance and broker_instance are global.
    # We need to ensure they are correctly set up for the TestClient.
    # The lifespan events should handle this.
    await lifespan_startup() # Call the startup event
    yield
    await lifespan_shutdown() # Call the shutdown event

@pytest.fixture(scope="module")
def client():
    """Provides a TestClient instance for making API requests."""
    # The TestClient will run the app's lifespan events if they are set up correctly
    # with app.router.lifespan_context
    with TestClient(fastapi_app) as test_client:
        yield test_client

# Helper to get the global PM instance from the FastAPI app
# This relies on how main_api.py sets up its globals.
# A cleaner way would be for main_api.py to have a getter or use app.state
def get_pm_instance_from_app():
    # This is highly dependent on your main_api.py structure
    # For now, let's assume main_api.py has a global `pm_instance` we can import
    # Or, if it's attached to app.state:
    # return fastapi_app.state.pm_instance
    # This needs main_api.py to be refactored slightly to make pm_instance accessible for tests
    # For this example, let's assume we can import it (bad practice for prod code, ok for example)
    import app.main_api as main_api_module
    return main_api_module.pm_instance


def test_set_target_position_api(client): # client fixture is from TestClient(app)
    pm_instance = get_pm_instance_from_app()
    assert pm_instance is not None, "PM instance not found in app"
    
    response = client.post("/target_position", json={"symbol": "PYTEST_AAPL", "quantity": 100})
    assert response.status_code == 200
    assert response.json()["message"] == "Target position for PYTEST_AAPL updated to 100. Processing initiated."

    # Allow some time for the PM thread to process the target
    # In a real test, you might use polling or a condition variable.
    time.sleep(0.2) # Small delay for PM to process the queue

    # Check internal state of PM (this makes it more of an integration/white-box test)
    assert pm_instance.target_positions.get("PYTEST_AAPL") == 100
    
    # Assuming SimulatedBroker is used by default in main_api.py for testing
    # (or you configure main_api.py to use SimulatedBroker for tests)
    # We expect an order to have been submitted.
    # The SimulatedBroker runs orders in threads. We need to wait for fills.
    # And check if the position reflects the target.
    max_wait = 5  # seconds
    start_time = time.time()
    final_position_reached = False
    while time.time() - start_time < max_wait:
        state = pm_instance.get_current_state_snapshot()
        if state["positions"].get("PYTEST_AAPL") == 100:
            final_position_reached = True
            break
        time.sleep(0.1)
    
    assert final_position_reached, "Position for PYTEST_AAPL did not reach target 100 in time."
    final_state = pm_instance.get_current_state_snapshot()
    assert final_state["live_orders_count_by_symbol"].get("PYTEST_AAPL", 0) == 0 # Orders should be filled

def test_get_system_state_api(client):
    # May need to set a target first to have interesting state
    client.post("/target_position", json={"symbol": "PYTEST_MSFT", "quantity": -50})
    time.sleep(0.5) # Allow PM and SimulatedBroker to process

    response = client.get("/state")
    assert response.status_code == 200
    data = response.json()
    assert "positions" in data
    assert "targets" in data
    assert "live_orders_details" in data
    assert data["targets"].get("PYTEST_MSFT") == -50
    # Position might take time to reach target with SimulatedBroker
    # For a quick check, just verify structure

# More integration tests:
# - Test with multiple target updates in sequence.
# - Test flattening a position (target 0).
# - Test flipping a position (e.g., long 100 to short 50).
# - Test what happens if the broker rejects an order (SimulatedBroker can be made to do this).
# - Test the /market_data endpoint (would require CppOrderBookBroker and the C++ server running,
#   or mocking the CppOrderBookBroker's get_market_data_snapshot method for this test).