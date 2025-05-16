// cpp_order_book/src/order.cpp
#include "order.hpp"
#include <string> // For std::to_string

Order::Order(OrderType orderType, OrderId orderId, Side side, Price price, Quantity quantity)
    : orderType_{orderType}, orderId_{orderId}, side_{side}, price_{price},
      initialQuantity_{quantity}, remainingQuantity_{quantity} {}

OrderId Order::GetOrderId() const { return orderId_; }
Side Order::GetSide() const { return side_; }
Price Order::GetPrice() const { return price_; }
Quantity Order::GetInitialQuantity() const { return initialQuantity_; }
Quantity Order::GetRemainingQuantity() const { return remainingQuantity_; }
Quantity Order::GetFilledQuantity() const { return GetInitialQuantity() - GetRemainingQuantity(); }
OrderType Order::GetOrderType() const { return orderType_; }
bool Order::IsFilled() const { return GetRemainingQuantity() == 0; }

void Order::Fill(Quantity quantity) {
    if (quantity > GetRemainingQuantity()) {
        // Using std::to_string for broader compatibility than C++20 std::format
        throw std::logic_error("Order (" + std::to_string(GetOrderId()) +
                               ") cannot be filled for more than its remaining quantity.");
    }
    remainingQuantity_ -= quantity;
}

// --- OrderModify Implementation ---
OrderModify::OrderModify(OrderId orderId, Side side, Price price, Quantity quantity)
    : orderId_{orderId}, side_{side}, price_{price}, quantity_{quantity} {}

OrderId OrderModify::GetOrderId() const { return orderId_; }
Price OrderModify::GetPrice() const { return price_; }
Side OrderModify::GetSide() const { return side_; }
Quantity OrderModify::GetQuantity() const { return quantity_; }

OrderPointer OrderModify::ToOrderPointer(OrderType type) const {
    return std::make_shared<Order>(type, GetOrderId(), GetSide(), GetPrice(), GetQuantity());
}