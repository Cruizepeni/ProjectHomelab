





















from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from typing import Any

from .StatMonitorMotherboard import StatMonitorMotherboard


LOGGER = logging.getLogger(__name__)

CLIENT_ID = "StatMonitorFanController"
MIN_TEST_PERCENT = 30.0
SET_VERIFY_TIMEOUT_SECONDS = 4.0
VERIFY_POLL_SECONDS = 0.25
SET_OUTPUT_TOLERANCE = 1.5



FAN_CONTROLLER_COMMANDS = {
	"GetFanChannels": {
		"purpose": "Return all motherboard fan/control channels and current state.",
		"args": {},
		"mutates": False,
	},
	"GetFanStatus": {
		"purpose": "Return current fan state for one fan or all fans.",
		"args": {"fan_number": "optional 1-based fan number"},
		"mutates": False,
	},
	"SetFanSpeed": {
		"purpose": "Set one motherboard fan to a software-controlled percentage.",
		"args": {"fan_number": "1-based fan number", "percent": "30-100"},
		"mutates": True,
	},
	"SetFanDefault": {
		"purpose": "Place one owned fan at 100% failsafe; restart Windows to return firmware control.",
		"args": {"fan_number": "1-based fan number"},
		"mutates": True,
	},
	"RestoreOwnedFans": {
		"purpose": "Place every owned fan at 100% failsafe; restart Windows to return firmware control.",
		"args": {},
		"mutates": True,
	},
}


@dataclass
class FanChannel:
	fan_number: int
	index: int
	hardware: Any
	fan_sensor: Any | None
	control_sensor: Any
	control: Any
	hardware_name: str
	fan_name: str
	control_name: str
	control_identifier: str


@dataclass
class OwnedFan:
	channel: FanChannel
	session_id: int
	original_mode: str
	original_output_percent: float | None
	original_rpm: float | None
	target_percent: float
	failsafe_100: bool = False


