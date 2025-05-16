# FlowManager

## Overview

This project mainly comprises of two parts - `C++` Order Book and Python Position Manager. 
The Order Book is a high-performance, multi-threaded library responsible for maintaining the Limit Order Book for one or more symbols as well as 
match orders and update the market data.
The Position Manager is a service responsible for tracking current positions, receiving target positions from an event-based strategy, calculating deltas, and managing the lifecycle of orders sent to the C++ Order Book to achieve target positions.

## Flow

```
+---------------------+      (Strategy Signals)     +-----------------------+
| Strategy (Python)   | --------------------------> | Python Position Mgr   |
| (Out of Scope)      |                             | (PM)                  |
+---------------------+                             +-----------+-----------+
                                                                |
                                     (pybind11 C++ Function Calls)
                                     1. SubmitOrder(symbol, side, price, qty, client_id)
                                     2. CancelOrder(client_id / broker_id)
                                     3. GetMarketDataSnapshot()
                                                                |
                                                                v
+-----------------------------------------------------------+   | (pybind11 Callbacks)
| C++ Order Book Engine (Multi-threaded Library)            |<--+ 4. OnTradeConfirmation(TradeReport)
|                                                           |   | 5. OnMarketDataUpdate(Snapshot)
|   +-----------------+     +-------------------------+     |
|   | Order Processor | --> | Matching Engine (Thread) | --> |
|   | (Ingestion)     |     +-------------------------+     |
|   +-----------------+                 |                   |
|         ^                             |                   |
|         | (Internal Queues)           v                   |
|   +---------------------------------------------+         |
|   | Data Structures (Maps, Lists for Bids/Asks) |         |
|   +---------------------------------------------+         |
+-----------------------------------------------------------+
```

