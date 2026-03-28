cmake_minimum_required(VERSION 3.14)
project(GTCRN_Stream_CPP)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

include(FetchContent)

# 1. PocketFFT (Single header) - download from the correct cpp branch
set(POCKETFFT_HEADER "${CMAKE_BINARY_DIR}/_deps/pocketfft/pocketfft_hdronly.h")
if(NOT EXISTS "${POCKETFFT_HEADER}")
    message(STATUS "Downloading pocketfft_hdronly.h...")
    file(DOWNLOAD
        "https://raw.githubusercontent.com/mreineck/pocketfft/cpp/pocketfft_hdronly.h"
        "${POCKETFFT_HEADER}"
    )
endif()
add_library(pocketfft INTERFACE)
target_include_directories(pocketfft INTERFACE "${CMAKE_BINARY_DIR}/_deps/pocketfft")

# 2. ONNX Runtime (Prebuilt binaries for Windows x64)
set(ORT_VERSION "1.17.1")
if(WIN32)
    set(ORT_URL "https://github.com/microsoft/onnxruntime/releases/download/v${ORT_VERSION}/onnxruntime-win-x64-${ORT_VERSION}.zip")
    FetchContent_Declare(
        onnxruntime
        URL ${ORT_URL}
        DOWNLOAD_EXTRACT_TIMESTAMP TRUE
    )
    FetchContent_MakeAvailable(onnxruntime)

    add_library(onnxruntime_lib SHARED IMPORTED)
    set_target_properties(onnxruntime_lib PROPERTIES
        IMPORTED_LOCATION "${onnxruntime_SOURCE_DIR}/lib/onnxruntime.dll"
        IMPORTED_IMPLIB "${onnxruntime_SOURCE_DIR}/lib/onnxruntime.lib"
        INTERFACE_INCLUDE_DIRECTORIES "${onnxruntime_SOURCE_DIR}/include"
    )
else()
    message(FATAL_ERROR "This CMakeLists.txt is currently configured for Windows x64. Please modify for other platforms.")
endif()

# 3. PortAudio
FetchContent_Declare(
    portaudio
    GIT_REPOSITORY https://github.com/PortAudio/portaudio.git
    GIT_TAG master
)
set(PA_BUILD_SHARED OFF CACHE BOOL "Build PortAudio as static" FORCE)
set(PA_BUILD_EXAMPLES OFF CACHE BOOL "Don't build PortAudio examples" FORCE)
set(PA_BUILD_TESTS OFF CACHE BOOL "Don't build PortAudio tests" FORCE)
FetchContent_MakeAvailable(portaudio)

# Check for the correct PortAudio target name
if(TARGET PortAudio)
    set(PORTAUDIO_TARGET PortAudio)
elseif(TARGET portaudio_static)
    set(PORTAUDIO_TARGET portaudio_static)
else()
    set(PORTAUDIO_TARGET portaudio)
endif()

# Source files
add_executable(gtcrn_realtime
    main.cpp
    AudioProcessor.cpp
    AudioProcessor.h
)

target_include_directories(gtcrn_realtime PRIVATE
    "${portaudio_SOURCE_DIR}/include"
    "${CMAKE_BINARY_DIR}/_deps/pocketfft"
    "${onnxruntime_SOURCE_DIR}/include"
)

target_link_libraries(gtcrn_realtime PRIVATE
    pocketfft
    onnxruntime_lib
    ${PORTAUDIO_TARGET}
)

# Copy DLLs and model to output directory
if(WIN32)
    # Copy ONNX Runtime DLL
    add_custom_command(TARGET gtcrn_realtime POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${onnxruntime_SOURCE_DIR}/lib/onnxruntime.dll"
        $<TARGET_FILE_DIR:gtcrn_realtime>
    )
    # Copy PortAudio DLL
    add_custom_command(TARGET gtcrn_realtime POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${portaudio_BINARY_DIR}/$<CONFIG>/portaudio.dll"
        $<TARGET_FILE_DIR:gtcrn_realtime>
    )
endif()

# Copy ONNX model to output directory
set(ONNX_MODEL_SRC "${CMAKE_SOURCE_DIR}/../onnx_models/gtcrn_simple.onnx")
if(EXISTS "${ONNX_MODEL_SRC}")
    add_custom_command(TARGET gtcrn_realtime POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${ONNX_MODEL_SRC}"
        $<TARGET_FILE_DIR:gtcrn_realtime>
    )
    message(STATUS "ONNX model will be copied to output directory.")
else()
    message(WARNING "ONNX model not found at ${ONNX_MODEL_SRC}. Run export_onnx.py first.")
endif()
