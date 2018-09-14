import datetime
import time

'''
##############################################################
CHANGE LOG:

- 9/14/2019: Version 1.0.1  Fixed a bunch of errors that I created while commenting version 1.0
- 9/13/2018: Version 1.0.  Added comments to explain the crazy logic.


##############################################################
This script is intended to replace the Auto Comfort features of a Haiku fan with Indigo, where it changes the speed of your
fan based on data from your home and your preferences.

The script is intended to be executed OFTEN.  Ideally, any change to the inputs to this script should execute the script,
which will then see if the result is a change to the fan speed.  The script will only execute a command to the fan if the 
new speed is different from the current speed.

Prerequisites:

1. Indigo
2. A Haiku fan, with the Haiku fan plugin installed and configured for the fan
3. Data to make decisions on the fan speed:

Required:
- a variable in your Indigo config that contains a boolean value for whether someone is home

For each fan / zone, you'll need (see the config before for further explanations):

INPUTS Required:
- a device in your Indigo setup for the weather (must contain a feelslike temperature) for your area.  Typically you would only have one of these devices, but will need to assign the same device to each fan/zone.

These INPUTS are needed for each fan/zone:
- a variable in your Indigo setup for the ideal temperature for that zone
- a device in your Indigo setup that contains a temperature sensor for the zone
- a device in your Indigo setup that contains a motion or presence value for the zone
- a device in your Indigo setup for your thermostat for the zone

OUTPUTS Required (each of these are required for each defined FanZone in the config):
- a variable in your Indigo setup for the target speed for the fan/one
- a variable in your Indigo setup for lock expiration time for that fan/zone
- a variable in your Indigo setup for last changed time for that fan/zone


It is recommended that you DISABLE the Smart Mode/Auto Comfort, Motion, Schedule, Sleep Mode features from your Haiku fan.  This script replaces all of that.
If you don't, this script will essentially fight your fan for control.

Recommended setup in Indigo:
	1. After you configure this script by updating the LoadConfig() function, you should create an action group to execute the script.  Run it to see that it's working properly.
	2. To trigger the script, I recommend the plugin called Group Change Listener.  Otherwise, you could create a schedule to execute the script every 5 or 10 minutes.  Remember, the script is intended to be run frequently.
		Make the trigger execute the action group, with a 2-3 second delay.  The delay will make it so that multiple occurrences of the trigger will be consolidated to one execution of the script.

	With the Group Change Listener, select all the variables and devices that are configured in the LoadConfig(), set the trigger to execute the action group that runs this script.

Troubleshooting the behavior:

Is your fan running faster or slower than you wanted?  First, make sure you have created a variable in Indigo for the script debug.  
Go to your Trigger (the group change listener event) and add your debug variable to the list of things that trigger the script.

Create a new action called "Run Auto Comfort w/ Debug" that sets the debug variable to true.  Then a second action that sets it to false, but with a 1 minute delay.

Executing this will run the script, in debug mode, then turn off debug mode.  You'll see the target speed for each fan, and the logic that contributed.  
Adjust your TempSteps appropriately.


##############################################################
How the logic works:

The script runs through rules and configurations to calculate a target speed.  If the target speed is different from the current fan speed,
the command is sent to the fan to change the speed of the fan.  It also logs to the Event log the rules that contributed to the target speed calculation.

The script does not log to the event log if no changes are made to the fan target speed, unless the debug flag is set.

Static rules that happen regardless of the zone temperature, season:
- If no one is home, the maximum speed (regardless of other configuration rules, temperatures, etc.) is 1.
- If the HVAC is running (heat or cool), the target speed is increased by 1 

Key variables:
	- Ideal temperature = The ideal temperature of the zone.  A static value read into this script by a variable
	- Temperature delta = The difference between the indoor temperature for the zone and the ideal temperature

##############################################################
Season / mode detection:

NOTE: It's not entirely about seasons.  Summer mode is the main mode for the script.  The script is designed to go into summer mode
any time it's a warm day and your house is trying to cool itself.  See more below.

If the thermostat (for the fan zone) has a cool setpoint above 0, and the heat setpoint is 0, the script goes into SUMMER MODE
If the thermostat (for the fan zone) has a heat setpoint above 0, and the cool setpoint is 0, the script goes into WINTER MODE
IF the thermostat (for the fan zone) has both a heat and cool setpoint above zero, it's in FALL/SPRING MODE

The script will go into WARM SUMMER DAY MODE if:
	- The "ideal temperature" for that zone is COOLER than the outside feelslike temp
	- The difference (Temperature Delta) between the current inside temperature of the zone and the ideal temperature is positive (warmer)

The script will go into COOL SUMMER DAY MODE if: 
	- The ideal temperature is WARMER than the outside temperature


##############################################################
In WINTER MODE:
	- The fan will not go above a speed of 1
	- The fan will turn on when the HVAC (heat) is turned on.  It will be off otherwise

IN WARM SUMMER DAY MODE:
	- If people are detected in the room, the target speed is increased by one.
	- If it's a bedroom fan, and the nighttime flags and config are set, the room is assumed to have people in it at nighttime

	- If it's deemed a "WARM SUMMER DAY", the TempSteps are used to determine a impact to the target speed based on the temperature delta for the zone

IN COOL SUMMER DAY MODE:
	- If it's deemed a "COOL SUMMER DAY", the 
		- The fan will not go above a speed of 1
		- room presence will not have an effect on the target speed
		- TempSteps are NOT used

In SPRING/FALL MODE:
	- The fan will not go above a speed of 1
	- The fan will turn on when the HVAC (heat) is turned on.  It will be off otherwise

'''

