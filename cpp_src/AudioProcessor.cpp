#include "AudioProcessor.h"
#include "pocketfft_hdronly.h"
#include <cmath>
#include <cstring>
#include <algorithm>
#include <iostream>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

using namespace pocketfft;

AudioProcessor::AudioProcessor(const std::string& model_path)
    : env_(ORT_LOGGING_LEVEL_WARNING, "GTCRN"),
      memory_info_(Ort::MemoryInfo::CreateCpu(OrtDeviceAllocator, OrtMemTypeCPU)) {
    
    // Initialize DSP buffers
    in_buffer_.resize(WINDOW_SIZE, 0.0f);
    out_buffer_.resize(WINDOW_SIZE, 0.0f);
    init_window();

    // Initialize ONNX Runtime Session
    Ort::SessionOptions session_options;
    session_options.SetIntraOpNumThreads(1);
    session_options.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);

#ifdef _WIN32
    // Convert string to wstring for Windows
    std::wstring w_model_path(model_path.begin(), model_path.end());
    session_ = std::make_unique<Ort::Session>(env_, w_model_path.c_str(), session_options);
#else
    session_ = std::make_unique<Ort::Session>(env_, model_path.c_str(), session_options);
#endif

    // Initialize state caches
    // conv_cache: (2, 1, 16, 16, 33) -> size 16896
    conv_cache_.resize(2 * 1 * 16 * 16 * 33, 0.0f);
    // tra_cache: (2, 3, 1, 1, 16) -> size 96
    tra_cache_.resize(2 * 3 * 1 * 1 * 16, 0.0f);
    // inter_cache: (2, 1, 33, 16) -> size 1056
    inter_cache_.resize(2 * 1 * 33 * 16, 0.0f);
}

AudioProcessor::~AudioProcessor() {}

void AudioProcessor::init_window() {
    window_.resize(WINDOW_SIZE);
    // torch.hann_window(N) uses periodic=True by default:
    // w[n] = 0.5 * (1 - cos(2*pi*n/N)), divisor is N, not N-1
    // This ensures w[n]^2 + w[n+N/2]^2 = 1 for 50% overlap (perfect reconstruction)
    for (int i = 0; i < WINDOW_SIZE; ++i) {
        float hann = 0.5f * (1.0f - std::cos(2.0f * M_PI * i / WINDOW_SIZE));
        window_[i] = std::sqrt(hann);
    }
}

