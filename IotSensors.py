import time
import datetime

import re

from CjsGen import isodateStrToDateTime

redecimal = re.compile('\d+\.\d*')
#redate =   re.compile('(20[0-9]{2})-([0-9]{2})-([0-9]{2})[ T]([0-9]{2}):([0-9]{2}):([0-9]{2})Z')


# this class stores the most recently available data for a given sensor
# if a following read fails, this is recorded in the error field, but the
# previous valid data is retained
class Sensor:
	def __init__(self, id, type):
		self.id = id
		self.status = 0	# unset
		self.value = 0	# this is stored as a string. ?? why??
		self.error = 0 # 1 = couldn't read on last attempt
		self.sensorType = type # a single letter: T=temp, H=humidity, L=light, P=pressure
		self.updateDate = datetime.datetime.utcnow()

	def Update(self, value, date):	# only called with valid data (how to enforce?), clear any error data
		self.value = value
		self.updateDate = date
		self.status = 1 # set. 1 = OK, [no other options now avaible?]
		self.error = 0 # reset any error, 0 = no error, 1 = last attempt was error, most recent valid data retained

	def Display(self):
		#print ("ID (", self.sensorType, "): ", self.id, ", stts: ", self.status, ", val: ", self.value, ", dt: ", self.updateDate.strftime('%Y-%m-%d %H:%M:%S'))
		print ("ID %s (%s): st: %d, val: %s, asat: %s" % (self.id, self.sensorType, self.status, self.value, self.updateDate))

	def DateAsString(self):
		return ("%s" % self.updateDate)

	def GetMinutesAgo(self):
		ss = self.GetSecondsAgo()
		return int (ss/60)

	def GetSecondsAgo(self):
		# work out how long between the stored updateDate and 'now'
		a = datetime.datetime.now()
		c = a - self.updateDate
		#print ("diff secs: ", c.total_seconds())
		return c.total_seconds()

# colin@raspberrypi ~/progs/python $ cat /sys/bus/w1/devices/28-00000418bede/w1_slave
#	c3 00 4b 46 7f ff 0d 10 12 : crc=12 YES
#	c3 00 4b 46 7f ff 0d 10 12 t=12187

class DS18B20(Sensor):
	# a temperature sensor
	def __init__(self, id, sensorFilename, defp = '/sys/bus/w1/devices/'):
		Sensor.__init__(self, id, 'T')
		self.filename = sensorFilename # just for filename, no path or slave-suffix
		self.defaultPath = defp
		
	def readTempRaw(self):
		device_filename = self.defaultPath + self.filename + '/w1_slave'
		#print ("Reading temperature file: ", device_filename)
		# need a try / except here... maybe move the tryCount here too
		try:
			f3 = open(device_filename, 'r')
		except:
			Sensor.error = 1
			Sensor.value = "-99"
			print ("Failed to open device file: ", device_filename)
			return "Failed to open device file"
		lines = f3.readlines()
		f3.close()
		#print ("Lines:")
		#print (lines)
		return lines

	def ReadTemp(self):
		tryCount = 0
		lines = self.readTempRaw()
		while lines[0].strip()[-3:] != 'YES':
			tryCount += 1
			if (tryCount > 20):
				print ("Cannot read temperature for ", self.filename)
				Sensor.error = 1
				return 0
			# wait before trying again
			time.sleep(0.2)
			lines = self.readTempRaw()
		equals_pos = lines[1].find('t=')
		if equals_pos != -1:
			temp_string = lines[1][equals_pos+2:]
			temp_c = float(temp_string) / 1000.0
			myDt = datetime.datetime.utcnow()
			Sensor.Update(self, temp_c, myDt)
			Sensor.error = 0
			return 1

		Sensor.error = 1
		return 0

