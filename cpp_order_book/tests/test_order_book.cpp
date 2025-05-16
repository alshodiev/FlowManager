#include "gtest/gtest.h"
#include "order_book.hpp" // Your order book header
#include "order.hpp"      // For Order, OrderType, Side etc.
#include "types.hpp"

// Helper to create an order easily
OrderPointer make_order(OrderId id, Side side, Price price, Quantity qty, OrderType type = OrderType::GoodTillCancel) {
    return std::make_shared<Order>(type, id, side, price, qty);
}

TEST(OrderBookTest, InitiallyEmpty) {
    OrderBook ob;
    ASSERT_EQ(ob.Size(), 0);
    OrderBookLevelInfos infos = ob.GetOrderInfos();
    ASSERT_TRUE(infos.GetBids().empty());
    ASSERT_TRUE(infos.GetAsks().empty());
}

TEST(OrderBookTest, AddSingleBuyOrder) {
    OrderBook ob;
    auto [trades, order_ptr] = ob.AddOrder(make_order(1, Side::Buy, 100, 10));
    ASSERT_TRUE(trades.empty());
    ASSERT_NE(order_ptr, nullptr);
    ASSERT_EQ(ob.Size(), 1);

    OrderBookLevelInfos infos = ob.GetOrderInfos();
    ASSERT_EQ(infos.GetBids().size(), 1);
    ASSERT_EQ(infos.GetBids()[0].price_, 100);
    ASSERT_EQ(infos.GetBids()[0].quantity_, 10);
    ASSERT_TRUE(infos.GetAsks().empty());
}

TEST(OrderBookTest, AddSingleSellOrder) {
    OrderBook ob;
    ob.AddOrder(make_order(1, Side::Sell, 101, 5));
    ASSERT_EQ(ob.Size(), 1);

    OrderBookLevelInfos infos = ob.GetOrderInfos();
    ASSERT_TRUE(infos.GetBids().empty());
    ASSERT_EQ(infos.GetAsks().size(), 1);
    ASSERT_EQ(infos.GetAsks()[0].price_, 101);
    ASSERT_EQ(infos.GetAsks()[0].quantity_, 5);
}

TEST(OrderBookTest, SimpleMatchFull) {
    OrderBook ob;
    OrderPointer buy_order = make_order(1, Side::Buy, 100, 10);
    OrderPointer sell_order = make_order(2, Side::Sell, 100, 10);

    ob.AddOrder(buy_order);
    auto [trades, submitted_sell_order_ptr] = ob.AddOrder(sell_order);

    ASSERT_EQ(ob.Size(), 0); // Both orders should be filled and removed
    ASSERT_EQ(trades.size(), 1);
    
    const auto& trade = trades[0];
    ASSERT_EQ(trade.GetBidTrade().orderId_, 1);
    ASSERT_EQ(trade.GetBidTrade().price_, 100);
    ASSERT_EQ(trade.GetBidTrade().tradedQuantity_, 10);

    ASSERT_EQ(trade.GetAskTrade().orderId_, 2);
    ASSERT_EQ(trade.GetAskTrade().price_, 100);
    ASSERT_EQ(trade.GetAskTrade().tradedQuantity_, 10);

    ASSERT_TRUE(buy_order->IsFilled());
    ASSERT_TRUE(sell_order->IsFilled()); // Or submitted_sell_order_ptr->IsFilled()
}

TEST(OrderBookTest, MatchPartialBuyAggresses) {
    OrderBook ob;
    OrderPointer buy_order = make_order(1, Side::Buy, 100, 15);   // Buy 15
    OrderPointer sell_order = make_order(2, Side::Sell, 100, 10); // Sell 10 (resting)

    ob.AddOrder(sell_order); // Sell order is resting
    auto [trades, submitted_buy_order_ptr] = ob.AddOrder(buy_order); // Buy order aggresses

    ASSERT_EQ(ob.Size(), 1); // Buy order should remain with 5
    ASSERT_EQ(trades.size(), 1);

    const auto& trade = trades[0];
    ASSERT_EQ(trade.GetBidTrade().orderId_, 1); // Aggressor buy
    ASSERT_EQ(trade.GetBidTrade().tradedQuantity_, 10);
    ASSERT_EQ(trade.GetAskTrade().orderId_, 2); // Resting sell
    ASSERT_EQ(trade.GetAskTrade().tradedQuantity_, 10);
    
    ASSERT_FALSE(buy_order->IsFilled());
    ASSERT_EQ(buy_order->GetRemainingQuantity(), 5);
    ASSERT_TRUE(sell_order->IsFilled());

    OrderBookLevelInfos infos = ob.GetOrderInfos();
    ASSERT_EQ(infos.GetBids().size(), 1);
    ASSERT_EQ(infos.GetBids()[0].price_, 100);
    ASSERT_EQ(infos.GetBids()[0].quantity_, 5);
    ASSERT_TRUE(infos.GetAsks().empty());
}

