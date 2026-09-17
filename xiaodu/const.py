"""Constants for the XiaoDu integration.

设备品类、控制指令与属性取值均以小度 MCP 服务端的白名单为准，
详见 .comate/specs/xiaodu-mcp-capability-expansion/doc.md。
"""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "xiaodu"

PLATFORMS: list[str] = ["light", "cover", "climate", "fan", "switch", "sensor", "scene"]

DEFAULT_SCAN_INTERVAL = timedelta(seconds=10)
# 场景列表几乎不变，无需与设备同频轮询
SCENE_SCAN_INTERVAL = timedelta(minutes=5)
REQUEST_TIMEOUT = 20

# 控制下发后，本地乐观状态最多保留多久（等待云端状态追上）
POWER_STATE_PENDING_TIMEOUT = timedelta(seconds=30)
# 控制下发后的递进补刷间隔（秒）
POWER_STATE_REFRESH_DELAYS = (2.0, 5.0, 10.0, 13.0)

# 百度小度公共 MCP 接口
MCP_URL = "https://xiaodu.baidu.com/saiya/smarthome/mcp"

# 百度 OAuth2 授权码流程配置
# 集成侧不保存任何凭据：client_id / client_secret / scope 全部由中转服务注入，
# 使用者只需把下面的地址改成分享者部署的中转服务。
AUTH_PROXY_BASE = "https://xiaodu.baidu.com/saiya/smarthome"
PROXY_AUTHORIZE = f"{AUTH_PROXY_BASE}/oauthauthorize"
PROXY_TOKEN = f"{AUTH_PROXY_BASE}/oauthtoken"

# MCP 支持的 method（Service_Page_Mcp::$actionMapping）
METHOD_DEVICELIST = "DEVICELIST"
METHOD_DEVICECONTROL = "DEVICECONTROL"
METHOD_SCENELIST = "SCENELIST"
METHOD_TRIGGERSCENE = "TRIGGERSCENE"
CONTROL_NAMESPACE = "DuerOS.ConnectedHome.Control"

# DEVICECONTROL 允许的 header.name（Service_Conf_Mcp::$arrHeaderNameToIntent）
REQUEST_TURN_ON = "TurnOnRequest"
REQUEST_TURN_OFF = "TurnOffRequest"
REQUEST_SET_BRIGHTNESS = "SetBrightnessPercentageRequest"
REQUEST_SET_COLOR_TEMPERATURE = "SetColorTemperatureRequest"
REQUEST_SET_TEMPERATURE = "SetTemperatureRequest"
REQUEST_SET_MODE = "SetModeRequest"
REQUEST_SET_FAN_SPEED = "SetFanSpeedRequest"
REQUEST_SET_ANGLE = "SetAngleRequest"
REQUEST_TRIGGER_SCENE = "TriggerRequest"

# 色温：DEVICELIST 上报与 DEVICECONTROL 下发都是 0-100 百分比，
# 云端按 2700-6500K 折算（Service_Conf_Attribute::COLOR_TEMPERATURE_MIN/MAX_VALUE）
COLOR_TEMP_MIN_KELVIN = 2700
COLOR_TEMP_MAX_KELVIN = 6500

# applianceTypes -> HA 平台（优先级见 mapping.primary_platform）
LIGHT_TYPES = frozenset(
    {
        "LIGHT",
        "DOWNLIGHT",
        "SPOTLIGHT",
        "AMBIENT_LIGHT",
        "CEILING_LAMP",
        "FLOOR_LAMP",
        "LAMP",
        "LIGHT_PANEL",
        "DIMMING_DRIVER",
        # 彩灯：MCP 无 SetColorRequest，颜色控不了，但开关/亮度/色温可用
        "RGB",
        "RGBW",
        "RGBCW",
    }
)
COVER_TYPES = frozenset(
    {
        "CURTAIN",
        "CURTAIN_PANEL",
        "CURT_SIMP",
        "ROLLER_BLINDS",
        "VENETIAN_BLINDS",
        "VERTICAL_BLINDS",
        "SLIDING_WINDOW",
        "WINDOW_OPENER",
    }
)
CLIMATE_TYPES = frozenset(
    {
        "AIR_CONDITION",
        "NO_STATUS_AIR_CONDITION",
        "AIR_CONDITION_PANEL",
        "CABINET_TYPE_AIR_CONDITIONER",
    }
)
# 这些品类只有在声明 setTemperature 时才归 climate，否则归 switch，
# 避免出现没有任何可调项的空调卡片
CONDITIONAL_CLIMATE_TYPES = frozenset(
    {"FLOOR_HEATER", "WATER_HEATER", "HEATER", "YUBA"}
)
FAN_TYPES = frozenset({"FAN", "TOWER_FAN"})
SWITCH_TYPES = frozenset(
    {
        "SWITCH",
        "SWITCH_2",
        "SWITCH_3",
        "WALL_SWITCH",
        "SOCKET",
        "OUTLET",
        "PLUG",
        "PLUGIN",
        "SPEAKER",
        "AUDIO",
        # 加湿/净化类：MCP 无湿度指令，做成 humidifier 会有调不动的滑块，归 switch
        "AIR_PURIFIER",
        "HUMIDIFIER",
        "DEHUMIDIFIER",
        "AIR_FRESHER",
        "CLOTHES_RACK",
        "FISH_TANK",
    }
)
OUTLET_TYPES = frozenset({"SOCKET", "OUTLET", "PLUG", "PLUGIN"})

# 无线开关 / 场景面板 / 旋钮是「只上报事件」的输入设备，没有可下发的开关能力，
# 做成 switch 会得到一个点了没反应的实体，因此不归任何控制平台。
INPUT_ONLY_TYPES = frozenset({"BUTTON", "SCENE_PANEL", "KNOB"})

# cover 品类 -> HA CoverDeviceClass 取值
COVER_DEVICE_CLASSES = {
    "CURTAIN": "curtain",
    "CURTAIN_PANEL": "curtain",
    "CURT_SIMP": "curtain",
    "ROLLER_BLINDS": "shade",
    "VENETIAN_BLINDS": "blind",
    "VERTICAL_BLINDS": "blind",
    "SLIDING_WINDOW": "window",
    "WINDOW_OPENER": "window",
}

# 温湿度读数所属的传感器品类（空调等把 temperature 当目标温度，不在此列）
AMBIENT_SENSOR_TYPES = frozenset(
    {"SENSOR", "TEMPERATURE_HUMIDITY_SENSOR", "AIR_MONITOR"}
)

# 状态取值常量
ON_VALUES = frozenset({"ON", "TRUE", "1"})
OFF_VALUES = frozenset({"OFF", "FALSE", "0"})
UNREACHABLE_VALUES = frozenset({"UNREACHABLE", "OFFLINE"})
