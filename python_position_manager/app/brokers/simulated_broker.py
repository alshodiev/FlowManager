# simulated_broker.py
import threading
import time
import sys
from random import random, randint, seed
from logging import getLogger
from typing import Callable, Dict, Optional

from broker_interface import BrokerInterface, TradeConfirmationMessage, OrderDetails # Assuming these are in broker_interface.py

# Your bs_str, bs_int functions
def bs_str(buy_sell: bool) -> str:
    return "BUY" if buy_sell else "SELL"
def bs_int(buy_sell: bool) -> int:
    return 1 if buy_sell else -1

class SimulatedOrder:
    def __init__(self,
                 broker_order_id: int,
                 client_order_id: str,
                 symbol: str,
                 amount: int,
                 buy_sell: bool,
                 sim_broker_callback: Callable # This callback is internal to SimulatedBroker
    ):
        self.broker_order_id = broker_order_id
        self.client_order_id = client_order_id
        self.symbol = symbol
        self.amount = amount
        self.buy_sell = buy_sell
        self.sim_broker_callback = sim_broker_callback # To notify SimulatedBroker upon completion

        self.amount_filled = 0
        self.cancelling = False
        self.logger = getLogger(f'SimulatedOrder-{broker_order_id}-{client_order_id}')
        self.status = "WORKING"

    def execute_order_thread(self):
        execute_order_start_time = time.time()
        self.logger.debug(f'Starting execution for order {self.broker_order_id} ({self.client_order_id})')
        while not self.cancelling and self.amount_filled < self.amount:
            filled_this_step = min(randint(1, max(1,self.amount // 10)), self.amount - self.amount_filled) # Fill ~10%
            self.amount_filled += filled_this_step
            self.logger.debug(f'Filled {self.amount_filled}/{self.amount} for {self.symbol}')
            # Simulate a partial fill notification (optional for 1-day, but good practice)
            # For now, send one confirmation at the end.
            time.sleep(random() * 0.1) # Faster simulation

        final_status = "CANCELLED" if self.cancelling else "FILLED"
        self.status = final_status
        self.logger.debug(f'Finished order {self.broker_order_id} ({self.client_order_id}) {bs_str(self.buy_sell)} {self.amount_filled} {self.symbol}, Status: {final_status}')
        confirmation = TradeConfirmationMessage(
            order_id=self.broker_order_id,
            client_order_id=self.client_order_id,
            symbol=self.symbol,
            filled_quantity=self.amount_filled,
            side_is_buy=self.buy_sell,
            price=100.0, # Simulated price
            status=final_status
        )
        self.sim_broker_callback(confirmation) # Notify SimulatedBroker
        self.logger.debug(f'Executed order in {time.time() - execute_order_start_time:.2f} seconds')

    def cancel_order(self):
        self.logger.debug(f'Cancelling order {self.broker_order_id} ({self.client_order_id})')
        self.cancelling = True
        self.status = "PENDING_CANCEL"


class SimulatedBroker(BrokerInterface):
    def __init__(self, trade_confirmation_callback: Callable[[TradeConfirmationMessage], None]):
        super().__init__(trade_confirmation_callback)
        self.next_broker_order_id_gen = (i for i in range(sys.maxsize))
        self.live_orders: Dict[str, SimulatedOrder] = {} # key: client_order_id
        self.lock = threading.Lock()
        self.logger = getLogger('SimulatedBroker')
        seed(123) # Keep seed for reproducibility if needed

    def _internal_sim_trade_callback(self, confirmation_msg: TradeConfirmationMessage):
        """
        Internal callback from SimulatedOrder when it finishes.
        This then calls the main callback registered by PositionManager.
        """
        self.logger.debug(f'Internal CB: Received trade confirmation for cl_ord_id {confirmation_msg.client_order_id}, broker_ord_id {confirmation_msg.order_id}')
        with self.lock:
            if confirmation_msg.client_order_id in self.live_orders:
                # Order might be fully filled or cancelled with partial fill
                # Remove from live_orders as its lifecycle is complete
                del self.live_orders[confirmation_msg.client_order_id]

        # Forward to the PositionManager's callback
        if self.trade_confirmation_callback:
            self.trade_confirmation_callback(confirmation_msg)
        else:
            self.logger.error("No trade_confirmation_callback registered with SimulatedBroker!")


    def submit_order(self, client_order_id: str, symbol: str, quantity: int, side_is_buy: bool, order_type: str = "MARKET", price: Optional[float] = None) -> Optional[int]:
        self.logger.debug(f'Received order: cl_id={client_order_id}, {bs_str(side_is_buy)} {quantity} of {symbol}')
        if self.trade_confirmation_callback is None:
            self.logger.error('Unable to process order: PositionManager callback not registered.')
            # Could send a REJECTED TradeConfirmationMessage here
            return None

        with self.lock:
            if client_order_id in self.live_orders:
                self.logger.error(f"Duplicate client_order_id: {client_order_id}. Rejecting.")
                # Send REJECTED confirmation
                reject_msg = TradeConfirmationMessage(
                    order_id=-1, client_order_id=client_order_id, symbol=symbol,
                    filled_quantity=0, side_is_buy=side_is_buy, price=0, status="REJECTED"
                )
                # Schedule this to run slightly later to avoid re-entrancy issues if PM reacts immediately
                threading.Timer(0.01, self.trade_confirmation_callback, args=[reject_msg]).start()
                return None

            broker_order_id = next(self.next_broker_order_id_gen)
            sim_order = SimulatedOrder(
                broker_order_id=broker_order_id,
                client_order_id=client_order_id,
                symbol=symbol,
                amount=quantity,
                buy_sell=side_is_buy,
                sim_broker_callback=self._internal_sim_trade_callback
            )
            self.live_orders[client_order_id] = sim_order

        self.logger.debug(f'Creating thread for simulated order {broker_order_id} ({client_order_id})')
        thread_order = threading.Thread(target=sim_order.execute_order_thread)
        thread_order.daemon = True # Allow main program to exit even if threads are running
        thread_order.start()
        return broker_order_id

    def cancel_order(self, client_order_id: str) -> bool:
        self.logger.debug(f'Request to cancel order: cl_id={client_order_id}')
        with self.lock:
            if client_order_id in self.live_orders:
                order_to_cancel = self.live_orders[client_order_id]
                order_to_cancel.cancel_order()
                # The order thread itself will send the final (possibly partial) confirmation
                return True
            else:
                self.logger.warning(f"Order {client_order_id} not found for cancellation or already completed.")
                # Send a "CANCEL_REJECTED" or "UNKNOWN_ORDER" confirmation if appropriate
                # For simplicity, just return False
                return False

    def get_order_details(self, client_order_id: str) -> Optional[OrderDetails]:
        with self.lock:
            sim_order = self.live_orders.get(client_order_id)
            if sim_order:
                return OrderDetails(
                    client_order_id=sim_order.client_order_id,
                    broker_order_id=sim_order.broker_order_id,
                    symbol=sim_order.symbol,
                    quantity=sim_order.amount,
                    side_is_buy=sim_order.buy_sell,
                    type="MARKET", # Assuming market for sim
                    price=None,
                    status=sim_order.status, # "WORKING", "PENDING_CANCEL", (FILLED/CANCELLED are removed)
                    filled_quantity=sim_order.amount_filled
                )
            return None

    def start(self):
        self.logger.info("SimulatedBroker started.")
        # No explicit background tasks needed for sim beyond order threads

    def stop(self):
        self.logger.info('Terminating all simulated orders from SimulatedBroker.')
        orders_to_wait_for = []
        with self.lock:
            for order in self.live_orders.values():
                order.cancel_order() # Request cancellation
                # We can't easily join threads here as they belong to SimulatedOrder objects
                # and the callback mechanism handles their lifecycle.
                # For a clean shutdown, we'd need to track threads.
                # For 1-day, daemon threads are okay.
        self.logger.info("SimulatedBroker stop initiated. Order threads will complete.")