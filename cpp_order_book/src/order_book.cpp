// cpp_order_book/src/order_book.cpp
#include "order_book.hpp"
#include <numeric>     // For std::accumulate (if used, simplified in current GetOrderInfos)
#include <algorithm>   // For std::min
#include <iostream>    // For std::cerr, std::cout logging

OrderBook::OrderBook() = default;

bool OrderBook::CanMatch(Side side, Price price) const {
    if (side == Side::Buy) {
        if (asks_.empty()) return false;
        const auto& [bestAskPrice, _] = *asks_.begin(); // C++17 structured binding
        return price >= bestAskPrice;
    } else { // Sell
        if (bids_.empty()) return false;
        const auto& [bestBidPrice, _] = *bids_.begin(); // C++17 structured binding
        return price <= bestBidPrice;
    }
}

Trades OrderBook::MatchOrders() {
    Trades trades;
    if (!orders_map_.empty()) trades.reserve(orders_map_.size()); // Heuristic

    while (true) {
        if (bids_.empty() || asks_.empty()) break;

        auto bidLevelIt = bids_.begin();
        auto askLevelIt = asks_.begin();

        Price bidPrice = bidLevelIt->first;
        OrderPointers& current_bids_at_level = bidLevelIt->second;
        Price askPrice = askLevelIt->first;
        OrderPointers& current_asks_at_level = askLevelIt->second;

        if (bidPrice < askPrice) break; // No cross

        while (!current_bids_at_level.empty() && !current_asks_at_level.empty()) {
            OrderPointer& bid_order = current_bids_at_level.front();
            OrderPointer& ask_order = current_asks_at_level.front();

            Quantity match_quantity = std::min(bid_order->GetRemainingQuantity(), ask_order->GetRemainingQuantity());
            
            bid_order->Fill(match_quantity);
            ask_order->Fill(match_quantity);

            // Using corrected TradeInfo with tradedQuantity
            trades.push_back(
                Trade{
                    TradeInfo{bid_order->GetOrderId(), bid_order->GetPrice(), match_quantity},
                    TradeInfo{ask_order->GetOrderId(), ask_order->GetPrice(), match_quantity}
                });
            
            if (bid_order->IsFilled()) {
                orders_map_.erase(bid_order->GetOrderId());
                current_bids_at_level.pop_front();
            }
            if (ask_order->IsFilled()) {
                orders_map_.erase(ask_order->GetOrderId());
                current_asks_at_level.pop_front();
            }
        }

        if (current_bids_at_level.empty()) bids_.erase(bidPrice);
        if (current_asks_at_level.empty()) asks_.erase(askPrice);
    }
    return trades;
}

void OrderBook::CancelOrderInternal(OrderId orderId) {
    const auto& entry = orders_map_.at(orderId); // Assumes orderId exists
    OrderPointer order_to_cancel = entry.order_; 

    if (order_to_cancel->GetSide() == Side::Sell) {
        auto& level_orders = asks_.at(order_to_cancel->GetPrice());
        level_orders.erase(entry.location_);
        if (level_orders.empty()) asks_.erase(order_to_cancel->GetPrice());
    } else { // Buy
        auto& level_orders = bids_.at(order_to_cancel->GetPrice());
        level_orders.erase(entry.location_);
        if (level_orders.empty()) bids_.erase(order_to_cancel->GetPrice());
    }
    orders_map_.erase(orderId);
}


std::pair<Trades, OrderPointer> OrderBook::AddOrder(OrderPointer order) {
    if (orders_map_.count(order->GetOrderId())) {
        std::cerr << "Error: Order ID " << order->GetOrderId() << " already exists." << std::endl;
        return {{}, nullptr}; // Empty trades, null order pointer (signals rejection)
    }

    // If FAK and cannot match immediately, don't add to book levels, return empty trades.
    // The returned 'order' pointer allows server to know it was a FAK that didn't match.
    if (order->GetOrderType() == OrderType::FillAndKill && !CanMatch(order->GetSide(), order->GetPrice())) {
        std::cout << "FAK Order " << order->GetOrderId() << " cannot match immediately, not added to book levels." << std::endl;
        return {{}, order}; 
    }

    OrderPointers::iterator it;
    if (order->GetSide() == Side::Buy) {
        auto& orders_at_price_level = bids_[order->GetPrice()];
        orders_at_price_level.push_back(order);
        it = std::prev(orders_at_price_level.end());
    } else { // Sell
        auto& orders_at_price_level = asks_[order->GetPrice()];
        orders_at_price_level.push_back(order);
        it = std::prev(orders_at_price_level.end());
    }
    orders_map_[order->GetOrderId()] = OrderEntry{order, it};
    
    Trades trades = MatchOrders();

    // If the added order was FAK and is not fully filled after matching, remove its remainder.
    if (order->GetOrderType() == OrderType::FillAndKill && !order->IsFilled()) {
        std::cout << "FAK Order " << order->GetOrderId() << " not fully filled after matching, removing remainder." << std::endl;
        if (orders_map_.count(order->GetOrderId())) { 
            CancelOrderInternal(order->GetOrderId());
        }
        // The 'order' pointer still reflects its state (e.g., partial fills).
        // The server will use this state to report back to Python.
    }
    return {trades, order}; // Return trades and the (potentially modified) order pointer
}

bool OrderBook::CancelOrder(OrderId orderId) {
    if (!orders_map_.count(orderId)) {
        std::cerr << "Warning: Attempt to cancel non-existent order ID " << orderId << std::endl;
        return false;
    }
    CancelOrderInternal(orderId);
    std::cout << "Order " << orderId << " cancelled." << std::endl;
    return true;
}

std::size_t OrderBook::Size() const {
    return orders_map_.size();
}

OrderBookLevelInfos OrderBook::GetOrderInfos() const {
    LevelInfos bidInfos, askInfos;
    bidInfos.reserve(bids_.size()); // Reserve based on number of price levels
    askInfos.reserve(asks_.size());

    auto create_level_info_from_orders = [](Price price, const OrderPointers& orders_at_level) {
        Quantity total_quantity_at_level = 0;
        for (const auto& order_ptr : orders_at_level) {
            total_quantity_at_level += order_ptr->GetRemainingQuantity();
        }
        return LevelInfo{price, total_quantity_at_level};
    };

    for (const auto& [price, orders_at_level] : bids_) {
        if (!orders_at_level.empty()) {
            bidInfos.push_back(create_level_info_from_orders(price, orders_at_level));
        }
    }
    for (const auto& [price, orders_at_level] : asks_) {
        if (!orders_at_level.empty()) {
            askInfos.push_back(create_level_info_from_orders(price, orders_at_level));
        }
    }
    return OrderBookLevelInfos{bidInfos, askInfos};
}