class StatMonitorFanController:


	def __init__(self, motherboard: StatMonitorMotherboard):
		if not isinstance(motherboard, StatMonitorMotherboard):
			raise TypeError("motherboard must be a StatMonitorMotherboard instance")
		self.motherboard = motherboard
		self._owned: dict[int, OwnedFan] = {}
		self._running = False

	def start(self) -> None:
		if self._running:
			return
		self.motherboard.register_lhm_pre_close_handler(self._on_lhm_pre_close)
		self.motherboard.acquire_lhm_client(CLIENT_ID)
		self._running = True

	def stop(self) -> None:
		if not self._running:
			return

		try:
			failures = self._set_all_owned_failsafe()
			if failures:
				LOGGER.critical("Could not verify 100%% failsafe for: %s. Restart Windows immediately.", ", ".join(f"Fan #{number}" for number in failures))
		finally:
			self.motherboard.release_lhm_client(CLIENT_ID)
			self.motherboard.unregister_lhm_pre_close_handler(self._on_lhm_pre_close)
			self._owned.clear()
			self._running = False

	def is_running(self) -> bool:
		return self._running

	def handle_command(
		self,
		command: str,
		arguments: dict[str, Any] | None = None,
	) -> dict[str, Any]:





		if not isinstance(command, str) or command not in FAN_CONTROLLER_COMMANDS:
			return {
				"success": False,
				"error": "unknown_command",
				"command": command,
			}

		request = dict(arguments) if isinstance(arguments, dict) else {}

		try:
			if command == "GetFanChannels":
				fans = self.get_channels()
				return {
					"success": True,
					"command": command,
					"count": len(fans),
					"fans": fans,
				}

			if command == "GetFanStatus":
				fan_number = request.get("fan_number")
				fans = self.get_channels()
				if fan_number is None:
					return {
						"success": True,
						"command": command,
						"count": len(fans),
						"fans": fans,
					}
				number = self._validate_fan_number(fan_number)
				fan = next(
					(item for item in fans if item.get("fan_number") == number),
					None,
				)
				if fan is None:
					return {
						"success": False,
						"error": "fan_not_found",
						"command": command,
						"fan_number": number,
					}
				return {
					"success": True,
					"command": command,
					"fan": fan,
				}

			if command == "SetFanSpeed":
				if "fan_number" not in request:
					raise ValueError("fan_number is required")
				if "percent" not in request:
					raise ValueError("percent is required")
				result = self.set_fan_percent(
					self._validate_fan_number(request["fan_number"]),
					request["percent"],
				)
				verified = bool(result.get("set_verified"))
				return {
					"success": verified,
					"command": command,
					**({"error": "set_not_verified"} if not verified else {}),
					"fan": result,
				}

			if command == "SetFanDefault":
				if "fan_number" not in request:
					raise ValueError("fan_number is required")
				number = self._validate_fan_number(request["fan_number"])
				owned = self._owned.get(number)
				if owned is None:
					return {"success": False, "error": "fan_not_owned", "command": command, "fan_number": number}
				verified = self._apply_failsafe_100_locked(owned)
				return {
					"success": False,
					"error": "restart_required" if verified else "failsafe_not_verified",
					"command": command,
					"fan_number": number,
					"failsafe_100": verified,
					"restart_required": True,
					"message": "Reliable firmware fan control cannot be restored in this session. Restart Windows to return firmware control." if verified else "The 100% failsafe could not be verified. Restart Windows immediately.",
				}

			if command == "RestoreOwnedFans":
				owned = sorted(self._owned)
				failures = self._set_all_owned_failsafe()
				return {
					"success": not owned,
					"command": command,
					"owned": owned,
					"failsafe_percent": 100.0 if owned else None,
					"failsafe_verified": not failures,
					"failsafe_failures": failures,
					"restart_required": bool(owned),
					**({"error": "failsafe_not_verified" if failures else "restart_required"} if owned else {}),
				}

		except ValueError as error:
			return {
				"success": False,
				"error": "invalid_request",
				"command": command,
				"message": str(error),
			}
		except RuntimeError as error:
			return {
				"success": False,
				"error": "controller_unavailable",
				"command": command,
				"message": str(error),
			}
		except Exception as error:
			LOGGER.exception("FanController command failed: %s", command)
			return {
				"success": False,
				"error": "request_failed",
				"command": command,
				"message": str(error),
			}

	def get_channels(self) -> list[dict[str, Any]]:

		self._require_running()
		with self.motherboard.lhm_access() as (computer, hardware_roots):
			session_id = id(computer)
			channels = self._discover_channels(hardware_roots)
			result = []
			for fan_number in sorted(channels):
				channel = channels[fan_number]
				self._update_hardware(channel.hardware)
				state = self._read_channel(channel)
				owned = self._owned.get(fan_number)
				result.append({
					"fan_number": fan_number,
					"fan_index": channel.index,
					"hardware": channel.hardware_name,
					"fan_name": channel.fan_name,
					"control_name": channel.control_name,
					"control_identifier": channel.control_identifier,
					"rpm": state["rpm"],
					"output_percent": state["output_percent"],
					"control_mode": state["control_mode"],
					"software_value_percent": state["software_value_percent"],
					"owned": bool(owned and owned.session_id == session_id),
					"original_output_percent": (
						owned.original_output_percent
						if owned and owned.session_id == session_id
						else None
					),
					"target_percent": (
						owned.target_percent
						if owned and owned.session_id == session_id
						else None
					),
					"failsafe_100": bool(
						owned and owned.session_id == session_id and owned.failsafe_100
					),
				})
			return result

	def get_owned_controls(self) -> list[dict[str, Any]]:
		return [
			{
				"fan_number": fan_number,
				"control_identifier": owned.channel.control_identifier,
				"original_mode": owned.original_mode,
				"original_output_percent": owned.original_output_percent,
				"original_rpm": owned.original_rpm,
				"target_percent": owned.target_percent,
				"failsafe_100": owned.failsafe_100,
			}
			for fan_number, owned in sorted(self._owned.items())
		]

	def set_fan_percent(self, fan_number: int, percent: float) -> dict[str, Any]:

		self._require_running()
		fan_number = self._validate_fan_number(fan_number)
		percent_value = self._validate_percent(percent)

		with self.motherboard.lhm_access() as (computer, hardware_roots):
			session_id = id(computer)
			channel = self._get_channel(hardware_roots, fan_number)
			self._update_hardware(channel.hardware)
			before = self._read_channel(channel)

			owned = self._owned.get(fan_number)
			if owned is not None and owned.session_id != session_id:
				raise RuntimeError(
					f"Fan #{fan_number} ownership belongs to an older LHM session. "
					"Restart Windows before applying another override."
				)

			if owned is None:
				owned = OwnedFan(
					channel=channel,
					session_id=session_id,
					original_mode=before["control_mode"],
					original_output_percent=before["output_percent"],
					original_rpm=before["rpm"],
					target_percent=100.0,
				)
				self._owned[fan_number] = owned
				channel.control.SetSoftware(100.0)
				safe_verified, _ = self._wait_for_set_locked(channel, 100.0, timeout=SET_VERIFY_TIMEOUT_SECONDS)
				if not safe_verified:
					raise RuntimeError(f"Could not verify 100% failsafe while taking ownership of Fan #{fan_number}")
				owned.target_percent = percent_value
			else:
				owned.channel = channel
				owned.target_percent = percent_value
				owned.failsafe_100 = False

			try:
				channel.control.SetSoftware(float(percent_value))
				verified, state = self._wait_for_set_locked(
					channel,
					percent_value,
					timeout=SET_VERIFY_TIMEOUT_SECONDS,
				)
			except Exception:
				self._apply_failsafe_100_locked(owned)
				raise
			if not verified:
				self._apply_failsafe_100_locked(owned)

			return {
				"fan_number": fan_number,
				"control_identifier": channel.control_identifier,
				"target_percent": percent_value,
				"original_mode": owned.original_mode,
				"original_output_percent": owned.original_output_percent,
				"original_rpm": owned.original_rpm,
				"current_mode": state["control_mode"],
				"current_output_percent": state["output_percent"],
				"current_rpm": state["rpm"],
				"set_verified": verified,
				"failsafe_100": not verified,
				"owned": True,
			}

	def set_fan_default(self, fan_number: int) -> dict[str, Any]:

		self._require_running()
		fan_number = self._validate_fan_number(fan_number)
		owned = self._owned.get(fan_number)
		if owned is None:
			return {"fan_number": fan_number, "restore_attempted": False, "restore_verified": False, "reason": "not_owned"}
		verified = self._apply_failsafe_100_locked(owned)
		return {
			"fan_number": fan_number,
			"restore_attempted": False,
			"restore_verified": False,
			"reason": "restart_required" if verified else "failsafe_not_verified",
			"failsafe_100": verified,
			"owned": True,
			"message": "Fan ownership remains with StatMonitor until Windows restarts. The fan is held at 100% for safety." if verified else "The 100% failsafe could not be verified. Restart Windows immediately.",
		}

	def restore_all_owned(self) -> list[int]:

		return self._set_all_owned_failsafe()

	def _set_all_owned_failsafe(self) -> list[int]:
		failures = []
		for fan_number, owned in list(self._owned.items()):
			if not self._apply_failsafe_100_locked(owned):
				failures.append(fan_number)
		return failures




	def _on_lhm_pre_close(self, reason: str) -> None:

		if not self._owned:
			return

		LOGGER.warning(
			"Motherboard LHM is closing (%s); placing %d owned fan control(s) at 100%% failsafe. Restart Windows to return firmware control.",
			reason,
			len(self._owned),
		)

		failures = self._set_all_owned_failsafe()
		if failures:
			LOGGER.critical("Could not verify 100%% failsafe before LHM close for: %s. Restart Windows immediately.", ", ".join(f"Fan #{number}" for number in failures))
		self._owned.clear()





	def _discover_channels(self, hardware_roots: tuple[Any, ...]) -> dict[int, FanChannel]:
		fan_sensors: dict[tuple[str, int], tuple[Any, Any]] = {}
		control_sensors: dict[tuple[str, int], tuple[Any, Any, Any]] = {}

		for hardware in self._iter_hardware(hardware_roots):
			self._update_hardware(hardware)
			hardware_identifier = self._identifier(getattr(hardware, "Identifier", None))

			for sensor in self._sensors(hardware):
				sensor_type = self._enum_name(getattr(sensor, "SensorType", None))
				index = self._int_value(getattr(sensor, "Index", None))
				key = (hardware_identifier, index)

				if sensor_type == "Fan":
					fan_sensors[key] = (hardware, sensor)
				elif sensor_type == "Control":
					control = getattr(sensor, "Control", None)
					if control is not None:
						control_sensors[key] = (hardware, sensor, control)

		channels: dict[int, FanChannel] = {}
		for (hardware_identifier, index), (hardware, control_sensor, control) in control_sensors.items():
			fan_tuple = fan_sensors.get((hardware_identifier, index))
			fan_sensor = fan_tuple[1] if fan_tuple else None
			fan_number = index + 1
			channels[fan_number] = FanChannel(
				fan_number=fan_number,
				index=index,
				hardware=hardware,
				fan_sensor=fan_sensor,
				control_sensor=control_sensor,
				control=control,
				hardware_name=self._clean_text(getattr(hardware, "Name", None)) or "Unnamed",
				fan_name=(self._clean_text(getattr(fan_sensor, "Name", None)) or "") if fan_sensor is not None else "",
				control_name=self._clean_text(getattr(control_sensor, "Name", None)) or "",
				control_identifier=(
					self._identifier(getattr(control_sensor, "Identifier", None))
					or f"control/{index}"
				),
			)

		if not channels:
			raise RuntimeError("No controllable motherboard fan channels were exposed by LHM")
		return channels

	def _get_channel(self, hardware_roots: tuple[Any, ...], fan_number: int) -> FanChannel:
		channels = self._discover_channels(hardware_roots)
		channel = channels.get(fan_number)
		if channel is None:
			available = ", ".join(f"#{number}" for number in sorted(channels))
			raise ValueError(f"Fan #{fan_number} is unavailable. Available controls: {available}")
		return channel

	def _wait_for_set_locked(
		self,
		channel: FanChannel,
		target: float,
		timeout: float,
	) -> tuple[bool, dict[str, Any]]:
		deadline = time.monotonic() + timeout
		state = self._read_channel(channel)
		while time.monotonic() < deadline:
			self._update_hardware(channel.hardware)
			state = self._read_channel(channel)
			mode_ok = state["control_mode"].lower() == "software"
			software_value = state["software_value_percent"]
			output = software_value if software_value is not None else state["output_percent"]
			output_ok = output is not None and abs(output - target) <= SET_OUTPUT_TOLERANCE
			if mode_ok and output_ok:
				return True, state
			time.sleep(VERIFY_POLL_SECONDS)
		return False, state

	def _apply_failsafe_100_locked(self, owned: OwnedFan) -> bool:
		try:
			owned.channel.control.SetSoftware(100.0)
			owned.target_percent = 100.0
			verified, _ = self._wait_for_set_locked(
				owned.channel,
				100.0,
				timeout=SET_VERIFY_TIMEOUT_SECONDS,
			)
			owned.failsafe_100 = verified
			if not verified:
				LOGGER.critical(
					"CRITICAL: could not verify 100%% failsafe on Fan #%s. Restart Windows immediately.",
					owned.channel.fan_number,
				)
			return verified
		except Exception:
			owned.failsafe_100 = False
			LOGGER.exception(
				"CRITICAL: could not apply 100%% failsafe to Fan #%s. "
				"Restart Windows immediately to restore motherboard fan state.",
				owned.channel.fan_number,
			)
			return False

	def _lost_session_result(self, owned: OwnedFan) -> dict[str, Any]:
		return {
			"fan_number": owned.channel.fan_number,
			"restore_attempted": False,
			"restore_verified": False,
			"reason": "lhm_session_changed",
			"message": (
				"The motherboard LHM session changed after this fan was overridden. "
				"Restart Windows to guarantee restoration of motherboard fan defaults."
			),
		}

	@staticmethod
	def _iter_hardware(hardware_roots: tuple[Any, ...]):
		stack = list(hardware_roots)
		while stack:
			hardware = stack.pop(0)
			yield hardware
			try:
				stack.extend(list(hardware.SubHardware))
			except Exception:
				continue

	@staticmethod
	def _sensors(hardware: Any) -> list[Any]:
		try:
			return list(hardware.Sensors)
		except Exception:
			return []

	@staticmethod
	def _update_hardware(hardware: Any) -> None:
		hardware.Update()

	@staticmethod
	def _read_channel(channel: FanChannel) -> dict[str, Any]:
		rpm = None
		if channel.fan_sensor is not None:
			rpm = StatMonitorFanController._number(
				getattr(channel.fan_sensor, "Value", None),
				1,
			)
		return {
			"rpm": rpm,
			"output_percent": StatMonitorFanController._number(
				getattr(channel.control_sensor, "Value", None),
				1,
			),
			"control_mode": StatMonitorFanController._enum_name(
				getattr(channel.control, "ControlMode", None)
			),
			"software_value_percent": StatMonitorFanController._number(
				getattr(channel.control, "SoftwareValue", None),
				1,
			),
		}

	@staticmethod
	def _validate_fan_number(value: int) -> int:
		if isinstance(value, bool):
			raise ValueError("Fan number must be an integer")
		try:
			number = int(value)
		except (TypeError, ValueError) as error:
			raise ValueError("Fan number must be an integer") from error
		if number < 1:
			raise ValueError("Fan number must be 1 or greater")
		return number

	@staticmethod
	def _validate_percent(value: float) -> float:
		try:
			percent = float(value)
		except (TypeError, ValueError) as error:
			raise ValueError("Fan percentage must be numeric") from error
		if not math.isfinite(percent):
			raise ValueError("Fan percentage must be finite")
		if percent < MIN_TEST_PERCENT or percent > 100.0:
			raise ValueError(
				f"Fan percentage must be between {MIN_TEST_PERCENT:.0f} and 100 "
				"while the development safety floor is active"
			)
		return percent

	def _require_running(self) -> None:
		if not self._running:
			raise RuntimeError("StatMonitorFanController is not running")

	@staticmethod
	def _identifier(value: Any) -> str:
		if value is None:
			return ""
		try:
			return str(value.ToString())
		except Exception:
			return str(value)

	@staticmethod
	def _enum_name(value: Any) -> str:
		if value is None:
			return "Unknown"
		return str(value).split(".")[-1]

	@staticmethod
	def _clean_text(value: Any) -> str | None:
		if value is None:
			return None
		text = " ".join(str(value).split()).strip()
		return text or None

	@staticmethod
	def _int_value(value: Any) -> int:
		try:
			return int(value)
		except (TypeError, ValueError):
			return -1

	@staticmethod
	def _number(value: Any, digits: int) -> float | None:
		if value is None:
			return None
		try:
			result = float(value)
		except (TypeError, ValueError):
			return None
		if not math.isfinite(result):
			return None
		return round(result, digits)