def LoadConfig(config):
	###################### BEGIN CONFIG #################

	# script debug mode.  Create a variable for this, or set it statically to True or False
	config.script_debug = indigo.variables[1757362760].getValue(bool)

	config.BEDTIME_HIGH_FEELSLIKE_TEMPERATURE = 70 # In the summer, a temperature above this while sleeping will raise the fan level
	config.BEDTIME_HIGH_HUMIDITY = 80 # In the summer, a humidity above this level while sleeping will raise the fan level
	config.NIGHTTIME_START_HOUR = 22 # 10pm starts nighttime hours
	config.NIGHTTIME_END_HOUR = 8 # 8am ends nighttime hours
	config.MINIMUM_CHANGE_FREQUENCY = 2 # the number of minutes that a change to a fan's speed will lock changes from this script

	# Whether or not someone is home at the house.  If no one is home, the script does not turn on the fan.
	config.someone_home = indigo.variables[1451030242].getValue(bool) # "someone_home"


	###################
	# Define each of your Fan Zones.  Copy this section for each fan you have.
	###################

	# First, create your fan object and give it the DevId of the device.  This should be the SenseMe plugin device ID. 
	sunroomFan = FanZone("Sunroom", 109543436)

	# A Indigo variable to hold the target speed that this script will set the fan speed to.  This is used to retain the value that the script set to, so that it can detect if that speed changed outside of the script (so that the script does not fight a manual change that happened from the remote or app)
	sunroomFan.target_speed_varId = 1844925823

	# a Indigo variable for the ideal temperature for the room/zone.  This is a important value, used to calculate the target speed for the fan.  I recommend using a thermostat setpoint to start.  You can make this more intricate by changing the ideal temperature with more sophisticated logic, and firing this script when that change happens.
	sunroomFan.ideal_temperature_varId = 206761205

	# a Indigo Sensor device that has a property of .SensorValue (like a multi sensor) that contains the temp for the zone/room
	sunroomFan.temperature_devId = 1346561783

	# a Indigo Sensor device that has a property of .onOffState (like a motion sensor) that contains the presence for the zone/room
	sunroomFan.presence_devId = 1276366371

	# The string name (case sensitive) for the thermostat for the zone.  The script will look for the deviceID matching the name.  I do this rather than take a devId directly in case the device changes, but the name is consistent (there's a bug with NEST plugin where this happens)
	sunroomFan.zone_thermostat_name = "Downstairs Thermostat"

	# The Indigo devId for a weather device.  Will look for the "feelslike" state.
	sunroomFan.weather_devId = 56720865

	# a Indigo VarId to hold the locked state for this fan zone.
	sunroomFan.locked_varId = 975280043

	# a Indigo VarId to hold the timestamp that the script last changed the fanzone
	sunroomFan.lastchanged_varId = 1896531099

	# Set the outside temperature that the fan will always remain on a minimum level speed (1)
	sunroomFan.always_on_outside_temp = 86

	# Set the inside temperature that the fan will always remain on a minimum level speed (1)
	sunroomFan.always_on_inside_temp = 86

	# Configure the temperature steps.  Each step is processed sequentially until one is matched.  It's recommended to make them chronological and sequential, where the max_temp for the previous is the min_temp for the next... see example.
	# Constructor for the object:
	#		min_temp = The beginning of the range for that step.  You can use None to indicate no floor.
	#		max_temp = The end of the range for that step.  You can use None to indicate no ceiling.
	#		impact = The impact if the current temperature of the room is within the min and max.
	#		min_target (optional) = The minimum target if room is within the min and max.  If the target speed is lower than the minimum, then it will be adjusted.
	#		max_target (optional) = Same as above, but setting the max target speed

	# examples:
	# TempStep(None, -0.5, None, None, 1) = If the temperature delta (see dictionary) of the room is between 0 and -.5 degrees colder (F) of the ideal temperature, do not set a target, set the maximum speed of the fan to 1 (other factors cannot raise the target speed above 1)
	# TempStep(3.5, 4.5, 2, None, None) = If the temperature delta (see dictionary) of the room is between 3.5 and 4.5 degrees warmer (f) from the ideal temperature, increase the target speed of the fan by two.

	sunroomFan.temp_steps = [
		TempStep(None, -0.5, None, None, 1),
		TempStep(-0.5, 1.0, 1, None, None),
		TempStep(1.0, 2.5, 1, None, None),
		TempStep(2.5, 3.5, 1, None, None),
		TempStep(3.5, 4.5, 2, None, None),
		TempStep(4.5, 6.0, 3, None, None),
		TempStep(6.0, 7.0, 4, None, None),
		TempStep(7.0, None, 5, None, None)
	]

	# These are optional for each zone

	# The For use with the Group Change Listener plugin.  This variable holds the text of what device or variable changed, which causes the running of this script.  For use in the output log
	sunroomFan.current_event_varId = 1083180693

	# Set a static maximum speed at bedtime
	sunroomFan.bedtimeMaxSpeed = 0

	# Setting this to true will make the lock disable when presence is no longer detected in the room
	sunroomFan.reset_lock_when_no_presence = True

	# Enable Woosh mode when the fan is above a level 2 and when presence is detected.  Note: Woosh mode disables the external lock detection, since it is impossible to tell if the fan was changed outside of the script (woosh mode changes the speed within the fan itself, no way to understand if it came from the remote, app, etc.)
	sunroomFan.enable_woosh_mode_when_present = True

	# devId of the sensor with the humidity value for the fan/zone
	sunroomFan.humidity_devId = 155284095

	############## END FAN ZONE

	# MBR Fan -- Required items
	MBRFan = FanZone("MBR", 1728133585)
	MBRFan.target_speed_varId = 425166341
	MBRFan.ideal_temperature_varId = 1830715289
	MBRFan.temperature_devId = 180918713
	MBRFan.presence_devId = 458359032
	MBRFan.zone_thermostat_name = "Upstairs Thermostat"
	MBRFan.weather_devId = 56720865
	MBRFan.current_event_varId = 874147138
	MBRFan.locked_varId = 1160436796
	MBRFan.lastchanged_varId = 315118607
	MBRFan.always_on_outside_temp = 84
	MBRFan.always_on_inside_temp = 83

	MBRFan.temp_steps = [
		TempStep(None, -1.0, None, None, 1),
		TempStep(-1.0, 1.0, 1, None, None),
		TempStep(1.0, 2.5, 1, None, None),
		TempStep(2.5, 3.5, 1, None, None),
		TempStep(3.5, 4.5, 2, 1, None),
		TempStep(4.5, 6.0, 3, 2, None),
		TempStep(6.0, 7.0, 4, 3, None),
		TempStep(7.0, None, 5, 4, None)
	]

	# use the isNighttime() to adjust the TempSteps for nighttime.
	if config.isNighttime():
		MBRFan.temp_steps = [
			TempStep(None, -1.0, None, None, 1),
			TempStep(-1.0, 1.0, 1, None, None),
			TempStep(1.0, 2.5, 2, None, None),
			TempStep(2.5, 3.5, 2, None, None),
			TempStep(3.5, 4.5, 3, 2, None),
			TempStep(4.5, 6.0, 4, 2, None),
			TempStep(6.0, 7.0, 5, 4, None),
			TempStep(7.0, None, 6, 4, None)
		]

	# MBR Fan -- Optional items
	MBRFan.summer_fan_at_bedtime = True
	MBRFan.enable_woosh_mode_when_present = False
	MBRFan.humidity_devId = 218110438

	# For each fan zone that you created, add it to the array here to be returned.  You are all done.
	return [sunroomFan, MBRFan]

