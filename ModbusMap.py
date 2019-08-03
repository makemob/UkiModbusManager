# Modbus map for UkiModbusManager
# See also http://github.com/makemob/Huhu

MB_MAP = {
    'MB_SCARAB_ID1' : 0,

	'MB_BRIDGE_CURRENT' : 100,
	'MB_BATT_VOLTAGE' : 101,
	'MB_MAX_BATT_VOLTAGE' : 102,
	'MB_MIN_BATT_VOLTAGE' : 103,
	'MB_BOARD_TEMPERATURE' : 104,

	'MB_POSITION_ENCODER_COUNTS': 117,

	'MB_MOTOR_SETPOINT' : 200,
	'MB_MOTOR_SPEED' : 201,
	'MB_MOTOR_ACCEL' : 202,
	'MB_CURRENT_LIMIT_INWARD' : 203,
	'MB_CURRENT_LIMIT_OUTWARD' : 204,
	'MB_EXTENSION_LIMIT_INWARD': 205,
	'MB_EXTENSION_LIMIT_OUTWARD': 206,
	'MB_POSITION_ENCODER_SCALING': 207,

	'MB_ESTOP' : 208,
	'MB_RESET_ESTOP' : 209,    # Write 0x5050 to reset emergency stop
	'MB_MOTOR_PWM_FREQ_MSW' : 210,
	'MB_MOTOR_PWM_FREQ_LSW' : 211,
	'MB_MOTOR_PWM_DUTY_MSW' : 212,
	'MB_MOTOR_PWM_DUTY_LSW' : 213,

	'MB_GOTO_POSITION': 218,
	'MB_GOTO_SPEED_SETPOINT': 219,
	'MB_FORCE_CALIBRATE_ENCODER': 220,  # write 0xA0A0 to force encoder to calibrate to zero in current position

	'MB_EXTENSION': 299,
    'MB_ESTOP_STATE': 300,
    'MB_CURRENT_TRIPS_INWARD': 301,
    'MB_CURRENT_TRIPS_OUTWARD': 302,
    'MB_INWARD_ENDSTOP_STATE': 303,
    'MB_OUTWARD_ENDSTOP_STATE': 304,
    'MB_INWARD_ENDSTOP_COUNT': 305,
    'MB_OUTWARD_ENDSTOP_COUNT': 306,
    'MB_VOLTAGE_TRIPS': 307,
    'MB_HEARTBEAT_EXPIRIES' : 308,
	'MB_EXTENSION_TRIPS_INWARD': 309,
	'MB_EXTENSION_TRIPS_OUTWARD': 310,
	'MB_ENCODER_FAIL_TRIPS': 311,

    'MB_HEARTBEAT_TIMEOUT' : 9008,  # seconds until heartbeat timer trips
	'MB_ENCODER_FAIL_TIMEOUT': 9009,  # Max milliseconds between encoder pulses before timeout

    'MAX_MODBUS_OFFSET' : 9010
}

MB_MAP_HUHU_VERSION = 0.5  # Matching Huhu firmware version