class IotSensor(Sensor):
	# a sensor with battery info included
	def __init__(self, id, sensorFilename, sensorType, defp = ""):
		Sensor.__init__(self, id, sensorType)
		self.filename = sensorFilename # just the filename, not the path
		self.batteryLevel = 0
		self.batteryDate = 0
		self.sensorType = sensorType
		self.allowedMinutes = 5
		#thermCount += 1
		self.defaultPath = "";
		if len(defp):
			self.defaultPath = defp

	def SetAllowedMinutes(self, newmins): # allow override of default
		self.allowedMinutes = newmins

	def ReadFileAt(self, filepath):
		# format: L#AA#2016-02-25T06:59:15Z#017.2#2016-02-25T06:50:15Z#2.63
		#         0 1  2                    3     4                    5
		fpToRead = filepath + self.filename
		#print ("fpToRead:", fpToRead)
		try:
			f2 = open(fpToRead, "r")
		except IOError:
			self.error = 1
			#print ("Cannot open file")
			return False

		oneLine = f2.read()
		#print ("Line:", oneLine)
		self.error = 0
		f2.close()

		lineEls = oneLine.split('#')
		if len(lineEls) == 6:
			x = redecimal.match(lineEls[3]) # check valid float
			if x:
				xVal = x.group(0)
				xVal = "%.1f" % float(xVal)
				#print ("Value is valid:",xVal)
				dateStr = lineEls[2]
				val, xDT = isodateStrToDateTime(dateStr)
				if val:
					#print ("Date is valid:", xDT)	# not necessarily recent, just structurally valid
					Sensor.Update(self, xVal, xDT)
					return True
				else:
					self.error = 2 # invalid read
			else:
				self.error = 2
		return False

	def ReadFile(self):
		return self.ReadFileAt(self.defaultPath)

	def UpdateBattery(self, value, date):
		self.batteryLevel = value
		self.batteryDate = date

	def Display(self):
		Sensor.Display(self)

	def IsLate(self):
		# compare updateDate to 'now' and allowedMinutes
		return (self.GetMinutesAgo() > self.allowedMinutes)
	def IsVeryLate(self):
		# compare updateDate to 'now' and allowedMinutes
		return (self.GetMinutesAgo() > (2 * self.allowedMinutes))

# probably best to regard the 2-in-1 sensors as a class
# that contains two sensors, rather than inheriting?
class IotSensor2:
	def __init__(self, id, filename, type, defp = ""):
		self.id = id
		id1 = id + '1'
		id2 = id + '2'
		self.sensor1 = IotSensor(id1, filename, type[0], defp)
		self.sensor2 = Sensor(id2, type[1])

	def Update(self, value, date, value2, date2):
		self.sensor1.Update(value, date)
		self.sensor2.Update(value2, date2)

	def Display(self):
		self.sensor1.Display()
		self.sensor2.Display()

	def ReadFileAt(self, filepath):
		# L#AC#2016-02-25T06:59:26Z#18.6#2016-02-25T06:59:26Z#52.4#2016-02-25T06:56:28Z#3.35
		# 0 1  2                    3    4                    5    6                    7
		fpToRead = filepath + self.sensor1.filename
		#print ("fpToRead:", fpToRead)
		try:
			f2 = open(fpToRead, "r")
		except IOError:
			self.sensor1.error = 1
			#print ("Cannot open file")
			return False

		oneLine = f2.read()
		#print ("Line:", oneLine)
		self.sensor1.error = 0
		f2.close()

		lineEls = oneLine.split('#')
		if len(lineEls) == 8:
			x = redecimal.match(lineEls[3]) # check valid float
			if x:
				xVal = x.group(0)
				xVal = "%.1f" % float(xVal)
				#print ("Value1 is valid:",xVal)
				dateStr = lineEls[2]
				val, xDT = isodateStrToDateTime(dateStr)
				if val:
					#print ("Date1 is valid:", xDT)
					self.sensor1.Update(xVal, xDT)
		
			x = redecimal.match(lineEls[5]) # check valid float
			if x:
				xVal = x.group(0)
				xVal = "%.1f" % float(xVal)
				#print ("Value2 is valid:",xVal)
				dateStr = lineEls[4]
				val, xDT = isodateStrToDateTime(dateStr)
				if val:
					#print ("Date2is valid:", xDT)
					self.sensor2.Update(xVal, xDT)
					return True
				else:
					self.error = 2 # invalid read
			else:
				self.error = 2
		return False

	def ReadFile(self):
		return self.ReadFileAt(self.sensor1.defaultPath)

	def IsLate(self):
		return self.sensor1.IsLate()
	def IsVeryLate(self):
		return self.sensor1.IsVeryLate()

	def GetMinutesAgo(self):
		return self.sensor1.GetMinutesAgo()


