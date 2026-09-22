cmake_minimum_required(VERSION 3.16)
project(gem_garfield_macros CXX)

# Garfield++/ROOT are local builds not on the default search path -- point
# CMake at them explicitly rather than relying on ~/.bashrc (which no longer
# exports these, see README.md "実行環境").
#
# IMPORTANT: must use ROOT 6.32.04 (/sw/packages/root/6.32.04), not the
# newer ~/local/root/6.40.04 -- ~/local/garfield's prebuilt libGarfield.so
# was linked against 6.32.04's ROOT dictionary ABI (confirmed via its
# original CMakeCache.txt) and fails to link against 6.40.04 with
# "undefined reference to ROOT::TGenericClassInfo::TGenericClassInfo(...)"
# because that ABI changed between the two ROOT versions.
list(APPEND CMAKE_PREFIX_PATH "$ENV{HOME}/local/garfield" "/sw/packages/root/6.32.04")

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