###################### END CONFIG #################
class AutoConfortConfig(object):
	def __init__(self):
		pass

	def isNighttime(self):
		return (not (datetime.datetime.now().time() >= datetime.time(self.NIGHTTIME_END_HOUR,00) and datetime.datetime.now().time() <= datetime.time(self.NIGHTTIME_START_HOUR,00)))

class TempStep(object):
	def __init__(self, min_temp, max_temp, impact, min_target = None, max_target = None):
		self.min_temp = min_temp
		self.max_temp = max_temp
		self.impact = impact
		self.min_target = min_target
		self.max_target = max_target

class FanZone(object):
	def __init__(self, zoneName, fanId):
		self.zoneName = zoneName
		self.min_target = 0
		self.max_target = 7
		self.debug = False
		self.fanId = fanId
		self.fanDev = indigo.devices[fanId]
		self.bedtimeMaxSpeed = None
		self.summer_fan_at_bedtime = False
		self.reset_lock_when_no_presence = False
		self.enable_woosh_mode_when_present = False
		self.humidity_devId = -1
		self.always_on_outside_temp = 88
		self.always_on_inside_temp = 88
		self.locktime = 60  # in minutes, default value
		self.zone_thermostat_id = None
		self.zone_thermostat_name = None

	def getMinTarget(self):
		if self.getCurrentRoomTemperature() > self.always_on_inside_temp and self.min_target < 1:
			self.min_target = 1

		if self.getFeelsLikeTemp() > self.always_on_outside_temp and self.min_target < 1:
			self.min_target = 1

		if config.someone_home and config.isNighttime() and self.getFeelsLikeTemp() > 69:
			self.min_target = 3

		if config.someone_home and not config.isNighttime() and self.getFeelsLikeTemp() > 80:
			self.min_target = 3

		return self.min_target

	def getMaxTarget(self):
		if config.isNighttime():
			return self.getBedtimeMaxSpeed()

		if self.getMinTarget() > self.max_target:
			return self.getMinTarget()

		return self.max_target

	def getIdealTemperature(self):
		try:
			return float(indigo.variables[self.ideal_temperature_varId].value)
		except:
			indigo.server.log(fan.zoneName + " fan script: could not determine the ideal temperature")
			return -1.0

	def getCurrentRoomTemperature(self):
		try:
			return float(indigo.devices[self.temperature_devId].sensorValue)
		except:
			indigo.server.log(fan.zoneName + " fan script: could not determine the current room temperature")
			return -1.0

	def getCoolSetpoint(self):
		try:
			return indigo.devices[self.zone_thermostat_id].coolSetpoint
		except:
			if self.findThermostat():
				return indigo.devices[self.zone_thermostat_id].coolSetpoint

			return None

	def getHeatSetpoint(self):
		try:
			return indigo.devices[self.zone_thermostat_id].heatSetpoint
		except:
			if self.findThermostat():
				return indigo.devices[self.zone_thermostat_id].heatSetpoint

			return None

	def getSummerAtBedtime(self):
		if self.config.isNighttime() and self.summer_fan_at_bedtime:
			return True

		return False

	def getPresence(self):
		if self.getSummerAtBedtime():
			return True

		try:
			if "onOffState" in indigo.devices[self.presence_devId].states:
				return bool(indigo.devices[self.presence_devId].states["onOffState"])
			else:
				return (indigo.devices[presence_devId].onOffState)
		except:
			indigo.server.log(fan.zoneName + " fan script: could not determine the local presence")
			return False

	def HVAC_Running(self):
		if self.zone_thermostat_id is None:
			if not self.findThermostat():
				return
			
		try:
			return indigo.devices[self.zone_thermostat_id].states["hvac_state"] == "cooling" or indigo.devices[self.zone_thermostat_id].states["hvac_state"] == "heating"
		except Exception as e:
			indigo.server.log(fan.zoneName + " fan script: could not determine the HVAC status.  error: " + str(e))
			return False

	def getFeelsLikeTemp(self):
		try:
			return indigo.devices[self.weather_devId].states["feelslike"]
		except:
			indigo.server.log(fan.zoneName + " fan script: could not determine the feels like temp")
			return -1

	def findThermostat(self):
		if self.zone_thermostat_name is None or len(self.zone_thermostat_name) == 0:
			indigo.server.log(fan.zoneName + " fan script: no thermostat name is set")
			return False

		for dev in indigo.devices:
			if dev.name.lower() == self.zone_thermostat_name.lower():
				self.zone_thermostat_id = dev.id
				return True

		indigo.server.log(fan.zoneName + " fan script: could not find the thermostat")
		return False

	def getEventChanged(self):
		try:
			return str(indigo.variables[self.current_event_varId].value)
		except:
