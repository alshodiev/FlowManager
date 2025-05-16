# cpp_ob_broker.py
import zmq
import json
import threading
import logging
from typing import Callable, Optional, Dict, Any

from broker_interface import BrokerInterface, TradeConfirmationMessage, OrderDetails # From previous steps

# Helper functions (if not already in a common utils file)
def bs_str(buy_sell: bool) -> str: return "BUY" if buy_sell else "SELL"
def bs_int(buy_sell: bool) -> int: return 1 if buy_sell else -1


class CppOrderBookBroker(BrokerInterface):
    def __init__(self, trade_confirmation_callback: Callable[[TradeConfirmationMessage], None],
                 zmq_req_addr: str = "tcp://localhost:5555"):
        super().__init__(trade_confirmation_callback) # trade_confirmation_callback is stored in self.trade_confirmation_callback
        self.zmq_req_addr = zmq_req_addr
        self.context = zmq.Context.instance() # Get a global ZMQ context instance
        self.socket: Optional[zmq.Socket] = None # To be created in start()
        self.logger = logging.getLogger(self.__class__.__name__)

        self._broker_order_id_counter = 0
        self._lock = threading.Lock() # Protects counter and maps

        self.client_to_broker_id_map: Dict[str, int] = {}
        self.broker_to_client_id_map: Dict[int, str] = {}
        self.broker_id_to_order_details: Dict[int, OrderDetails] = {}

    def _get_next_broker_id(self) -> int:
        with self._lock:
            self._broker_order_id_counter += 1
            return self._broker_order_id_counter

    def start(self):
        if self.socket is None or self.socket.closed:
            self.socket = self.context.socket(zmq.REQ)
            self.socket.setsockopt(zmq.LINGER, 0) # Prevent hanging on close if messages pending
            self.socket.setsockopt(zmq.RCVTIMEO, 5000) # 5s timeout for recv
            self.socket.setsockopt(zmq.SNDTIMEO, 5000) # 5s timeout for send
            self.logger.info(f"Connecting CppOrderBookBroker REQ socket to {self.zmq_req_addr}")
            try:
                self.socket.connect(self.zmq_req_addr)
                self.logger.info(f"Successfully connected to {self.zmq_req_addr}")
                # Simple ping to check if server is up (optional, C++ server needs to handle PING)
                # self.socket.send_json({"command": "PING"})
                # response = self.socket.recv_json()
                # if response.get("reply") != "PONG":
                #     self.logger.error("PING to C++ server failed or got unexpected response.")
            except zmq.ZMQError as e:
                self.logger.error(f"Failed to connect ZMQ REQ socket to {self.zmq_req_addr}: {e}")
                self.socket.close() # Ensure socket is closed on connection failure
                self.socket = None
                raise ConnectionError(f"Could not connect to C++ Order Book server at {self.zmq_req_addr}") from e
        else:
            self.logger.info("CppOrderBookBroker already started or socket exists.")


    def stop(self):
        self.logger.info("Stopping CppOrderBookBroker...")
        if self.socket is not None and not self.socket.closed:
            try:
                self.socket.close(linger=0)
                self.logger.info("ZMQ REQ socket closed.")
            except Exception as e:
                self.logger.error(f"Error closing ZMQ socket: {e}")
        self.socket = None
        # Don't term context here if it's shared (Context.instance())
        # If context was self.context = zmq.Context(), then self.context.term()
        self.logger.info("CppOrderBookBroker stopped.")

    def _send_request_to_ob(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if self.socket is None or self.socket.closed:
            self.logger.error("ZMQ socket is not connected or closed. Cannot send request.")
            # Attempt to reconnect (simple version)
            try:
                self.start() # This will try to connect
                if self.socket is None or self.socket.closed: # If start failed
                    return None
            except ConnectionError:
                 return None # start() already logged

        try:
            self.logger.debug(f"Sending to C++ OB: {request}")
            self.socket.send_json(request)
            response_json = self.socket.recv_json()
            self.logger.debug(f"Received from C++ OB: {response_json}")
            return response_json
        except zmq.Again: # Timeout
            self.logger.error(f"ZMQ timeout waiting for response from C++ OB for request: {request.get('command')}, cl_id: {request.get('client_order_id')}")
            return None
        except zmq.ZMQError as e:
            self.logger.error(f"ZMQ Error during request '{request.get('command')}': {e}")
            # Consider socket state invalid, try to close and reopen on next call
            if self.socket: self.socket.close(); self.socket = None
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error during ZMQ communication: {e}")
            return None


    def submit_order(self, client_order_id: str, symbol: str, quantity: int, side_is_buy: bool,
                     order_type_str: str = "GTC", price: Optional[float] = None) -> Optional[int]:
        if price is None:
            self.logger.error(f"Order {client_order_id} for {symbol} needs a price for this C++ OB.")
            self._dispatch_rejection(client_order_id, symbol, side_is_buy, "Price not provided")
            return None

        broker_ord_id = self._get_next_broker_id()
        cpp_order_type = "GoodTillCancel" if order_type_str.upper() == "GTC" else "FillAndKill"

        # Store details optimisticallly. Clean up if submission fails.
        order_details_to_store = OrderDetails(
            client_order_id=client_order_id, broker_order_id=broker_ord_id,
            symbol=symbol, quantity=quantity, side_is_buy=side_is_buy,
            type=order_type_str.upper(), price=price, status="PENDING_ACK", filled_quantity=0
        )
        with self._lock:
            self.client_to_broker_id_map[client_order_id] = broker_ord_id
            self.broker_to_client_id_map[broker_ord_id] = client_order_id
            self.broker_id_to_order_details[broker_ord_id] = order_details_to_store

        request_msg = {
            "command": "ADD_ORDER",
            "client_order_id": client_order_id,
            "broker_order_id": broker_ord_id,
            "symbol": symbol,
            "side": "Buy" if side_is_buy else "Sell",
            "price": int(price), # C++ OB expects Price as uint32_t
            "quantity": quantity,
            "type": cpp_order_type
        }

        response_json = self._send_request_to_ob(request_msg)

        if not response_json or response_json.get("status") != "OK":
            error_msg = response_json.get("message", "Communication error or C++ OB rejected") if response_json else "No response from C++ OB"
            self.logger.error(f"Order submission failed for {client_order_id} (broker_id {broker_ord_id}): {error_msg}")
            self._dispatch_rejection(client_order_id, symbol, side_is_buy, error_msg)
            self._cleanup_order_maps(client_order_id, broker_ord_id) # Critical: cleanup on failure
            return None

        # Order submission acknowledged by C++ OB
        self.logger.info(f"Order {client_order_id} (broker_id {broker_ord_id}) acknowledged by C++ OB.")
        order_details_to_store.status = "ACKNOWLEDGED" # Or "WORKING" if not FAK

        # Process trades from response
        # C++ response "trades" field should be:
        # [ { "order_id_filled": int_id, "price": p, "traded_quantity": q, "side_of_original_order": "Buy|Sell" }, ... ]
        for fill_info in response_json.get("trades", []):
            filled_broker_id = fill_info.get("order_id_filled")
            traded_qty = fill_info.get("traded_quantity")
            fill_price = fill_info.get("price")
            # Side of original order is important if we don't want to look up order details each time
            # For now, we will look up original order details via filled_broker_id
            
            with self._lock: # Accessing shared maps
                original_client_id = self.broker_to_client_id_map.get(filled_broker_id)
                original_order = self.broker_id_to_order_details.get(filled_broker_id)

            if original_client_id and original_order and traded_qty > 0:
                self.logger.info(f"Processing fill for {original_client_id} (broker_id {filled_broker_id}): {bs_str(original_order.side_is_buy)} {traded_qty} {original_order.symbol} @ {fill_price}")
                
                original_order.filled_quantity += traded_qty
                
                # Determine confirmation status
                conf_status = "PARTIALLY_FILLED"
                is_fully_filled_on_this_order = (original_order.filled_quantity >= original_order.quantity)

                if is_fully_filled_on_this_order:
                    conf_status = "FILLED"
                    original_order.status = "FILLED"
                elif original_order.status != "FILLED": # Not fully filled yet
                     original_order.status = "WORKING" # Or keep as ACK if this is the first partial

                confirmation = TradeConfirmationMessage(
                    order_id=filled_broker_id, # Using broker_id for confirmation consistency
                    client_order_id=original_client_id,
                    symbol=original_order.symbol,
                    filled_quantity=traded_qty, # Quantity of THIS specific fill
                    side_is_buy=original_order.side_is_buy,
                    price=float(fill_price),
                    status=conf_status
                )
                self.trade_confirmation_callback(confirmation)

                if conf_status == "FILLED":
                    self._cleanup_order_maps(original_client_id, filled_broker_id)
            elif not original_client_id or not original_order:
                 self.logger.warning(f"Received fill for unknown/completed broker_id {filled_broker_id}. Ignoring.")


        # Handle final status of the newly submitted order itself
        # (e.g., FAK that didn't fill, or GTC that got fully filled on entry)
        new_order_final_status_in_book = response_json.get("order_final_status_in_book")
        with self._lock: # Ensure order_details_to_store is up-to-date
            # Check if the order is still in our active maps (it might have been filled and cleaned up)
            if broker_ord_id in self.broker_id_to_order_details:
                current_submitted_order_details = self.broker_id_to_order_details[broker_ord_id]
                if new_order_final_status_in_book == "FILLED":
                    # This should have been handled by loop above if trades were reported correctly
                    if current_submitted_order_details.status != "FILLED":
                        self.logger.warning(f"Order {client_order_id} reported FILLED by OB but not fully by trade events. Forcing.")
                        # This case indicates a mismatch or incomplete fill reporting.
                        # For safety, if OB says FILLED, ensure PM knows.
                        # Send a final fill if needed, or just update status.
                        # For now, rely on individual fills summing up.
                        current_submitted_order_details.status = "FILLED"
                        self._cleanup_order_maps(client_order_id, broker_ord_id)

                elif new_order_final_status_in_book == "REJECTED_BY_BOOK": # e.g. FAK order not (fully) filled
                    self.logger.info(f"Order {client_order_id} (type {current_submitted_order_details.type}) resulted in REJECTED_BY_BOOK (e.g. FAK cancel).")
                    # Fills (if any) were processed. Now send a CANCELLED confirmation for the order itself.
                    # The PM will see this as the order lifecycle ending.
                    confirmation = TradeConfirmationMessage(
                        order_id=broker_ord_id, client_order_id=client_order_id,
                        symbol=symbol,
                        # Filled quantity for this CANCELLED message is 0, as fills were separate events.
                        # The status "CANCELLED" here signals the end of the order's life.
                        filled_quantity=0,
                        side_is_buy=side_is_buy, price=float(price), status="CANCELLED"
                    )
                    self.trade_confirmation_callback(confirmation)
                    current_submitted_order_details.status = "CANCELLED" # Mark it
                    self._cleanup_order_maps(client_order_id, broker_ord_id)
                elif current_submitted_order_details.status == "ACKNOWLEDGED": # No fills on entry, GTC order is now resting
                    current_submitted_order_details.status = "WORKING"

        return broker_ord_id


    def cancel_order(self, client_order_id: str) -> bool:
        broker_ord_id = None
        original_order_details = None
        with self._lock:
            broker_ord_id = self.client_to_broker_id_map.get(client_order_id)
            if broker_ord_id:
                original_order_details = self.broker_id_to_order_details.get(broker_ord_id)

        if not broker_ord_id or not original_order_details:
            self.logger.warning(f"Cannot cancel: Order {client_order_id} not found or already completed.")
            return False

        if original_order_details.status in ["FILLED", "CANCELLED", "REJECTED", "PENDING_CANCEL"]:
            self.logger.warning(f"Cannot cancel: Order {client_order_id} already in terminal or pending cancel state '{original_order_details.status}'.")
            return False
        
        original_order_details.status = "PENDING_CANCEL" # Optimistic update

        request_msg = {"command": "CANCEL_ORDER", "broker_order_id": broker_ord_id}
        response_json = self._send_request_to_ob(request_msg)

        if not response_json or response_json.get("status") != "OK" or response_json.get("final_status") != "CANCELLED":
            error_msg = response_json.get("message", "Communication error or C++ OB cancel failed") if response_json else "No response from C++ OB"
            self.logger.error(f"Cancel request for {client_order_id} (broker_id {broker_ord_id}) failed: {error_msg}")
            if original_order_details: original_order_details.status = "WORKING" # Revert status
            return False

        # Cancellation confirmed by C++ OB
        self.logger.info(f"Order {client_order_id} (broker_id {broker_ord_id}) cancelled by C++ OB.")
        if original_order_details: original_order_details.status = "CANCELLED"

        confirmation = TradeConfirmationMessage(
            order_id=broker_ord_id,
            client_order_id=client_order_id,
            symbol=original_order_details.symbol,
            filled_quantity=0, # Cancellation itself doesn't fill. Prior fills are separate.
            side_is_buy=original_order_details.side_is_buy,
            price=original_order_details.price or 0.0,
            status="CANCELLED"
        )
        self.trade_confirmation_callback(confirmation)
        self._cleanup_order_maps(client_order_id, broker_ord_id)
        return True

    def _dispatch_rejection(self, client_order_id: str, symbol: str, side_is_buy: bool, reason: str):
        self.logger.warning(f"Dispatching REJECTION for {client_order_id} ({symbol}): {reason}")
        rejection_conf = TradeConfirmationMessage(
            order_id=-1, client_order_id=client_order_id, symbol=symbol,
            filled_quantity=0, side_is_buy=side_is_buy, price=0.0, status="REJECTED"
        )
        self.trade_confirmation_callback(rejection_conf)

    def _cleanup_order_maps(self, client_order_id: str, broker_order_id: int):
        with self._lock:
            if client_order_id in self.client_to_broker_id_map:
                del self.client_to_broker_id_map[client_order_id]
            if broker_order_id in self.broker_to_client_id_map:
                del self.broker_to_client_id_map[broker_order_id]
            if broker_order_id in self.broker_id_to_order_details:
                del self.broker_id_to_order_details[broker_order_id]
        self.logger.debug(f"Cleaned maps for order: client_id={client_order_id}, broker_id={broker_order_id}")

    def get_order_details(self, client_order_id: str) -> Optional[OrderDetails]:
         with self._lock:
            broker_id = self.client_to_broker_id_map.get(client_order_id)
            if broker_id:
                # Return a copy to prevent modification of internal state by caller
                details = self.broker_id_to_order_details.get(broker_id)
                if details:
                    return OrderDetails(**vars(details)) # Create a new instance
            return None

    def get_market_data_snapshot(self, symbol: str) -> Optional[Dict[str, Any]]:
        request_msg = {"command": "GET_BOOK_INFO", "symbol": symbol}
        response_json = self._send_request_to_ob(request_msg)

        if response_json and response_json.get("status") == "OK":
            return {
                "bids": response_json.get("bids", []),
                "asks": response_json.get("asks", [])
            }
        else:
            error_msg = response_json.get("message", "Failed to get market data") if response_json else "No response"
            self.logger.warning(f"Could not retrieve market data for {symbol}: {error_msg}")
            return None