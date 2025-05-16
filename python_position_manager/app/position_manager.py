# position_manager.py (Significant rewrite/refinement)
import os
import json
import threading
import time
import uuid # For unique client_order_ids
from collections import defaultdict
from logging import getLogger, basicConfig
from queue import Queue # Using regular Queue for FIFO generally
from typing import Dict, List, Tuple, Optional, Set

from broker_interface import BrokerInterface, TradeConfirmationMessage, OrderDetails # Ensure this import works

# Your bs_str, bs_int functions
def bs_str(buy_sell: bool) -> str: return "BUY" if buy_sell else "SELL"
def bs_int(buy_sell: bool) -> int: return 1 if buy_sell else -1


class PositionManager:
    def __init__(self, broker: BrokerInterface):
        self.broker = broker # This will be an instance of SimulatedBroker or CppBroker
        # The broker should be initialized with self._trade_confirmation_callback
        # broker.register_trade_confirmation_callback(self._trade_confirmation_callback) <- This is done by broker constructor now

        self.positions: Dict[str, int] = defaultdict(int) # Actual held positions
        self.target_positions: Dict[str, int] = defaultdict(int)
        
        # Tracking orders sent by PM
        # client_order_id -> OrderDetails object
        self.live_orders: Dict[str, OrderDetails] = {}
        # symbol -> list of client_order_id
        self.live_orders_by_symbol: Dict[str, List[str]] = defaultdict(list)

        self.total_traded_by_symbol: Dict[str, int] = defaultdict(int) # Gross traded volume

        # Queues for asynchronous updates
        self.target_updates_q: Queue[Tuple[str, int]] = Queue() # (symbol, target_amount)
        self.trade_confirmations_q: Queue[TradeConfirmationMessage] = Queue() # TradeConfirmation from broker

        self.terminate_flag = threading.Event()
        self.lock = threading.Lock() # Master lock for critical sections modifying shared state

        self.logger = getLogger("PositionManager")
        self.logger.debug('Position Manager Initialized')

    def _generate_client_order_id(self) -> str:
        return str(uuid.uuid4())

    # --- Callbacks and Queue Processors ---
    def _trade_confirmation_callback(self, confirmation: TradeConfirmationMessage):
        """Callback for the broker to push trade confirmations."""
        self.logger.info(f"Callback received: {confirmation}")
        self.trade_confirmations_q.put(confirmation)

    def _process_trade_confirmations(self) -> Set[str]:
        """Processes filled/cancelled orders from the queue."""
        symbols_affected = set()
        with self.lock:
            while not self.trade_confirmations_q.empty():
                try:
                    conf = self.trade_confirmations_q.get_nowait()
                except Exception: # Should be queue.Empty
                    break
                
                self.logger.debug(f"Processing confirmation: {conf}")
                symbols_affected.add(conf.symbol)
                
                # Update actual position
                self.positions[conf.symbol] += conf.filled_quantity * bs_int(conf.side_is_buy)
                self.total_traded_by_symbol[conf.symbol] += conf.filled_quantity

                # Update live order status
                live_order = self.live_orders.get(conf.client_order_id)
                if live_order:
                    live_order.filled_quantity += conf.filled_quantity # Accumulate fills
                    live_order.status = conf.status # Update to FILLED, PARTIALLY_FILLED, CANCELLED
                    
                    if conf.status in ["FILLED", "CANCELLED", "REJECTED"]:
                        self.logger.info(f"Order {conf.client_order_id} ({conf.symbol}) reached terminal state: {conf.status}. Removing from live tracking.")
                        del self.live_orders[conf.client_order_id]
                        if conf.client_order_id in self.live_orders_by_symbol.get(conf.symbol, []):
                           self.live_orders_by_symbol[conf.symbol].remove(conf.client_order_id)
                           if not self.live_orders_by_symbol[conf.symbol]: # cleanup if list empty
                               del self.live_orders_by_symbol[conf.symbol]
                    else: # e.g. PARTIALLY_FILLED
                        self.logger.info(f"Order {conf.client_order_id} ({conf.symbol}) partially filled. Remaining: {live_order.quantity - live_order.filled_quantity}")
                else:
                    self.logger.warning(f"Received confirmation for unknown/completed client_order_id: {conf.client_order_id}")
        return symbols_affected

    def _process_target_updates(self) -> Set[str]:
        """Processes target position updates from the queue."""
        symbols_affected = set()
        with self.lock: # Protect target_positions
            while not self.target_updates_q.empty():
                try:
                    symbol, target_amount = self.target_updates_q.get_nowait()
                except Exception:
                    break
                self.logger.info(f"Updating target for {symbol} to {target_amount}")
                self.target_positions[symbol] = target_amount
                symbols_affected.add(symbol)
        return symbols_affected

    # --- External API for Strategy/FastAPI ---
    def update_target_position(self, symbol: str, target_amount: int):
        self.logger.info(f'Received target update: {symbol} -> {target_amount}')
        self.target_updates_q.put((symbol, target_amount))

    def get_current_state_snapshot(self) -> Dict:
        with self.lock: # Ensure a consistent snapshot
            state = {
                "positions": dict(self.positions),
                "targets": dict(self.target_positions),
                "live_orders_count_by_symbol": {s: len(ids) for s, ids in self.live_orders_by_symbol.items()},
                "live_orders_details": [vars(o) for o in self.live_orders.values()], # List of dicts
                "total_traded_by_symbol": dict(self.total_traded_by_symbol)
            }
        return state

    # --- Core Order Management Logic ---
    def _calculate_working_position(self, symbol: str) -> int:
        """ Calculates current position + net effect of live orders. Called under lock. """
        actual_pos = self.positions.get(symbol, 0)
        working_pos = actual_pos
        
        for client_ord_id in self.live_orders_by_symbol.get(symbol, []):
            order = self.live_orders.get(client_ord_id)
            if order and order.status not in ["FILLED", "CANCELLED", "REJECTED"]: # only "live" orders
                remaining_qty = order.quantity - order.filled_quantity
                if remaining_qty > 0:
                    working_pos += remaining_qty * bs_int(order.side_is_buy)
        return working_pos

    def _reconcile_positions(self, symbols_to_check: Set[str]):
        """The core logic to adjust positions to targets."""
        if not symbols_to_check:
            return

        with self.lock:
            for symbol in symbols_to_check:
                target_pos = self.target_positions.get(symbol, 0) # Default to 0 if no target (e.g. only trade came in)
                working_pos = self._calculate_working_position(symbol) # Needs to be accurate

                delta = target_pos - working_pos
                self.logger.info(f"Reconciling {symbol}: Target={target_pos}, Actual={self.positions.get(symbol,0)}, Working={working_pos}, Delta={delta}")

                if delta == 0:
                    self.logger.debug(f"{symbol} is on target. No action needed.")
                    continue

                # --- Order Management Logic based on Share Delta ---
                if delta > 0: # Need to BUY more
                    # 1. Cancel any existing LIVE SELL orders for this symbol
                    for client_ord_id in list(self.live_orders_by_symbol.get(symbol, [])): # Iterate copy
                        order = self.live_orders.get(client_ord_id)
                        if order and not order.side_is_buy and order.status not in ["FILLED", "CANCELLED", "REJECTED", "PENDING_CANCEL"]:
                            self.logger.info(f"Delta is BUY ({delta}). Cancelling existing SELL order {client_ord_id} for {symbol}.")
                            if self.broker.cancel_order(client_ord_id):
                                order.status = "PENDING_CANCEL" # Mark as pending cancel
                            else:
                                self.logger.warning(f"Failed to send cancel request for {client_ord_id}")
                    # 2. Place new BUY order for abs(delta)
                    new_buy_id = self._generate_client_order_id()
                    self.logger.info(f"Placing new BUY order {new_buy_id} for {symbol}, Amount: {abs(delta)}")
                    self.live_orders[new_buy_id] = OrderDetails(
                        client_order_id=new_buy_id, broker_order_id=None, symbol=symbol,
                        quantity=abs(delta), side_is_buy=True, type="MARKET", price=None,
                        status="PENDING_NEW", filled_quantity=0
                    )
                    self.live_orders_by_symbol[symbol].append(new_buy_id)
                    # The actual broker_order_id might come back synchronously or later via a confirmation
                    b_ord_id = self.broker.submit_order(new_buy_id, symbol, abs(delta), True, "MARKET")
                    if b_ord_id is not None: self.live_orders[new_buy_id].broker_order_id = b_ord_id
                    # If submit_order fails (e.g. returns None and no REJECTED confirmation immediately), PM needs to handle this state

                elif delta < 0: # Need to SELL more
                    # 1. Cancel any existing LIVE BUY orders for this symbol
                    for client_ord_id in list(self.live_orders_by_symbol.get(symbol, [])): # Iterate copy
                        order = self.live_orders.get(client_ord_id)
                        if order and order.side_is_buy and order.status not in ["FILLED", "CANCELLED", "REJECTED", "PENDING_CANCEL"]:
                            self.logger.info(f"Delta is SELL ({delta}). Cancelling existing BUY order {client_ord_id} for {symbol}.")
                            if self.broker.cancel_order(client_ord_id):
                                order.status = "PENDING_CANCEL"
                            else:
                                self.logger.warning(f"Failed to send cancel request for {client_ord_id}")
                    # 2. Place new SELL order for abs(delta)
                    new_sell_id = self._generate_client_order_id()
                    self.logger.info(f"Placing new SELL order {new_sell_id} for {symbol}, Amount: {abs(delta)}")
                    self.live_orders[new_sell_id] = OrderDetails(
                        client_order_id=new_sell_id, broker_order_id=None, symbol=symbol,
                        quantity=abs(delta), side_is_buy=False, type="MARKET", price=None,
                        status="PENDING_NEW", filled_quantity=0
                    )
                    self.live_orders_by_symbol[symbol].append(new_sell_id)
                    b_ord_id = self.broker.submit_order(new_sell_id, symbol, abs(delta), False, "MARKET")
                    if b_ord_id is not None: self.live_orders[new_sell_id].broker_order_id = b_ord_id


    # --- Main Loop ---
    def run(self):
        self.logger.info("Position Manager thread started.")
        self.broker.start() # Start the broker's communication
        
        while not self.terminate_flag.is_set():
            symbols_from_trades = self._process_trade_confirmations()
            symbols_from_targets = self._process_target_updates()

            symbols_to_reconcile = symbols_from_trades.union(symbols_from_targets)
            # Periodically check all symbols with targets even if no new updates
            # This helps if an order got "stuck" or needs re-evaluation
            # For 1-day, just reconciling on updates is simpler.
            # with self.lock: symbols_to_reconcile.update(self.target_positions.keys())


            if symbols_to_reconcile:
                self.logger.debug(f"Symbols to reconcile: {symbols_to_reconcile}")
                self._reconcile_positions(symbols_to_reconcile)
            else:
                # Sleep if no symbols to reconcile from queue processing
                # The queues themselves will block if empty on get, but this loop needs to poll
                # Or use Queue.get(timeout=...) to prevent busy-wait
                time.sleep(0.01) # Small sleep to prevent busy loop if queues are empty

        self.logger.info("Position Manager run loop ending.")
        self.broker.stop() # Cleanly stop the broker
        self.logger.info("Position Manager terminated.")

    def terminate(self):
        self.logger.info("Terminate signal received for Position Manager.")
        self.terminate_flag.set()

    def log_current_summary(self): # For use by strategy/main
        self.logger.info(f"PM SUMMARY: {json.dumps(self.get_current_state_snapshot(), indent=2)}")