#			indigo.server.log(fan.zoneName + " fan script: could not determine the event changed")
			return "unknown event"

	def isIdealTempIsCoolerThanOutside(self):
		return self.getIdealTemperature() < self.getFeelsLikeTemp()

	def getTemperatureDelta(self):
		return self.getCurrentRoomTemperature() - self.getIdealTemperature()

	def getCurrentSpeed(self):
		if "off" in self.fanDev.states["statusString"]:
			return 0

		try:
			return int(self.fanDev.states["speed"])
		except:
			indigo.server.log(fan.zoneName + " fan script: could not determine the current fan speed")
			return 0

	def wooshMode(self):
		try:
			if isinstance(self.fanDev.states["whoosh"], basestring):
				return self.fanDev.states["whoosh"].lower() == "on" # State "whoosh" of "Sunroom Ceiling Fan"
			elif isinstance(self.fanDev.states["whoosh"], bool):
				return bool(self.fanDev.states["whoosh"])
		except:
			indigo.server.log(fan.zoneName + " fan script: could not determine the woosh mode")
			return False

	def getBedtimeMaxSpeed(self):
		if self.bedtimeMaxSpeed is not None:
			return self.bedtimeMaxSpeed
		else:
			return self.max_target

	def isLocked(self):
		if self.reset_lock_when_no_presence and not self.getPresence():
			return False

		return self.isLockedTime() > datetime.datetime.now()

		try:
			pass
		except Exception as e:
			indigo.server.log(self.zoneName + " fan script: could not determine the fan lock status.  error: " + str(e))
			indigo.variable.updateValue(self.locked_varId, value=unicode((datetime.datetime.now() - datetime.timedelta(minutes = self.locktime)).strftime("%Y-%m-%d %H:%M:%S")))
			return False

	def isLockedTime(self):
		date1 = datetime.datetime.strptime(indigo.variables[self.locked_varId].value, "%Y-%m-%d %H:%M:%S")
		date2 = datetime.datetime.strptime(indigo.variables[self.lastchanged_varId].value, "%Y-%m-%d %H:%M:%S") + datetime.timedelta(minutes = config.MINIMUM_CHANGE_FREQUENCY)

		return max([date1, date2])

	def getHumidity(self):
		try:
			return float(indigo.devices[self.humidity_devId].sensorValue)
		except:
			indigo.server.log(fan.zoneName + " fan script: could not determine the current humidity")
			return -1.0


