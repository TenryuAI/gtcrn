#pragma once

#include <vector>
#include <complex>
#include <string>
#include <memory>
#include <onnxruntime_cxx_api.h>

struct SpeexResamplerState_;
typedef struct SpeexResamplerState_ SpeexResamplerState;

class AudioProcessor {
public:
    AudioProcessor(const std::string& model_path);
    ~AudioProcessor();

    // Process one block of audio (256 samples)
    // input and output should have size 256
    void process_block(const float* input, float* output, float denoise_strength);

private:
    // DSP parameters
    static constexpr int BLOCK_SIZE = 256;
    static constexpr int WINDOW_SIZE = 512;
    static constexpr int FFT_SIZE = 512;
    static constexpr int NUM_BINS = 257; // FFT_SIZE / 2 + 1

    // Buffers for Overlap-Add
    std::vector<float> in_buffer_;
    std::vector<float> out_buffer_;
    std::vector<float> window_;

    // ONNX Runtime
    Ort::Env env_;
    std::unique_ptr<Ort::Session> session_;
    Ort::MemoryInfo memory_info_;
    
    // Model state caches
    std::vector<float> conv_cache_;
    std::vector<float> tra_cache_;
    std::vector<float> inter_cache_;
    
    // Input/Output tensors
    std::vector<Ort::Value> input_tensors_;
    std::vector<Ort::Value> output_tensors_;
    
    // Names
    std::vector<const char*> input_names_ = {"mix", "conv_cache", "tra_cache", "inter_cache"};
    std::vector<const char*> output_names_ = {"enh", "conv_cache_out", "tra_cache_out", "inter_cache_out"};

    // Helper functions
    void init_window();
    void reset_caches();
};

class AudioProcessor48k {
public:
    static constexpr int IO_SAMPLE_RATE = 48000;
    static constexpr int MODEL_SAMPLE_RATE = 16000;
    static constexpr int IO_BLOCK_SIZE = 768;      // 48k * 16ms
    static constexpr int MODEL_BLOCK_SIZE = 256;   // 16k * 16ms

    explicit AudioProcessor48k(const std::string& model_path);
    ~AudioProcessor48k();

    // Process one 48kHz mono block of 768 samples.
    void process_block(const float* input_48k, float* output_48k, float denoise_strength);

private:
    AudioProcessor core_;
    SpeexResamplerState* input_resampler_;
    SpeexResamplerState* output_resampler_;
    std::vector<float> model_in_;
    std::vector<float> model_out_;
};
