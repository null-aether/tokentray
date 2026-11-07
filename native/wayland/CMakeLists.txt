cmake_minimum_required(VERSION 3.25)
project(TokenTrayWayland LANGUAGES CXX)

if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
    message(FATAL_ERROR "TokenTray's optional Wayland backend requires Linux")
endif()
find_package(Qt6 6.11 REQUIRED COMPONENTS Core Gui Widgets)
find_package(LayerShellQt 6.6 REQUIRED)
find_package(KF6StatusNotifierItem REQUIRED)
find_package(PkgConfig REQUIRED)
pkg_check_modules(WaylandClient REQUIRED IMPORTED_TARGET wayland-client)

add_library(tokentray_wayland SHARED bridge.cpp)
target_compile_features(tokentray_wayland PRIVATE cxx_std_17)
target_link_libraries(tokentray_wayland PRIVATE
    Qt6::Core Qt6::Gui Qt6::Widgets LayerShellQt::Interface KF6::StatusNotifierItem PkgConfig::WaylandClient)
install(TARGETS tokentray_wayland LIBRARY DESTINATION tokentray_wayland)
