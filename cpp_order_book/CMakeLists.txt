# cpp_order_book/CMakeLists.txt
cmake_minimum_required(VERSION 3.10)
project(OrderBookServer LANGUAGES CXX)

list(APPEND CMAKE_PREFIX_PATH "/usr/local")

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(ZeroMQ REQUIRED)

include_directories(${CMAKE_CURRENT_SOURCE_DIR}/include)

set(PROJECT_SOURCES
    src/level_info.cpp
    src/order.cpp
    src/trade.cpp
    src/order_book.cpp
    src/order_book_server.cpp
)

add_executable(order_book_server ${PROJECT_SOURCES})

target_link_libraries(order_book_server PRIVATE ZMQ::libzmq) 
target_include_directories(order_book_server PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)

enable_testing()
add_subdirectory(tests)

if(MSVC)
    target_compile_options(order_book_server PRIVATE /W4)
else()
    target_compile_options(order_book_server PRIVATE -Wall -Wextra -pedantic)
endif()

