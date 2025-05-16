# strategy_runner.py
import os
import sys
import json
import threading
import time
from enum import Enum
from logging import getLogger, basicConfig

# Make sure other modules are importable (adjust sys.path if needed or run as module)
from position_manager import PositionManager
from simulated_broker import SimulatedBroker # Using simulated broker for now
# from cpp_ob_broker import CppOrderBookBroker # This will be for C++ OB

basicConfig(level=os.environ.get("LOGLEVEL", "INFO")) # INFO for less noise

class Event(str, Enum):
    Target = 'Target'
    Wait = 'Wait'
    LogPosition = 'LogPosition' # Renamed for clarity from your original

class Strategy:
    def __init__(self, position_manager: PositionManager):
        self.position_manager = position_manager
        self.logger = getLogger("Strategy")

    def replay_events_log(self, events):
        self.logger.info("Starting strategy event replay...")
        for i, event_data in enumerate(events):
            self.logger.debug(f"Event {i+1}: {event_data}")
            if self.position_manager.terminate_flag.is_set():
                self.logger.info("Position Manager terminated, stopping strategy.")
                break

            event_type = event_data.get('Event')
            if event_type == Event.Wait.value: # Compare with .value for Enum
                sleep_duration = event_data.get('Seconds', 0)
                self.logger.info(f"Waiting for {sleep_duration} seconds...")
                time.sleep(sleep_duration)
            elif event_type == Event.Target.value:
                symbol = event_data.get('Symbol')
                target = event_data.get('Target')
                if symbol is not None and target is not None:
                    self.logger.info(f"Strategy sends target: {symbol} -> {target}")
                    self.position_manager.update_target_position(symbol, target)
                else:
                    self.logger.warning(f"Invalid Target event: {event_data}")
            elif event_type == Event.LogPosition.value:
                self.logger.info("Strategy requests position log.")
                self.position_manager.log_current_summary() # Use the new summary log
            else:
                self.logger.error(f'Unknown replay event type: {event_type} in {event_data}')
        self.logger.info("Strategy event replay finished.")

def read_event_log_from_stdin():
    event_log = []
    print("Reading event log from STDIN (Ctrl+D or Ctrl+Z then Enter to end):", file=sys.stderr)
    for line in sys.stdin:
        try:
            event_data = json.loads(line.strip())
            event_log.append(event_data)
        except json.JSONDecodeError as e:
            getLogger("Main").error(f"Error decoding JSON from stdin: {e} on line: {line.strip()}")
    print(f"Read {len(event_log)} events.", file=sys.stderr)
    return event_log

if __name__ == '__main__':
    main_logger = getLogger('MainRunner')
    main_logger.info("System Starting...")
    test_start_time = time.time()

    event_log = read_event_log_from_stdin()
    if not event_log:
        main_logger.warning("No events read from stdin. Exiting.")
        sys.exit(0)

    # Initialize SimulatedBroker with the PositionManager's callback
    # The PositionManager needs the broker instance at init.
    # The broker needs the PM's callback. Chicken and egg.
    # Solution: Pass a placeholder or set it after PM init.
    # OR: Broker init takes the callback. PM init takes the broker.
    
    # Step 1: Create a placeholder for the callback initially for PM
    # This is a bit complex. Let's simplify: PM will set broker's callback.
    # No, the BrokerInterface defines constructor takes callback.
    
    pm_instance = PositionManager(broker=None) # Broker will be set shortly
    
    # Now create broker and give it the PM's callback
    # For SimulatedBroker
    sim_broker = SimulatedBroker(trade_confirmation_callback=pm_instance._trade_confirmation_callback)
    pm_instance.broker = sim_broker # Now PM has its broker

    # For CppOrderBookBroker (when ready)
    # cpp_broker = CppOrderBookBroker(trade_confirmation_callback=pm_instance._trade_confirmation_callback, zmq_req_port="tcp://localhost:5555", zmq_sub_port="tcp://localhost:5556")
    # pm_instance.broker = cpp_broker

    main_logger.info("Starting Position Manager thread...")
    thread_position_manager = threading.Thread(target=pm_instance.run, name="PositionManagerThread")
    thread_position_manager.daemon = True # So it exits if main thread exits
    thread_position_manager.start()

    strategy = Strategy(pm_instance)
    strategy.replay_events_log(event_log)

    main_logger.info("Strategy finished. Terminating Position Manager...")
    pm_instance.terminate() # Signal PM to stop
    
    # Wait for PM thread to finish its current loop and clean up
    # The broker.stop() is called inside pm_instance.run() before it exits
    thread_position_manager.join(timeout=10) # Wait up to 10 seconds

    if thread_position_manager.is_alive():
        main_logger.warning("Position Manager thread did not terminate cleanly.")

    main_logger.info("Final Position Manager State:")
    pm_instance.log_current_summary() # Log final state

    main_logger.info('Test Time: %.2f seconds' % (time.time() - test_start_time))
    main_logger.info("System Shutdown.")