TEST(OrderBookTest, MatchPartialSellAggresses) {
    OrderBook ob;
    OrderPointer buy_order = make_order(1, Side::Buy, 100, 10);    // Buy 10 (resting)
    OrderPointer sell_order = make_order(2, Side::Sell, 100, 15);  // Sell 15 (aggressing)

    ob.AddOrder(buy_order); // Buy order is resting
    auto [trades, submitted_sell_order_ptr] = ob.AddOrder(sell_order); // Sell order aggresses

    ASSERT_EQ(ob.Size(), 1); // Sell order should remain with 5
    ASSERT_EQ(trades.size(), 1);
    
    ASSERT_TRUE(buy_order->IsFilled());
    ASSERT_FALSE(sell_order->IsFilled());
    ASSERT_EQ(sell_order->GetRemainingQuantity(), 5);

    OrderBookLevelInfos infos = ob.GetOrderInfos();
    ASSERT_TRUE(infos.GetBids().empty());
    ASSERT_EQ(infos.GetAsks().size(), 1);
    ASSERT_EQ(infos.GetAsks()[0].price_, 100);
    ASSERT_EQ(infos.GetAsks()[0].quantity_, 5);
}


TEST(OrderBookTest, CancelOrder) {
    OrderBook ob;
    ob.AddOrder(make_order(1, Side::Buy, 100, 10));
    ob.AddOrder(make_order(2, Side::Buy, 99, 5));
    ASSERT_EQ(ob.Size(), 2);

    bool cancelled = ob.CancelOrder(1);
    ASSERT_TRUE(cancelled);
    ASSERT_EQ(ob.Size(), 1);

    OrderBookLevelInfos infos = ob.GetOrderInfos();
    ASSERT_EQ(infos.GetBids().size(), 1);
    ASSERT_EQ(infos.GetBids()[0].price_, 99); // Order 1 at 100 should be gone
    
    cancelled = ob.CancelOrder(999); // Non-existent order
    ASSERT_FALSE(cancelled);
    ASSERT_EQ(ob.Size(), 1);
}

TEST(OrderBookTest, FillAndKill_NoMatch_ShouldNotAdd) {
    OrderBook ob;
    auto [trades, order_ptr] = ob.AddOrder(make_order(1, Side::Buy, 100, 10, OrderType::FillAndKill));
    
    ASSERT_TRUE(trades.empty());
    ASSERT_NE(order_ptr, nullptr); // Order pointer is returned
    ASSERT_FALSE(order_ptr->IsFilled()); // Not filled
    ASSERT_EQ(ob.Size(), 0); // FAK that doesn't match isn't added
}

TEST(OrderBookTest, FillAndKill_PartialMatch_ShouldTradeAndRemoveRemainder) {
    OrderBook ob;
    ob.AddOrder(make_order(1, Side::Sell, 100, 5)); // Resting sell order of 5

    OrderPointer fak_buy = make_order(2, Side::Buy, 100, 10, OrderType::FillAndKill);
    auto [trades, submitted_fak_ptr] = ob.AddOrder(fak_buy);

    ASSERT_EQ(trades.size(), 1);
    ASSERT_EQ(trades[0].GetBidTrade().orderId_, 2); // FAK buy
    ASSERT_EQ(trades[0].GetBidTrade().tradedQuantity_, 5);
    ASSERT_EQ(trades[0].GetAskTrade().orderId_, 1); // Resting sell
    ASSERT_EQ(trades[0].GetAskTrade().tradedQuantity_, 5);

    ASSERT_NE(submitted_fak_ptr, nullptr);
    ASSERT_FALSE(submitted_fak_ptr->IsFilled()); // FAK filled 5 of 10
    ASSERT_EQ(submitted_fak_ptr->GetRemainingQuantity(), 5); // Remaining on FAK itself
    
    ASSERT_EQ(ob.Size(), 0); // Resting sell filled, FAK remainder cancelled
}

TEST(OrderBookTest, FillAndKill_FullMatch) {
    OrderBook ob;
    ob.AddOrder(make_order(1, Side::Sell, 100, 10)); // Resting sell order of 10

    OrderPointer fak_buy = make_order(2, Side::Buy, 100, 10, OrderType::FillAndKill);
    auto [trades, submitted_fak_ptr] = ob.AddOrder(fak_buy);

    ASSERT_EQ(trades.size(), 1);
    ASSERT_EQ(trades[0].GetBidTrade().tradedQuantity_, 10);
    
    ASSERT_NE(submitted_fak_ptr, nullptr);
    ASSERT_TRUE(submitted_fak_ptr->IsFilled());
    ASSERT_EQ(ob.Size(), 0);
}

// Add more tests:
// - Multiple orders at the same price level (time priority)
// - Orders crossing multiple price levels
// - Modifying orders (if you implement that logic)
// - Edge cases for quantities and prices (e.g., 0 quantity - though your types are uint)