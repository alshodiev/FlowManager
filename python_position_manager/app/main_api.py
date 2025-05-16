# main_api.py
import uvicorn
from fastapi import FastAPI, HTTPException, Body, Request
from fastapi.responses import JSONResponse
import threading
import logging
import time
import sys # For path modification if necessary

# --- Add project root to Python path if running scripts from different dirs ---
# import pathlib
# project_root = pathlib.Path(__file__).resolve().parent
# sys.path.append(str(project_root))
# --- End Path Modification ---

from position_manager import PositionManager
from cpp_ob_broker import CppOrderBookBroker
# from simulated_broker import SimulatedBroker # For fallback

# Configure logging (place this at the top level of your script)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)] # Ensure logs go to stdout
)
logger = logging.getLogger("FastAPIApp")


app = FastAPI(title="Trade Execution System")

# Global instances (handle with care in production, use FastAPI lifespan for proper setup/teardown)
pm_instance: Optional[PositionManager] = None
pm_thread: Optional[threading.Thread] = None
broker_instance: Optional[CppOrderBookBroker] = None # Or SimulatedBroker

# --- FastAPI Lifespan Events (Recommended over @app.on_event) ---
@app.on_event("startup")
async def lifespan_startup():
    global pm_instance, pm_thread, broker_instance
    logger.info("Application starting up...")

    # Initialize broker
    # Option 1: CppOrderBookBroker
    # Callback will be properly set after PM is instantiated
    def temp_broker_cb(confirmation): logger.critical(f"Broker CB called before PM fully ready: {confirmation}")

    # Ensure C++ server is running on this address
    cpp_broker_addr = "tcp://localhost:5555"
    broker_instance = CppOrderBookBroker(
        trade_confirmation_callback=temp_broker_cb, # Placeholder
        zmq_req_addr=cpp_broker_addr
    )
    try:
        broker_instance.start() # Attempt to connect to C++ OB
        logger.info(f"CppOrderBookBroker started and connected to {cpp_broker_addr}.")
    except ConnectionError as e:
        logger.error(f"CRITICAL: Could not connect to C++ Order Book server at {cpp_broker_addr}. Error: {e}")
        logger.error("The application will start, but trading will not function.")
        # Depending on requirements, you might choose to raise an exception here to prevent startup
        # For this project, we'll let it start but log critical error.

    # Option 2: SimulatedBroker (for testing without C++)
    # from simulated_broker import SimulatedBroker
    # broker_instance = SimulatedBroker(trade_confirmation_callback=temp_broker_cb)
    # broker_instance.start()
    # logger.info("SimulatedBroker started.")

    # Initialize PositionManager and set the actual broker callback
    pm_instance = PositionManager(broker=broker_instance) # PM gets the broker instance
    if broker_instance: # If broker initialized successfully
        broker_instance.trade_confirmation_callback = pm_instance._trade_confirmation_callback

    logger.info("Starting Position Manager thread...")
    pm_thread = threading.Thread(target=pm_instance.run, name="PositionManagerThread")
    pm_thread.daemon = True # Allow uvicorn to manage shutdown by not blocking exit
    pm_thread.start()
    logger.info("Position Manager thread started.")


@app.on_event("shutdown")
async def lifespan_shutdown():
    logger.info("Application shutting down...")
    if pm_instance:
        logger.info("Terminating Position Manager...")
        pm_instance.terminate() # Signal PM to stop its loop
    
    if broker_instance: # Ensure broker is stopped
        logger.info("Stopping Broker...")
        broker_instance.stop()

    if pm_thread and pm_thread.is_alive():
        logger.info("Waiting for Position Manager thread to join...")
        pm_thread.join(timeout=10) # Give PM thread time to finish
        if pm_thread.is_alive():
            logger.warning("Position Manager thread did not terminate cleanly after 10s.")
    logger.info("Shutdown complete.")


# --- API Endpoints ---
@app.post("/target_position", summary="Set Target Position for a Symbol")
async def set_target_position_api(symbol: str = Body(..., embed=True, description="Trading symbol, e.g., AAPL"),
                                  quantity: int = Body(..., embed=True, description="Target quantity (positive for long, negative for short, 0 to flatten)")):
    if not pm_instance:
        logger.error("API call to /target_position when PM not initialized.")
        raise HTTPException(status_code=503, detail="Position Manager not initialized or broker connection failed.")
    logger.info(f"API: Received target for {symbol} -> {quantity}")
    pm_instance.update_target_position(symbol, quantity)
    return {"message": f"Target position for {symbol} updated to {quantity}. Processing initiated."}

@app.get("/state", summary="Get Current System State")
async def get_system_state_api():
    if not pm_instance:
        logger.error("API call to /state when PM not initialized.")
        raise HTTPException(status_code=503, detail="Position Manager not initialized or broker connection failed.")
    return pm_instance.get_current_state_snapshot()

@app.get("/market_data/{symbol}", summary="Get Market Data Snapshot for a Symbol")
async def get_market_data_api(symbol: str):
    global broker_instance
    if not broker_instance or not isinstance(broker_instance, CppOrderBookBroker):
         logger.warning(f"API call to /market_data/{symbol} but CppOrderBookBroker not active.")
         raise HTTPException(status_code=501, detail="Market data endpoint requires the CppOrderBookBroker and it's not active or configured.")
    
    if broker_instance.socket is None or broker_instance.socket.closed: # Check connection
        logger.error(f"API call to /market_data/{symbol} but broker socket is not connected.")
        raise HTTPException(status_code=503, detail="Broker is not connected to the C++ Order Book server.")

    data = broker_instance.get_market_data_snapshot(symbol)
    if data:
        return data
    else:
        logger.warning(f"Failed to retrieve market data for {symbol} from broker.")
        raise HTTPException(status_code=404, detail=f"Could not retrieve market data for {symbol}. Check C++ OB server and logs.")

# --- Exception Handler for Graceful Error Responses ---
@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception for request {request.url}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"message": "An internal server error occurred.", "detail": str(exc)},
    )

if __name__ == "__main__":
    logger.info("Starting Uvicorn server directly for development...")
    # workers=1 is important for shared global state if not using lifespan correctly for worker-specific resources
    uvicorn.run(app, host="0.0.0.0", port=8000, workers=1)