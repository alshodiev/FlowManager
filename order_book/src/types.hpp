// cpp_order_book/src/types.hpp
#ifndef TYPES_HPP
#define TYPES_HPP

#include <cstdint>
#include <vector>
#include <list>
#include <memory>

// Forward declaration if Order class is defined elsewhere and OrderPointer is used widely
// class Order; // Not strictly needed here if order.hpp includes types.hpp

enum class OrderType {
    GoodTillCancel,
    FillAndKill
};

enum class Side {
    Buy,
    Sell
};

using Price = std::uint32_t;
using Quantity = std::uint32_t;
using OrderId = std::uint64_t;
// using OrderControl = std::uint64_t; // This was in your original code, uncomment if used

#endif // TYPES_HPP