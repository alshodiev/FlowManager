// cpp_order_book/src/level_info.cpp
#include "level_info.hpp"

OrderBookLevelInfos::OrderBookLevelInfos(const LevelInfos& bids, const LevelInfos& asks)
    : bids_{bids}, asks_{asks} {}

const LevelInfos& OrderBookLevelInfos::GetBids() const { return bids_; }
const LevelInfos& OrderBookLevelInfos::GetAsks() const { return asks_; }