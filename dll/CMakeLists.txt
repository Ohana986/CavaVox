cmake_minimum_required(VERSION 3.13)
project(cavacore_wrapper)

# Export all symbols automatically (avoids modifying cavacore.h with dllexport)
set(CMAKE_WINDOWS_EXPORT_ALL_SYMBOLS ON)

# Try modern CONFIG mode first (Windows via vcpkg), fall back to variable mode (Fedora etc.)
find_package(FFTW3 CONFIG QUIET)
if(NOT FFTW3_FOUND)
    find_package(FFTW3 REQUIRED)
endif()

add_library(cavacore SHARED cavacore.c cavacore_helper.c)
target_include_directories(cavacore PRIVATE ${CMAKE_CURRENT_SOURCE_DIR} ${FFTW3_INCLUDE_DIRS})

if(TARGET FFTW3::fftw3)
    target_link_libraries(cavacore PRIVATE FFTW3::fftw3)
else()
    target_link_libraries(cavacore PRIVATE ${FFTW3_LIBRARIES})
endif()

add_custom_command(TARGET cavacore POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy $<TARGET_FILE:cavacore> ${CMAKE_SOURCE_DIR}/..
    COMMENT "Copying cavacore.dll to project root"
)