void AudioProcessor::process_block(const float* input, float* output, float denoise_strength) {
    // 1. Shift in_buffer left by BLOCK_SIZE and copy new input
    std::memmove(in_buffer_.data(), in_buffer_.data() + BLOCK_SIZE, (WINDOW_SIZE - BLOCK_SIZE) * sizeof(float));
    std::memcpy(in_buffer_.data() + WINDOW_SIZE - BLOCK_SIZE, input, BLOCK_SIZE * sizeof(float));

    // If denoise_strength is 0, we can just bypass processing to save CPU
    // But to keep latency consistent, we still output from the buffer
    if (denoise_strength <= 0.0f) {
        std::memcpy(output, in_buffer_.data(), BLOCK_SIZE * sizeof(float));
        return;
    }

    // 2. Apply window and prepare for FFT
    std::vector<float> fft_in(WINDOW_SIZE);
    for (int i = 0; i < WINDOW_SIZE; ++i) {
        fft_in[i] = in_buffer_[i] * window_[i];
    }

    // 3. STFT (Real FFT)
    std::vector<std::complex<float>> fft_out(NUM_BINS);
    shape_t shape_in = {WINDOW_SIZE};
    shape_t axes = {0};
    stride_t stride_in = {sizeof(float)};
    stride_t stride_out = {sizeof(std::complex<float>)};
    
    r2c(shape_in, stride_in, stride_out, axes, pocketfft::FORWARD, fft_in.data(), fft_out.data(), 1.0f);

    // 4. Prepare ONNX Input (spec: [1, 257, 1, 2])
    std::vector<float> spec_tensor(1 * NUM_BINS * 1 * 2);
    for (int i = 0; i < NUM_BINS; ++i) {
        spec_tensor[i * 2 + 0] = fft_out[i].real();
        spec_tensor[i * 2 + 1] = fft_out[i].imag();
    }

    // Create Ort::Value for inputs
    std::vector<int64_t> spec_shape = {1, NUM_BINS, 1, 2};
    std::vector<int64_t> conv_shape = {2, 1, 16, 16, 33};
    std::vector<int64_t> tra_shape = {2, 3, 1, 1, 16};
    std::vector<int64_t> inter_shape = {2, 1, 33, 16};

    input_tensors_.clear();
    input_tensors_.push_back(Ort::Value::CreateTensor<float>(memory_info_, spec_tensor.data(), spec_tensor.size(), spec_shape.data(), spec_shape.size()));
    input_tensors_.push_back(Ort::Value::CreateTensor<float>(memory_info_, conv_cache_.data(), conv_cache_.size(), conv_shape.data(), conv_shape.size()));
    input_tensors_.push_back(Ort::Value::CreateTensor<float>(memory_info_, tra_cache_.data(), tra_cache_.size(), tra_shape.data(), tra_shape.size()));
    input_tensors_.push_back(Ort::Value::CreateTensor<float>(memory_info_, inter_cache_.data(), inter_cache_.size(), inter_shape.data(), inter_shape.size()));

    // 5. Run Inference
    output_tensors_ = session_->Run(Ort::RunOptions{nullptr}, input_names_.data(), input_tensors_.data(), input_tensors_.size(), output_names_.data(), output_names_.size());

    // 6. Update Caches
    const float* out_conv = output_tensors_[1].GetTensorMutableData<float>();
    std::memcpy(conv_cache_.data(), out_conv, conv_cache_.size() * sizeof(float));

    const float* out_tra = output_tensors_[2].GetTensorMutableData<float>();
    std::memcpy(tra_cache_.data(), out_tra, tra_cache_.size() * sizeof(float));

    const float* out_inter = output_tensors_[3].GetTensorMutableData<float>();
    std::memcpy(inter_cache_.data(), out_inter, inter_cache_.size() * sizeof(float));

    // 7. Extract Enhanced Spec and iSTFT
    const float* out_spec = output_tensors_[0].GetTensorMutableData<float>();
    std::vector<std::complex<float>> ifft_in(NUM_BINS);
    for (int i = 0; i < NUM_BINS; ++i) {
        ifft_in[i] = std::complex<float>(out_spec[i * 2 + 0], out_spec[i * 2 + 1]);
    }

    std::vector<float> ifft_out(WINDOW_SIZE);
    stride_t stride_in_c = {sizeof(std::complex<float>)};
    stride_t stride_out_r = {sizeof(float)};
    
    // pocketfft backward is unnormalized, we need to divide by WINDOW_SIZE
    c2r(shape_in, stride_in_c, stride_out_r, axes, pocketfft::BACKWARD, ifft_in.data(), ifft_out.data(), 1.0f / WINDOW_SIZE);

    // 8. Apply Window and Overlap-Add
    for (int i = 0; i < WINDOW_SIZE; ++i) {
        out_buffer_[i] += ifft_out[i] * window_[i];
    }

    // 9. Extract output and Dry/Wet Mix
    for (int i = 0; i < BLOCK_SIZE; ++i) {
        float dry = in_buffer_[i]; // This is the delayed dry signal (aligned with output)
        float wet = out_buffer_[i];
        output[i] = denoise_strength * wet + (1.0f - denoise_strength) * dry;
    }

    // 10. Shift out_buffer left and pad with zeros
    std::memmove(out_buffer_.data(), out_buffer_.data() + BLOCK_SIZE, (WINDOW_SIZE - BLOCK_SIZE) * sizeof(float));
    std::memset(out_buffer_.data() + WINDOW_SIZE - BLOCK_SIZE, 0, BLOCK_SIZE * sizeof(float));
}
