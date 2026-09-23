cmake_minimum_required(VERSION 3.16)
project(gem_garfield_macros CXX)

# Garfield++/ROOT are local builds not on the default search path -- point
# CMake at them explicitly rather than relying on ~/.bashrc (which no longer
# exports these, see README.md "実行環境").
#
# ~/local/garfield was originally built against ROOT 6.32.04 and could not be
# linked against the newer ~/local/root/6.40.04 (ABI mismatch: "undefined
# reference to ROOT::TGenericClassInfo::TGenericClassInfo(...)"). Rebuilt and
# reinstalled against 6.40.04 on 2026-09-22 (source at
# ~/.package_build/garfieldpp) so the project can use one ROOT version
# throughout; see README.md "実行環境" for the rebuild steps if this ever
# needs to be redone (e.g. after upgrading ROOT again).
#
# NOTE: on this machine, an inherited CMAKE_PREFIX_PATH environment variable
# and/or Garfield's own GarfieldConfig.cmake (which internally does
# find_dependency(ROOT ...)) can cause CMake to resolve ROOT_DIR to a stale
# path before this list() line's CMAKE_PREFIX_PATH is consulted. If a fresh
# `cmake ..` ever reports the wrong ROOT under "Found Vdt: ...", force it
# explicitly: `cmake -DROOT_DIR=$HOME/local/root/6.40.04/cmake ..`.
list(APPEND CMAKE_PREFIX_PATH "$ENV{HOME}/local/garfield" "$ENV{HOME}/local/root/6.40.04")
set(ROOT_DIR "$ENV{HOME}/local/root/6.40.04/cmake" CACHE PATH "" FORCE)

find_package(Garfield REQUIRED)
find_package(ROOT REQUIRED COMPONENTS Core RIO Tree Gui Geom Graf Graf3d Gpad Hist Matrix MathCore)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

function(add_gem_macro name)
    add_executable(${name} ${name}.cpp)
    # ${CMAKE_CURRENT_SOURCE_DIR} lets macros #include "model_info.hh"; the
    # ../include path is for vendored third-party headers (e.g.
    # include/third_party/nlohmann/json.hpp, used by model_info.hh).
    target_include_directories(${name} PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}
        ${CMAKE_CURRENT_SOURCE_DIR}/../include
    )
    target_link_libraries(${name} PRIVATE
        Garfield::Garfield
        ROOT::Core ROOT::RIO ROOT::Tree ROOT::Gui ROOT::Geom ROOT::Graf ROOT::Graf3d ROOT::Gpad ROOT::Hist ROOT::Matrix ROOT::MathCore
    )
endfunction()

add_gem_macro(view_gem_field)
add_gem_macro(export_field_samples)
add_gem_macro(gen_gas_table)
add_gem_macro(gem_avalanche)
add_gem_macro(view_gem_avalanche_cross_section)
add_gem_macro(probe_field)
add_gem_macro(export_avalanche_trajectories)
add_gem_macro(probe_gas_transport)
