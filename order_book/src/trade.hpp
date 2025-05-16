// cpp_order_book/src/trade.hpp
#ifndef TRADE_HPP
#define TRADE_HPP

#include "types.hpp" // For OrderId, Price, Quantity
#include <vector>

struct TradeInfo {
    OrderId orderId_;
    Price price_;
    Quantity tradedQuantity_; // Using the corrected name
};

class Trade {
public:
    Trade(const TradeInfo& bidTrade, const TradeInfo& askTrade);

    const TradeInfo& GetBidTrade() const;
    const TradeInfo& GetAskTrade() const;

private:
    TradeInfo bidTrade_;
    TradeInfo askTrade_;
};

using Trades = std::vector<Trade>;

#endif // TRADE_HPP