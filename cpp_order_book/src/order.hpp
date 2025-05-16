// cpp_order_book/src/order.hpp
#ifndef ORDER_HPP
#define ORDER_HPP

#include "types.hpp" // For OrderType, OrderId, Side, Price, Quantity
#include <memory>    // For std::shared_ptr
#include <list>
#include <string>    // For std::string in exception
#include <stdexcept> // For std::logic_error
// #include <format> // C++20, replaced with std::to_string for broader compatibility

class Order {
public:
    Order(OrderType orderType, OrderId orderId, Side side, Price price, Quantity quantity);

    OrderId GetOrderId() const;
    Side GetSide() const;
    Price GetPrice() const;
    Quantity GetInitialQuantity() const;
    Quantity GetRemainingQuantity() const;
    Quantity GetFilledQuantity() const;
    OrderType GetOrderType() const;
    bool IsFilled() const;

    void Fill(Quantity quantity);

private:
    OrderType orderType_;
    OrderId orderId_;
    Side side_;
    Price price_;
    Quantity initialQuantity_;
    Quantity remainingQuantity_;
};

using OrderPointer = std::shared_ptr<Order>;
using OrderPointers = std::list<OrderPointer>;

class OrderModify {
public:
    OrderModify(OrderId orderId, Side side, Price price, Quantity quantity);

    OrderId GetOrderId() const;
    Price GetPrice() const;
    Side GetSide() const;
    Quantity GetQuantity() const;

    OrderPointer ToOrderPointer(OrderType type) const;

private:
    OrderId orderId_;
    Price price_;
    Side side_;
    Quantity quantity_;
};

#endif // ORDER_HPP