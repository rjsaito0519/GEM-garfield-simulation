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
find_package(ROOT REQUIRED COMPONENTS Core RIO Gui Geom Graf Graf3d Gpad Hist Matrix MathCore)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_executable(view_single_gem_field view_single_gem_field.cpp)
target_link_libraries(view_single_gem_field PRIVATE
    Garfield::Garfield
    ROOT::Core ROOT::RIO ROOT::Gui ROOT::Geom ROOT::Graf ROOT::Graf3d ROOT::Gpad ROOT::Hist ROOT::Matrix ROOT::MathCore
)

add_executable(export_field_samples export_field_samples.cpp)
target_link_libraries(export_field_samples PRIVATE
    Garfield::Garfield
    ROOT::Core ROOT::RIO ROOT::Gui ROOT::Geom ROOT::Graf ROOT::Graf3d ROOT::Gpad ROOT::Hist ROOT::Matrix ROOT::MathCore
)

add_executable(gen_gas_table gen_gas_table.cpp)
target_link_libraries(gen_gas_table PRIVATE
    Garfield::Garfield
    ROOT::Core ROOT::RIO ROOT::Gui ROOT::Geom ROOT::Graf ROOT::Graf3d ROOT::Gpad ROOT::Hist ROOT::Matrix ROOT::MathCore
)

add_executable(single_gem_avalanche single_gem_avalanche.cpp)
target_link_libraries(single_gem_avalanche PRIVATE
    Garfield::Garfield
    ROOT::Core ROOT::RIO ROOT::Gui ROOT::Geom ROOT::Graf ROOT::Graf3d ROOT::Gpad ROOT::Hist ROOT::Matrix ROOT::MathCore
)

add_executable(view_single_gem_avalanche_cross_section view_single_gem_avalanche_cross_section.cpp)
target_link_libraries(view_single_gem_avalanche_cross_section PRIVATE
    Garfield::Garfield
    ROOT::Core ROOT::RIO ROOT::Gui ROOT::Geom ROOT::Graf ROOT::Graf3d ROOT::Gpad ROOT::Hist ROOT::Matrix ROOT::MathCore
)