######################

def AutoComfort(config, fanZones):
	senseMeID = "com.pennypacker.indigoplugin.senseme"
	senseMePlugin = indigo.server.getPlugin(senseMeID)

	'''

	LOOP THROUGH FANS

	'''
	for fan in fanZones:
	#	if script_debug:
	#		indigo.server.log(fan.zoneName + ": now processing")

		fan.config = config

		target_speed = 0
		temp_delta = fan.getTemperatureDelta()

		# A list of the reasons that the script calculates for the speed.  Used for output to the Event Log
		reasons = []

	#################################################################
	#		LOCK LOGIC - WHEN SOMEONE MAKES MANUAL CHANGES
	#################################################################

		previousTargetSpeed = int(indigo.variables[fan.target_speed_varId].value)
		if not fan.isLocked() and fan.getCurrentSpeed() != previousTargetSpeed:
			# woosh mode throws off the detection
			if not fan.wooshMode():
				indigo.server.log(fan.zoneName + ": has been changed outside of the auto_fan script (current speed: " + str(fan.getCurrentSpeed()) + ", previous target speed: " + str(previousTargetSpeed) + ").  Will now lock changes for 60 minutes")
				# Seems that someone has made a change to the fan manually.
				indigo.variable.updateValue(fan.locked_varId, value=unicode((datetime.datetime.now() + datetime.timedelta(minutes = fan.locktime)).strftime("%Y-%m-%d %H:%M:%S")))
				indigo.variable.updateValue(fan.target_speed_varId, value=unicode(fan.getCurrentSpeed()))

		if fan.isLocked():
			indigo.variable.updateValue(fan.target_speed_varId, value=unicode(fan.getCurrentSpeed()))		
			if config.script_debug:
				indigo.server.log(fan.zoneName + ": fan is locked (current speed: " + str(fan.getCurrentSpeed()) + ") from changes until " + str(fan.isLockedTime()))
			continue

	#################################################################
	#		HVAC
	#################################################################

		if fan.HVAC_Running():
			reasons.append(fan.zoneName + " HVAC is running [Impact: +1]")
			target_speed = target_speed + 1
		else:
			reasons.append("HVAC is not running [Impact: 0]")

	#################################################################
	#		TEMPERATURE AND SEASON BASED LOGIC
	#################################################################

		# For the summer months
		if (fan.getCoolSetpoint() > 0 and (fan.isIdealTempIsCoolerThanOutside() or fan.getTemperatureDelta() > 0)) or (fan.getCoolSetpoint() > 0 and fan.getHeatSetpoint() == 0 and fan.summer_fan_at_bedtime and config.isNighttime()):
			delta_fanspeed_impact = 0

			if config.script_debug:
				reasons.append("Mode: summer warm day mode")

			# Increase when presence is detected
			if fan.getPresence():
				reasons.append("presence is detected [Impact: +1]")
				target_speed = target_speed + 1

			# if humidity or temperature are high at night, raise one more level
			if config.isNighttime() and fan.summer_fan_at_bedtime and (fan.getHumidity() > config.BEDTIME_HIGH_HUMIDITY or fan.getFeelsLikeTemp() > config.BEDTIME_HIGH_FEELSLIKE_TEMPERATURE):
				reasons.append("humidity (" + str(fan.getHumidity()) + "%) or outside feels like temperature (" + str(fan.getFeelsLikeTemp()) + "°F) is high during sleeping hours.  [Impact: +1]")
				target_speed = target_speed + 1

			for entry in fan.temp_steps:
				triggered = False
				if entry.min_temp is None:
					if temp_delta <= entry.max_temp:
						triggered = True
				elif entry.max_temp is None:
					if temp_delta >= entry.min_temp:
						triggered = True
				else:
					if temp_delta > entry.min_temp and temp_delta <= entry.max_temp:
						triggered = True

				if triggered:
					impact_statement = ""
					if entry.impact is not None:
						delta_fanspeed_impact = entry.impact
						impact_statement = "target_speed: +" + str(entry.impact) + "  "

					if entry.max_target is not None:
						fan.max_target = entry.max_target
						impact_statement = impact_statement + "max_target: " + str(entry.max_target) + "  "

					if entry.min_target is not None:
						fan.min_target = entry.min_target
						impact_statement = impact_statement + "min_target: " + str(entry.min_target)

					reasons.append("current temperature (" + str(fan.getCurrentRoomTemperature()) + "°F) is between " + str(entry.min_temp) + "°F and " + str(entry.max_temp) + "°F (" + str(temp_delta) + "°F) from the desired temperature of " + str(fan.getIdealTemperature()) + "°F [Impact: " + impact_statement + "]")
					break
			
			target_speed = target_speed + delta_fanspeed_impact
		
		# for the cooler days in the early summer.  AC is on, but it's cool outside.
		elif fan.getCoolSetpoint() > 0 and fan.getHeatSetpoint() == 0 and not fan.isIdealTempIsCoolerThanOutside():
			if script_debug:
				reasons.append("Mode: summer cool day mode")

			fan.max_target = 1

			if fan.getMinTarget() > 1:
				fan.min_target = 1

			reasons.append("ideal temperature of " + str(fan.getIdealTemperature()) + "°F is warmer than the current outside temperature (" + str(fan.getFeelsLikeTemp()) + "°F) [max_target: 0]")
		
		# Fall, spring, and winter
		elif fan.getHeatSetpoint() > 0:
			if config.script_debug:
				reasons.append("Mode: fall, spring, and winter mode")

			fan.max_target = 1
			reasons.append("Fall, spring and winter mode [max_target: 1]")

	#################################################################
	#		Someone is home
	#################################################################

		if not config.someone_home:
			reasons.append("no one is home [Maximum Target = 1]")
			fan.max_target = 1

			if fan.getMinTarget() > 1:
				fan.min_target = 1

	#################################################################
	#		MINIMUM AND MAXIMUM TARGET LOGIC
	#################################################################

		# Compare target to the minimum and maximum and make adjustments
		if target_speed < fan.getMinTarget():
			reasons.append("target speed set adjusted for the fan minimum speed [Minimum: " + str(fan.getMinTarget()) + "]")
			target_speed = fan.getMinTarget()

		if target_speed > fan.getMaxTarget():
			reasons.append("target speed is adjusted for the fan maximum speed [Maximum: " + str(fan.getMaxTarget()) + "]")

			target_speed = fan.getMaxTarget()

	#################################################################
	#		CREATE STRINGS FOR OUTPUT TO EVENT LOG
	#################################################################

		i = 0
		reasons_str = ""
		for reason in reasons:
			if i == 0:
				reasons_str = '\n'

			reasons_str = reasons_str + "     " + reason + '\n'
			i = i + 1

	#################################################################
	#		SAVE CHANGES TO THE FAN
	#################################################################

		if target_speed > fan.getCurrentSpeed():
			action_str = fan.zoneName + " fan: increasing from " + str(fan.getCurrentSpeed()) + " to " + str(target_speed)
		elif target_speed == fan.getCurrentSpeed():
			action_str = fan.zoneName + " fan: no change (current speed: " + str(fan.getCurrentSpeed()) + ")"
		elif target_speed < fan.getCurrentSpeed():
			action_str = fan.zoneName + " fan: decreasing from " + str(fan.getCurrentSpeed()) + " to " + str(target_speed)

		# Make the changes to the fan, save some things to the Indigo variables.  Write the output to the Event Log
		if target_speed != fan.getCurrentSpeed():
			wooshMode = target_speed >= 2 and fan.enable_woosh_mode_when_present and fan.getPresence() and not fan.wooshMode()

			if wooshMode:
				reasons_str = reasons_str + "     turned on woosh mode\n"

			indigo.server.log(fan.zoneName + " fan script: \n\n" + action_str + " due to the change to " + fan.getEventChanged() + ", reasons influencing the target speed: " + reasons_str)

			senseMePlugin.executeAction("fanSpeed", deviceId=fan.fanId, props={'speed':str(target_speed)})
			indigo.variable.updateValue(fan.target_speed_varId, value=unicode(target_speed))
			indigo.variable.updateValue(fan.lastchanged_varId, value=unicode(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
			
			if wooshMode:
				senseMePlugin.executeAction("whooshOn", deviceId=fan.fanId, props={})

		else:
			if config.script_debug:
				indigo.server.log(fan.zoneName + " fan script: \n\n" + action_str + " due to the change to " + fan.getEventChanged() + ", reasons influencing the target speed: " + reasons_str)

		if config.script_debug:
			debug_str = "\n\n" + fan.zoneName + "fan script debug: \n\n"

			debug_str = debug_str + " current speed: " + str(fan.getCurrentSpeed()) + "\n"
			debug_str = debug_str + " min_target speed: " + str(fan.getMinTarget()) + "\n"
			debug_str = debug_str + " max_target speed: " + str(fan.getMaxTarget()) + "\n"
			debug_str = debug_str + " target speed: " + str(target_speed) + "\n"
			debug_str = debug_str + " room temp: " + str(fan.getCurrentRoomTemperature()) + "°F" + "\n"
			debug_str = debug_str + " outside temp: " + str(fan.getFeelsLikeTemp()) + "°F" + "\n"
			debug_str = debug_str + " ideal temp: " + str(fan.getIdealTemperature()) + "°F" + "\n"
			debug_str = debug_str + " getCoolSetpoint: " + str(fan.getCoolSetpoint()) + "°F" + "\n"
			debug_str = debug_str + " getHeatSetpoint: " + str(fan.getHeatSetpoint()) + "°F" + "\n"
			debug_str = debug_str + " temp delta (current - ideal): " + str(fan.getTemperatureDelta()) + "°F" + "\n"
			debug_str = debug_str + " isIdealTempIsCoolerThanOutside: " + str(fan.isIdealTempIsCoolerThanOutside()) + "\n"

			debug_str = debug_str + " getPresence: " + str(fan.getPresence()) + "\n"
			debug_str = debug_str + " is_nighttime: " + str(config.isNighttime()) + "\n"
			debug_str = debug_str + " fan.HVAC_Running(): " + str(fan.HVAC_Running()) + "\n"
			debug_str = debug_str + " fan.wooshMode(): " + str(fan.wooshMode()) + "\n"

			indigo.server.log(debug_str)

####################################################################################

config = AutoConfortConfig()

fanZones = LoadConfig(config)
AutoComfort(config, fanZones)
