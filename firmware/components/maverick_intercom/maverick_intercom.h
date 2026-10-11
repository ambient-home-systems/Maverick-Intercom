#pragma once

#include <atomic>
#include <functional>
#include <string>
#include "esphome/core/component.h"
#include "esphome/core/automation.h"
#include "esphome/components/microphone/microphone_source.h"
#include "esphome/components/speaker/speaker.h"
#include "esp_tls.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "wire.h"

namespace esphome::maverick_intercom {
struct AudioFrame { uint32_t sequence; uint8_t data[AUDIO_SIZE]; };

class Intercom : public Component {
 public:
  void setup() override;
  void loop() override;
  void dump_config() override;
  void on_shutdown() override { this->stop(); }
  void start();
  void stop();
  bool is_requested() const { return this->requested_; }
  bool is_active() const { return this->active_; }
  bool is_finished() const {
    return !this->requested_ && !this->worker_running_ && !this->worker_done_
      && !this->stopping_ && !this->microphone_started_;
  }
  uint32_t get_tx_dropped() const { return this->tx_dropped_; }
  uint32_t get_rx_dropped() const { return this->rx_dropped_; }
  void set_microphone_source(microphone::MicrophoneSource *source) { this->source_ = source; }
  void set_microphone(microphone::Microphone *mic) { this->mic_ = mic; }
  void set_speaker(speaker::Speaker *output) { this->speaker_ = output; }
  void set_host(const std::string &host) { this->host_ = host; }
  void set_port(uint16_t port) { this->port_ = port; }
  void set_device_id(const std::string &id) { this->device_id_ = id; }
  void set_token(const std::string &token) { this->token_ = token; }
  void set_ca_certificate(const std::string &pem) { this->ca_certificate_ = pem; }
  void set_audio_available(std::function<bool()> fn) { this->audio_available_ = std::move(fn); }
  Trigger<> *get_stopped_trigger() { return &this->stopped_trigger_; }

 protected:
  static void task_entry_(void *arg);
  void run_();
  bool write_all_(esp_tls_t *tls, const uint8_t *data, size_t length);
  bool send_(esp_tls_t *tls, uint8_t kind, const uint8_t *data, uint16_t length, uint32_t sequence = 0);
  void capture_(const std::vector<uint8_t> &data);
  microphone::MicrophoneSource *source_{nullptr};
  microphone::Microphone *mic_{nullptr};
  speaker::Speaker *speaker_{nullptr};
  std::string host_, device_id_, token_, ca_certificate_;
  uint16_t port_{8765};
  std::function<bool()> audio_available_;
  Trigger<> stopped_trigger_;
  QueueHandle_t tx_queue_{nullptr}, rx_queue_{nullptr};
  std::atomic<bool> requested_{false}, active_{false}, worker_running_{false}, worker_done_{false};
  std::atomic<uint32_t> tx_dropped_{0}, rx_dropped_{0};
  bool microphone_started_{false}, stopping_{false};
  uint8_t pending_capture_[AUDIO_SIZE]{};
  size_t capture_size_{0};
  uint32_t tx_sequence_{0};
  AudioFrame playback_{};
  size_t playback_offset_{AUDIO_SIZE};
};
}  // namespace esphome::maverick_intercom
