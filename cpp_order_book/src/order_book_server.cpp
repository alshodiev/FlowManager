// cpp_order_book/src/order_book_server.cpp
#include "order_book.hpp" // Main order book logic
// types.hpp, order.hpp are included via order_book.hpp or directly if needed for parsing
// For example, to create an OrderPointer from JSON:
#include "order.hpp" // For std::make_shared<Order> and enums OrderType, Side

#include <iostream>
#include <string>
#include <vector>
#include <memory>    // For std::shared_ptr
#include <stdexcept> // For std::exception

#include <zmq.hpp>
#include <nlohmann/json.hpp> // Requires nlohmann/json.hpp in include path

using json = nlohmann::json;

int main() {
    OrderBook orderbook;
    zmq::context_t context(1);
    zmq::socket_t socket(context, zmq::socket_type::rep);
    std::string bind_address = "tcp://*:5555";
    
    try {
        socket.bind(bind_address);
    } catch (const zmq::error_t& e) {
        std::cerr << "ZMQ bind error: " << e.what() << std::endl;
        return 1;
    }
    std::cout << "C++ Order Book server started on " << bind_address << std::endl;

    while (true) {
        zmq::message_t request_msg;
        std::string req_str; // To store the string representation of the message

        try {
            auto recv_result = socket.recv(request_msg, zmq::recv_flags::none);
            if (!recv_result.has_value() || recv_result.value() == 0) {
                std::cerr << "Failed to receive ZMQ message or received empty message." << std::endl;
                if (recv_result.has_value() && recv_result.value() == 0) {
                     json err_res;
                     err_res["status"] = "ERROR";
                     err_res["message"] = "Received empty request from client.";
                     socket.send(zmq::buffer(err_res.dump()), zmq::send_flags::none);
                }
                continue;
            }
            req_str = request_msg.to_string(); // Convert to string for parsing
            if (req_str.empty()) {
                std::cerr << "Received an empty message string after ZMQ recv." << std::endl;
                json err_res;
                err_res["status"] = "ERROR";
                err_res["message"] = "Empty request string after ZMQ recv.";
                socket.send(zmq::buffer(err_res.dump()), zmq::send_flags::none);
                continue;
            }
        } catch (const zmq::error_t& e) {
            std::cerr << "ZMQ recv error: " << e.what() << std::endl;
            if (e.num() == ETERM) {
                std::cout << "ZMQ context terminated, exiting." << std::endl;
                break;
            }
            // Attempt to send an error if socket might still be usable
            json err_res;
            err_res["status"] = "ERROR";
            err_res["message"] = "ZMQ receive error on server: " + std::string(e.what());
            try { socket.send(zmq::buffer(err_res.dump()), zmq::send_flags::none); }
            catch (const zmq::error_t&) { /* ignore send error after recv error */ }
            continue; 
        }
        
        json req_json;
        try {
            req_json = json::parse(req_str);
        } catch (const json::parse_error& e) {
            std::cerr << "JSON parse error: " << e.what() << " on string: " << req_str << std::endl;
            json err_res;
            err_res["status"] = "ERROR";
            err_res["message"] = "Invalid JSON request: " + std::string(e.what());
            socket.send(zmq::buffer(err_res.dump()), zmq::send_flags::none);
            continue;
        }

        json res_json;
        std::string command = req_json.value("command", "");
         std::cout << "Received command: " << command 
                  << " (Client Order ID: " << req_json.value("client_order_id", "N/A") 
                  << ", Broker Order ID: ";
        if (req_json.contains("broker_order_id") && req_json["broker_order_id"].is_number()) {
            std::cout << req_json["broker_order_id"].get<OrderId>();
        } else {
            std::cout << "N/A";
        }
        std::cout << ")" << std::endl;


        try { 
            if (command == "ADD_ORDER") {
                // Validate required fields
                if (!(req_json.contains("side") && req_json.contains("price") && req_json.contains("quantity") &&
                      req_json.contains("broker_order_id") && req_json.contains("type") &&
                      req_json.contains("client_order_id"))) {
                    throw std::runtime_error("Missing one or more required fields for ADD_ORDER.");
                }

                Side side = (req_json.at("side").get<std::string>() == "Buy") ? Side::Buy : Side::Sell;
                Price price = req_json.at("price").get<Price>();
                Quantity quantity = req_json.at("quantity").get<Quantity>();
                OrderId broker_order_id = req_json.at("broker_order_id").get<OrderId>();
                OrderType orderType = (req_json.at("type").get<std::string>() == "GoodTillCancel") ? OrderType::GoodTillCancel : OrderType::FillAndKill;

                auto order_ptr = std::make_shared<Order>(orderType, broker_order_id, side, price, quantity);
                auto [trades, submitted_order_ptr] = orderbook.AddOrder(order_ptr);

                if (!submitted_order_ptr && trades.empty()) { // Early rejection (e.g. duplicate ID)
                    res_json["status"] = "ERROR";
                    res_json["message"] = "Order rejected by book (e.g., duplicate Order ID or invalid params).";
                    new_order_status_in_book = "REJECTED_BY_BOOK";
                } else {
                    res_json["status"] = "OK";
                    res_json["trades"] = json::array();

                    for (const auto& trade : trades) {
                        json bid_fill_info;
                        bid_fill_info["order_id_filled"] = trade.GetBidTrade().orderId_;
                        bid_fill_info["price"] = trade.GetBidTrade().price_;
                        bid_fill_info["traded_quantity"] = trade.GetBidTrade().tradedQuantity_;
                        bid_fill_info["side_of_original_order"] = "Buy";
                        res_json["trades"].push_back(bid_fill_info);

                        json ask_fill_info;
                        ask_fill_info["order_id_filled"] = trade.GetAskTrade().orderId_;
                        ask_fill_info["price"] = trade.GetAskTrade().price_;
                        ask_fill_info["traded_quantity"] = trade.GetAskTrade().tradedQuantity_;
                        ask_fill_info["side_of_original_order"] = "Sell";
                        res_json["trades"].push_back(ask_fill_info);
                    }
                    
                    std::string new_order_status_in_book = "UNKNOWN";
                    if (submitted_order_ptr) {
                        if (submitted_order_ptr->IsFilled()) {
                            new_order_status_in_book = "FILLED";
                        } else if (submitted_order_ptr->GetOrderType() == OrderType::FillAndKill) {
                            new_order_status_in_book = "REJECTED_BY_BOOK"; 
                        } else { 
                            new_order_status_in_book = "WORKING";
                        }
                    } else { 
                        new_order_status_in_book = "REJECTED_BY_BOOK"; // Should be covered by initial check
                    }
                    res_json["order_final_status_in_book"] = new_order_status_in_book;
                }
                // Echo back client and broker IDs regardless of outcome for easier debugging on client
                res_json["client_order_id"] = req_json.value("client_order_id", "N/A");
                res_json["broker_order_id"] = req_json.value("broker_order_id", 0);


            } else if (command == "CANCEL_ORDER") {
                 if (!req_json.contains("broker_order_id")) {
                    throw std::runtime_error("Missing 'broker_order_id' for CANCEL_ORDER.");
                }
                OrderId order_id_to_cancel = req_json.at("broker_order_id").get<OrderId>();
                bool success = orderbook.CancelOrder(order_id_to_cancel);
                if (success) {
                    res_json["status"] = "OK";
                    res_json["final_status"] = "CANCELLED";
                } else {
                    res_json["status"] = "ERROR";
                    res_json["message"] = "Cancel failed (e.g. order not found or already completed)";
                    res_json["final_status"] = "CANCEL_REJECTED"; 
                }
                res_json["broker_order_id"] = order_id_to_cancel; // Echo back

            } else if (command == "GET_BOOK_INFO") {
                OrderBookLevelInfos infos = orderbook.GetOrderInfos();
                res_json["status"] = "OK";
                res_json["bids"] = json::array();
                for (const auto& level : infos.GetBids()) {
                    res_json["bids"].push_back({{"price", level.price_}, {"quantity", level.quantity_}});
                }
                res_json["asks"] = json::array();
                for (const auto& level : infos.GetAsks()) {
                    res_json["asks"].push_back({{"price", level.price_}, {"quantity", level.quantity_}});
                }
            } else if (command == "PING") {
                res_json["status"] = "OK"; // PING should also have a status
                res_json["reply"] = "PONG";
            }
            else {
                res_json["status"] = "ERROR";
                res_json["message"] = "Unknown command: " + command;
            }
        } catch (const json::exception& e) { // Catch errors from req_json.at("key") or .get<T>()
            std::cerr << "JSON access/type error processing command '" << command << "': " << e.what() << std::endl;
            res_json["status"] = "ERROR";
            res_json["message"] = "Invalid or missing field in JSON request: " + std::string(e.what());
        } catch (const std::exception& e) { // Catch other standard exceptions (e.g. std::runtime_error)
            std::cerr << "Error processing command '" << command << "': " << e.what() << std::endl;
            res_json["status"] = "ERROR";
            res_json["message"] = std::string("Internal server error: ") + e.what();
        }

        try {
            std::string response_str = res_json.dump();
            std::cout << "Sending response: " << response_str << std::endl;
            socket.send(zmq::buffer(response_str), zmq::send_flags::none);
        } catch (const zmq::error_t& e) {
            std::cerr << "ZMQ send error: " << e.what() << std::endl;
        }
    }
    // Cleanup unreachable in current loop, but good practice
    socket.close();
    context.close(); 
    return 0;
}