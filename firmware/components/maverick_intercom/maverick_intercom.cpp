#include "maverick_intercom.h"
#include "esphome/core/log.h"
#include "esphome/core/helpers.h"
#include "esphome/components/json/json_util.h"
#include <algorithm>
#include <ctime>
#include <fcntl.h>
#include "lwip/sockets.h"
#include "lwip/tcp.h"

namespace esphome::maverick_intercom {
static const char *const TAG = "maverick_intercom";

void Intercom::setup() {
  this->tx_queue_ = xQueueCreate(5, sizeof(AudioFrame));
  this->rx_queue_ = xQueueCreate(5, sizeof(AudioFrame));
  if (!this->tx_queue_ || !this->rx_queue_) { this->mark_failed(); return; }
  this->source_->add_data_callback([this](const std::vector<uint8_t> &data) { this->capture_(data); });
}

void Intercom::dump_config() {
  ESP_LOGCONFIG(TAG, "Maverick experimental TLS intercom; 16 kHz mono, 20 ms frames");
  ESP_LOGCONFIG(TAG, "Relay port: %u; no automatic reconnection", this->port_);
}

void Intercom::start() {
  if (this->is_failed() || this->requested_ || this->worker_running_ || this->stopping_) return;
  // TLS verification requires a valid clock. Do not bypass verification while SNTP starts.
  if (std::time(nullptr) < 1700000000 || this->mic_->get_mute_state() || !this->audio_available_()) {
    ESP_LOGW(TAG, "Start refused: clock, mute, or audio ownership not ready");
    this->stopped_trigger_.trigger();
    return;
  }
  xQueueReset(this->tx_queue_);
  xQueueReset(this->rx_queue_);
  this->playback_offset_ = AUDIO_SIZE;
  this->capture_size_ = 0;
  this->tx_sequence_ = 0;
  this->tx_dropped_ = 0;
  this->rx_dropped_ = 0;
  this->requested_ = true;
  this->worker_running_ = true;
  if (xTaskCreate(task_entry_, "maverick_tls", 8192, this, 4, nullptr) != pdPASS) {
    this->worker_running_ = false;
    this->requested_ = false;
    this->stopped_trigger_.trigger();
    return;
  }
  ESP_LOGI(TAG, "Connecting; microphone remains stopped until both endpoints join");
}

void Intercom::stop() {
  this->requested_ = false;
  this->active_ = false;
  this->stopping_ = this->worker_running_ || this->microphone_started_;
}

void Intercom::loop() {
  if (this->requested_ && (this->mic_->get_mute_state() || !this->audio_available_())) {
    ESP_LOGI(TAG, "Audio ownership changed or device muted; ending call");
    this->stop();
  }
  if (this->active_ && !this->microphone_started_ && !this->stopping_) {
    this->speaker_->set_audio_stream_info(audio::AudioStreamInfo(16, 1, 16000));
    this->source_->start();
    this->microphone_started_ = true;
    ESP_LOGI(TAG, "Both endpoints joined; simultaneous capture and playback enabled");
  }
  if (!this->active_ && this->microphone_started_) {
    this->source_->stop();
    this->speaker_->stop();
    this->microphone_started_ = false;
    this->stopping_ = true;
  }
  if (this->worker_done_.exchange(false)) {
    this->requested_ = false;
    this->active_ = false;
    this->stopping_ = true;
  }
  // Restore Assist only after the microphone task has relinquished the hardware.
  if (this->stopping_ && !this->worker_running_ && !this->microphone_started_ && this->mic_->is_stopped() && this->speaker_->is_stopped()) {
    this->stopping_ = false;
    ESP_LOGI(TAG, "Session ended: tx dropped=%u, rx dropped=%u", this->tx_dropped_.load(), this->rx_dropped_.load());
    this->stopped_trigger_.trigger();
  }
  if (!this->active_) return;
  if (this->playback_offset_ == AUDIO_SIZE && xQueueReceive(this->rx_queue_, &this->playback_, 0) == pdTRUE)
    this->playback_offset_ = 0;
  if (this->playback_offset_ < AUDIO_SIZE) {
    // Preserve partial writes; never block ESPHome's main loop waiting for a speaker.
    this->playback_offset_ += this->speaker_->play(this->playback_.data + this->playback_offset_, AUDIO_SIZE - this->playback_offset_, 0);
  }
}

void Intercom::capture_(const std::vector<uint8_t> &data) {
  if (!this->active_ || !this->requested_ || this->mic_->get_mute_state()) return;
  size_t offset = 0;
  while (offset < data.size()) {
    size_t count = std::min(AUDIO_SIZE - this->capture_size_, data.size() - offset);
    std::memcpy(this->pending_capture_ + this->capture_size_, data.data() + offset, count);
    offset += count;
    this->capture_size_ += count;
    if (this->capture_size_ == AUDIO_SIZE) {
      AudioFrame frame;
      frame.sequence = this->tx_sequence_++;
      std::memcpy(frame.data, this->pending_capture_, AUDIO_SIZE);
      if (xQueueSend(this->tx_queue_, &frame, 0) != pdTRUE) this->tx_dropped_++;
      this->capture_size_ = 0;
    }
  }
}

bool Intercom::write_all_(esp_tls_t *tls, const uint8_t *data, size_t length) {
  uint32_t started = millis();
  size_t offset = 0;
  while (offset < length && this->requested_) {
    int n = esp_tls_conn_write(tls, data + offset, length - offset);
    if (n > 0) offset += n;
    else if (n != ESP_TLS_ERR_SSL_WANT_READ && n != ESP_TLS_ERR_SSL_WANT_WRITE) return false;
    if (millis() - started > 1000) return false;
    if (n <= 0) vTaskDelay(std::max<TickType_t>(1, pdMS_TO_TICKS(2)));
  }
  return offset == length;
}

bool Intercom::send_(esp_tls_t *tls, uint8_t kind, const uint8_t *data, uint16_t length, uint32_t sequence) {
  uint8_t header[HEADER_SIZE];
  encode_header(header, kind, length, sequence);
  return this->write_all_(tls, header, sizeof(header)) && this->write_all_(tls, data, length);
}

void Intercom::task_entry_(void *arg) {
  auto *self = static_cast<Intercom *>(arg);
  self->run_();
  self->active_ = false;
  self->worker_running_ = false;
  self->worker_done_ = true;
  vTaskDelete(nullptr);
}

void Intercom::run_() {
  esp_tls_t *tls = esp_tls_init();
  if (!tls) return;
  esp_tls_cfg_t cfg{};
  cfg.cacert_buf = reinterpret_cast<const unsigned char *>(this->ca_certificate_.c_str());
  cfg.cacert_bytes = this->ca_certificate_.size() + 1;
  cfg.timeout_ms = 5000;
  // Default hostname verification stays enabled; CA and hostname must both match.
  if (esp_tls_conn_new_sync(this->host_.c_str(), this->host_.size(), this->port_, &cfg, tls) != 1) {
    ESP_LOGW(TAG, "TLS connection failed; verify relay address, certificate, and device time");
    esp_tls_conn_destroy(tls);
    return;
  }
  // Switch the established transport to nonblocking I/O so receive cannot stall capture/send.
  int socket_fd = -1;
  esp_tls_get_conn_sockfd(tls, &socket_fd);
  if (socket_fd < 0 || fcntl(socket_fd, F_SETFL, fcntl(socket_fd, F_GETFL, 0) | O_NONBLOCK) < 0) {
    esp_tls_conn_destroy(tls);
    return;
  }
  int no_delay = 1;
  if (setsockopt(socket_fd, IPPROTO_TCP, TCP_NODELAY, &no_delay, sizeof(no_delay)) != 0) {
    esp_tls_conn_destroy(tls);
    return;
  }
  std::string hello = json::build_json([this](JsonObject root) {
    root["device_id"] = this->device_id_;
    root["token"] = this->token_;
  });
  if (!this->send_(tls, HELLO, reinterpret_cast<const uint8_t *>(hello.data()), hello.size())) {
    esp_tls_conn_destroy(tls);
    return;
  }
  uint8_t buffer[HEADER_SIZE + MAX_CONTROL_SIZE];
  size_t received = 0, needed = HEADER_SIZE;
  uint8_t kind = 0;
  uint16_t length = 0;
  uint32_t sequence = 0, last_rx = millis(), last_ping = millis(), joined = millis();
  uint32_t previous_sequence = 0;
  bool have_sequence = false;
  while (this->requested_) {
    AudioFrame frame;
    if (this->active_ && xQueueReceive(this->tx_queue_, &frame, 0) == pdTRUE) {
      if (!this->send_(tls, AUDIO, frame.data, AUDIO_SIZE, frame.sequence)) break;
    }
    int n = esp_tls_conn_read(tls, buffer + received, needed - received);
    if (n > 0) {
      received += n;
      if (received == needed) {
        if (needed == HEADER_SIZE) {
          if (!decode_header(buffer, kind, length, sequence)) break;
          needed += length;
        }
        if (received == needed) {
          last_rx = millis();
          if (kind == STATUS) {
            bool valid = json::parse_json(std::string(reinterpret_cast<char *>(buffer + HEADER_SIZE), length), [this](JsonObject root) {
              const char *state = root["state"] | "";
              if (std::strcmp(state, "active") == 0) { this->active_ = true; return true; }
              return std::strcmp(state, "waiting") == 0 && !this->active_;
            });
            if (!valid) break;
          } else if (kind == AUDIO && this->active_) {
            uint32_t delta = sequence - previous_sequence;
            if (have_sequence && (delta == 0 || delta >= 0x80000000)) break;
            if (have_sequence && delta > 1) this->rx_dropped_ += delta - 1;
            previous_sequence = sequence;
            have_sequence = true;
            frame.sequence = sequence;
            std::memcpy(frame.data, buffer + HEADER_SIZE, AUDIO_SIZE);
            if (xQueueSend(this->rx_queue_, &frame, 0) != pdTRUE) this->rx_dropped_++;
          } else if (kind != PONG) break;
          received = 0;
          needed = HEADER_SIZE;
        }
      }
    } else if (n != ESP_TLS_ERR_SSL_WANT_READ && n != ESP_TLS_ERR_SSL_WANT_WRITE) break;
    if (millis() - last_rx > 15000 || (!this->active_ && millis() - joined > 30000)) break;
    if (millis() - last_ping > 5000) {
      if (!this->send_(tls, PING, nullptr, 0)) break;
      last_ping = millis();
    }
    vTaskDelay(std::max<TickType_t>(1, pdMS_TO_TICKS(2)));
  }
  esp_tls_conn_destroy(tls);
}
}  // namespace esphome::maverick_intercom
