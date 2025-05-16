// cpp_order_book/src/order_book.hpp
#ifndef ORDER_BOOK_HPP
#define ORDER_BOOK_HPP

#include "types.hpp"
#include "order.hpp"    // For OrderPointer, OrderPointers, Order, OrderModify
#include "trade.hpp"    // For Trade, Trades
#include "level_info.hpp" // For OrderBookLevelInfos

#include <map>
#include <list>
#include <vector>
#include <string>
#include <unordered_map>
#include <functional> // For std::greater
#include <utility>    // For std::pair

class OrderBook {
private:
    struct OrderEntry {
        OrderPointer order_{nullptr};
        OrderPointers::iterator location_;
    };

    std::map<Price, OrderPointers, std::greater<Price>> bids_;
    std::map<Price, OrderPointers> asks_;
    std::unordered_map<OrderId, OrderEntry> orders_map_; // Renamed from orders_ for clarity

    bool CanMatch(Side side, Price price) const;
    Trades MatchOrders();
    void CancelOrderInternal(OrderId orderId); // Helper for internal cancellation logic

public:
    OrderBook(); // Default constructor

    // AddOrder now returns a pair: the trades generated, and a pointer to the submitted order
    // (which might have been modified by fills, or indicates FAK status).
    // Returns nullptr for submitted_order_ptr if order was rejected due to pre-existing ID.
    std::pair<Trades, OrderPointer> AddOrder(OrderPointer order);
    
    bool CancelOrder(OrderId orderId); // Returns true if order was found and cancelled

    // ModifyOrder is not directly exposed to Python (PM does Cancel+Add).
    // If you need it later, uncomment and implement.
    // Trades ModifyOrder(OrderModify order_modification_details);

    std::size_t Size() const;
    OrderBookLevelInfos GetOrderInfos() const;
};

#endif // ORDER_BOOK_HPP