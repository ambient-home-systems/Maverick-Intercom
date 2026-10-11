from pathlib import Path

from esphome import automation
import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import esp32, microphone, socket, speaker
from esphome.const import CONF_ID, CONF_MICROPHONE, CONF_SPEAKER
from esphome.core import CORE

DEPENDENCIES = ["esp32", "microphone", "speaker"]
AUTO_LOAD = ["audio", "json", "socket"]
namespace = cg.esphome_ns.namespace("maverick_intercom")
Intercom = namespace.class_("Intercom", cg.Component)

CONFIG_SCHEMA = cv.All(
    cv.Schema({
        cv.GenerateID(): cv.declare_id(Intercom),
        cv.Required(CONF_MICROPHONE): microphone.microphone_source_schema(),
        cv.Required(CONF_SPEAKER): cv.use_id(speaker.Speaker),
        cv.Required("host"): cv.All(cv.string_strict, cv.Length(min=1, max=253)),
        cv.Optional("port", default=8765): cv.port,
        cv.Required("device_id"): cv.All(cv.string_strict, cv.Length(min=1, max=64)),
        cv.Required("token"): cv.sensitive(cv.All(cv.string_strict, cv.Length(min=32, max=128))),
        cv.Required("ca_certificate"): cv.file_,
        cv.Required("audio_available"): cv.returning_lambda,
        cv.Optional("on_stopped"): automation.validate_automation(single=True),
    }).extend(cv.COMPONENT_SCHEMA),
    cv.only_on_esp32,
    socket.consume_sockets(1, "maverick_intercom"),
)

FINAL_VALIDATE_SCHEMA = cv.Schema({
    cv.Required(CONF_MICROPHONE): microphone.final_validate_microphone_source_schema("maverick_intercom", sample_rate=16000),
}, extra=cv.ALLOW_EXTRA)


async def to_code(config):
    if CORE.target_framework != "esp-idf":
        raise cv.Invalid("maverick_intercom requires ESP-IDF")
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    source = await microphone.microphone_source_to_code(config[CONF_MICROPHONE])
    raw = await cg.get_variable(config[CONF_MICROPHONE][CONF_MICROPHONE])
    output = await cg.get_variable(config[CONF_SPEAKER])
    cg.add(var.set_microphone_source(source))
    cg.add(var.set_microphone(raw))
    cg.add(var.set_speaker(output))
    for name in ("host", "port", "device_id", "token"):
        cg.add(getattr(var, "set_" + name)(config[name]))
    certificate = Path(CORE.relative_config_path(config["ca_certificate"])).read_text()
    if "-----BEGIN CERTIFICATE-----" not in certificate:
        raise cv.Invalid("ca_certificate must contain a PEM certificate")
    cg.add(var.set_ca_certificate(certificate))
    guard = await cg.process_lambda(config["audio_available"], [], return_type=cg.bool_)
    cg.add(var.set_audio_available(guard))
    if "on_stopped" in config:
        await automation.build_automation(var.get_stopped_trigger(), [], config["on_stopped"])
    esp32.include_builtin_idf_component("esp-tls")
