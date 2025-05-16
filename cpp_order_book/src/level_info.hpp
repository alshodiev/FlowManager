// cpp_order_book/src/level_info.hpp
#ifndef LEVEL_INFO_HPP
#define LEVEL_INFO_HPP

#include "types.hpp" // For Price, Quantity
#include <vector>

struct LevelInfo {
    Price price_;
    Quantity quantity_;
};

using LevelInfos = std::vector<LevelInfo>;

class OrderBookLevelInfos {
public:
    OrderBookLevelInfos(const LevelInfos& bids, const LevelInfos& asks);

    const LevelInfos& GetBids() const;
    const LevelInfos& GetAsks() const;

private:
    LevelInfos bids_;
    LevelInfos asks_;
};

#endif // LEVEL_INFO_HPP