# Remember, need python3 for piface

import os
import glob
import time
import datetime
import sys
import re

# need to split this file? DS18B20 reads hardware but the others are just files
from IotSensors import IotSensor, IotSensor2, DS18B20
import pifacedigitalio as p

###########################################################
# Global variables used in subroutines
###########################################################
LED_HEATING = 1 # change while debugging, should be 1
LED_WATER = 0
LED_TIMER = 2
LED_BLINK = 3
LED_WARN2 = 6
LED_WARN = 7

PB1 = 0
# pb1 is button nearest the USB port, on old piface

internalTempFilename = "/sys/class/thermal/thermal_zone0/temp"

netfilepathS = "/nas/sdrive/PiNet/data/" # or set to device name
netfilepathW = "/nas/wdrive/PiNet/data/"
#t#netfilepathS = "s:/PiNet/data/"		#t#
#t#netfilepathW = "w:/PiNet/data/"		#t#

piNetfilename = "t1.dat"
#t#piNetfilename = "t2.dat" # filename for both #t#

overrideFilename = netfilepathS + "override.dat"

aaSensor = IotSensor('aa', "aa.dat", "T", netfilepathS)		# living room temp sensor
#abSensor = IotSensor('ab', "ab.dat", "L", netfilepathS)	# living room light sensor
acSensor = IotSensor2('ac', "ac.dat", "TH", netfilepathS)	# bathroom hum/temp sensor
adSensor = IotSensor2('ad', "ad.dat", "TP", netfilepathS)	# landing pressure/temp sensor
DS18in = DS18B20('DSin', "28-00000418bede")
DS18out = DS18B20('DSout', "28-00000437d62d")

# set global variables -- most of these get changed later
#  from the ini file
currentTemperature = 20
switchTemperature = 19.6	# changed later to SWITCH_TEMPERATURE_DAY
heatingHysteresis = 0.3
combinedTemp = 0.0
heatingOnOrOff = 0
pitemp = 0					# from internal sensors
overrideHeatingChar = '?'
overrideWaterChar = '?'

# initialise for real, read files on sdrive
aaFound = aaSensor.ReadFile()
acFound = acSensor.ReadFile()
adFound = adSensor.ReadFile()

##redecimal = re.compile('\d+\.\d*')
##reinteger = re.compile('\d+')
#redate =   re.compile('(20[0-9]{2})-([0-9]{2})-([0-9]{2})[ T]([0-9]{2}):([0-9]{2}):([0-9]{2})')
redaterange = re.compile('(\d+)-(\d+)')

# time heating [relay] last switched, to avoid turning on and off too quickly
# this is in minutes, set to one for testing, try 15 for real
HEATING_CHANGE_DELAY=15

# not world time, but day, night, between on times etc
timerZone = -1
oldYearDay = -1

# make these globals
utcDT = datetime.datetime.utcnow()
nowDT = datetime.datetime.now()
# set last change to 2014 - any old date is fine
heatingChangeTimeUtc = utcDT.replace(2014)

# set as globals, use subroutine setTimes from here on
isBST = nowDT.hour > utcDT.hour
isWeekend = utcDT.isoweekday() > 5
yearDay = utcDT.timetuple()[7]

# set this to a sensible default
# a list of tuples
tp1 = (7,1)
tp2 = (10,2)
tp3 = (16,3)
tp4 = (22,4)
todaysTimesGMT = [tp1,tp2,tp3,tp4]
#print ("todaysTimesGMT:",todaysTimesGMT) #t#

# setup globals, data loaded from ini
iniHeatingWDlist = []
holidayList = []
schooldayList = []
vacationList = []
isHoliday = False # assume for now
isVacation = False # assume for now
isSchoolday = not isWeekend # will do for now

# works because extension is always .py
progName = os.path.basename(__file__)
progName = progName[:len(progName)-3]

# read from parameter file... set sensible defaults for now
# night get altered to frost when vacation is set
switch_temperature_day = 19.7
switch_temperature_night = 17.0
switch_temperature_frost = 6.0

############################################################
# subroutines required early on, must declare globals first
############################################################
def readFromIni(exitVal):
	global vacationList, holidayList, schooldayList, iniHeatingWDlist, iniHeatingWElist
	global switch_temperature_day, switch_temperature_night, switch_temperature_frost

	try:
		f = open('heatPf.ini', "r")		# always in same directory as script
	except:
		print("Cannot open ini file")
		if exitVal == 1:
			exit(2)
		return 0

	iniline = f.readline()
	while (iniline):
		iniline = iniline.rstrip('\n')
		iniline = iniline.replace(' ', '')
		#print ("iniline: ",iniline)
		if len(iniline) > 1:
			if iniline[0] != '#':
				#print ("parseme: ",iniline)
				els = iniline.split('=')
				if els[0] == 'vacationList':
					vacationList = els[1].split(',')
				if els[0] == 'schooldayList':
					schooldayList = els[1].split(',')
				if els[0] == 'holidayList':
					holidayList = els[1].split(',')
				if els[0] == 'HeatingWD':
					iniHeatingWDlist = els[1].split(',')
				if els[0] == 'HeatingWE':
					iniHeatingWElist = els[1].split(',')
				if els[0] == 'HeatingWD':
					iniHeatingWDlist = els[1].split(',')
				if els[0] == 'TempDay':
					switch_temperature_day = float(els[1])
				if els[0] == 'TempNight':
					switch_temperature_night = float(els[1])

		iniline = f.readline()
	f.close()
	return 1

def isDaynoInList(dayno, thislist):
	#print ("Checking list",thislist, " for",dayno)
	for i in range(len(thislist)):
		if thislist[i].isdigit():
			if dayno == int(thislist[i]):
				return True
		else:
			m = redaterange.match(thislist[i])
			if m:
				if dayno >= int(m.group(1)) and dayno <= int(m.group(2)):
					return True
	return False

# setTimes must have already been called, to set isWeekend and yearDay
def setDailyTimes(): # only check once a day, or on startup
	global isHoliday, isVacation, isSchoolday
	isHoliday = isDaynoInList(yearDay, holidayList) # e.g. easter, bank holiday
	isVacation = isDaynoInList(yearDay, vacationList)
	if isWeekend or isHoliday or isVacation:
		isSchoolday = False
	else:
		isSchoolday = isDaynoInList(yearDay, schooldayList)

def setTimes():
	global nowDT, utcDT, isBST, isWeekend, yearDay
	nowDT = datetime.datetime.now()
	utcDT = datetime.datetime.utcnow()
	isBST = nowDT.hour > utcDT.hour
	isWeekend = utcDT.isoweekday() > 5
	yearDay = utcDT.timetuple()[7]

def setTodaysHeatingTimes():
	# don't need global for most? just reading
	global todaysTimesGMT
	# set todaysTimesGMT from iniHeatingWDlist, based on weekend, vacationlist, schooldaylist, anything else?
	tp0 = iniHeatingWDlist[0].split(':')
	tp1 = iniHeatingWDlist[1].split(':')
	tp2 = iniHeatingWDlist[2].split(':')
	tp3 = iniHeatingWDlist[3].split(':')

	if not isSchoolday:
		tp0 = iniHeatingWElist[0].split(':')
		tp1 = iniHeatingWElist[1].split(':')
		tp2 = iniHeatingWElist[2].split(':')
		tp3 = iniHeatingWElist[3].split(':')

	# here could do: If it's a Friday, set fourth tp to weekend value
	# here could do: If it's a Sunday and the next day is a schoolday, set the fourth tp to weekday value

	#print ("tp0:",tp0, ",tp1:",tp1,"tp2:",tp2,"tp3:",tp3)
	hr0 = int(tp0[0])
	hr1 = int(tp1[0])
	hr2 = int(tp2[0])
	hr3 = int(tp3[0])
	if isBST:
		hr0 = hr0-1
		if hr1 >1:
			hr1 = hr1-1
		if hr2 >1:
			hr2 = hr2-1
		hr3 = hr3-1

	

	todaysTimesGMT = [(hr0,int(tp0[1])),(hr1,int(tp1[1])), (hr2,int(tp2[1])), (hr3,int(tp3[1])) ]
	#print ("todaysTimesGMT:",todaysTimesGMT)

## end of first group of subroutines ###############################
####################################################################

readFromIni(1)	# 1 = if fails, exit prog
if 0:
	print("tempDay",switch_temperature_day)
	print("tempNight",switch_temperature_night)
	print("tempFrost",switch_temperature_frost)

	print("Vacationlist",vacationList)
	print("HolidayList",holidayList)
	print("SchooldayList",schooldayList)
	print("iniHeatingWDlist",iniHeatingWDlist)
	print("iniHeatingWElist",iniHeatingWElist)


setTimes()
setDailyTimes()
setTodaysHeatingTimes()


# main program continues after next group of subroutines

####################################################
# subroutines
####################################################


def setAllOutputs(onOrOff):
	for jj in range(0, 8):
		p.digital_write(jj,onOrOff) # 1 = on
		#t#print ("switchoff:",jj)	#t#

def resetAllOutputs():
	setAllOutputs(0)

def logWrite(msg):
	logtime = datetime.datetime.utcnow()
	logfilename = "%s-%02u%02u%02u.log" % (progName, logtime.year % 100, logtime.month, logtime.day)
	try:
		f1 = open(logfilename, "a")
	except IOError as e:
		print ("Could not open log file: ", logfilename)
		print (" I/O error({0}): {1}".format(e.errno, e.strerror))
	else:
		msg = msg + "\n"
		f1.write(msg)
		f1.close()

# incorporate netWriteT, only difference is dir path
def netWrite(curpath, curfn, msg):
	if os.path.isdir(curpath): # has slash on end, ok? "/nas/sdrive/dpi"):
		pathAndFilename = curpath + curfn
		try:
			f2 = open(pathAndFilename, "w")
		except IOError:
			msg = "Could not open net file: " + pathAndFilename
			print (msg)
			logWrite(msg)
		else:
			msg = msg + "\n"
			try:
				f2.write(msg)
				f2.close()
			except IOError as e:
				print ("Error writing to net file: I/O error({0}): {1}".format(e.errno, e.strerror))
				logWrite("Error writing to net file: I/O error({0}): {1}".format(e.errno, e.strerror))

		p.digital_write(LED_WARN,0)
		#t#print ("LED_WARN off")	#t#

	else:
		print ("Cannot write to net log, path", curpath, "not available.")
		logWrite("Cannot write to net log, path" + " not available.")
		p.digital_write(LED_WARN,1)
		#t#print ("LED_WARN on")	#t#


# this function checks and changes the timerzone
# it also alters the temp setting accordingly
def checkTimerzone():
	global timerZone
	global todaysTimesGMT
	global switchTemperature
	global oldYearDay
	changesMade = 0
	# doesn't need to know if weekend, already taken into account
	# BUT does need to know if it's a new day, so might be weekend etc.
	setTimes()
	if oldYearDay != yearDay:
		print ("It's a new day!!")
		str = "T1#%04u-%02u-%02uT%02u:%02u:%02uZ#NewDay:%u" % \
			(utcDT.year, utcDT.month, utcDT.day, utcDT.hour, utcDT.minute, utcDT.second, yearDay)
		if isBST:
			str += "#BST"
		else:
			str += "#GMT"
		if isWeekend:
			str += "#WE"
		else:
			str += "#WD"

		setDailyTimes()
		if isHoliday:
			str += "#IsHol:Y"
		else:
			str += "#IsHol:n"
		if isVacation:
			str += "#IsVac:Y"
		else:
			str += "#IsVac:n"
		if isSchoolday:
			str += "#IsSch:Y"
		else:
			str += "#IsSch:n"
		logWrite(str)

		setTodaysHeatingTimes()

		str = "T2#%04u-%02u-%02uT%02u:%02u:%02uZ" % \
			(utcDT.year, utcDT.month, utcDT.day, utcDT.hour, utcDT.minute, utcDT.second)
		str += "#TodaysTimesGMT#%02u:%02u" % (todaysTimesGMT[0][0], todaysTimesGMT[0][1])
		if todaysTimesGMT[1][0] > -1:
			str += "#%02u:%02u" % (todaysTimesGMT[1][0], todaysTimesGMT[1][1])
		else:
			str += "#--"
		if todaysTimesGMT[2][0] > -1:
			str += "#%02u:%02u" % (todaysTimesGMT[2][0], todaysTimesGMT[2][1])
		else:
			str += "#--"
		str += "#%02u:%02u" % (todaysTimesGMT[3][0], todaysTimesGMT[3][1])
		
		logWrite(str)

	#print (todaysTimesGMT)

	if timerZone < 1:
		#check if on1 time is reached
		print ("timerZone < 1 (", timerZone, ")")
		checkTime = datetime.datetime(utcDT.year, utcDT.month, utcDT.day, todaysTimesGMT[0][0], todaysTimesGMT[0][1])
		print (" checkTime (1st entry in todaysTimesGMT):", checkTime)
		print (" nowTime:", utcDT)
		diff = checkTime - utcDT
		print (" diff(0):", diff)
		if utcDT > checkTime:
			if todaysTimesGMT[1][0] > todaysTimesGMT[0][0]:	# todaysTimesGMT[1][0] might be -1
				print (" Changing to timerZone1 am on")
				str = "T3#%04u-%02u-%02uT%02u:%02u:%02uZ#Timerzone Changed#1a-on" % \
					(utcDT.year, utcDT.month, utcDT.day, utcDT.hour, utcDT.minute, utcDT.second)
				logWrite(str)
				timerZone = 1
			else:	# it was -1, leave on allday
				print (" Jumping to timerZone3 pm on")
				str = "T3#%04u-%02u-%02uT%02u:%02u:%02uZ#Timerzone Changed#3p-on" % \
					(utcDT.year, utcDT.month, utcDT.day, utcDT.hour, utcDT.minute, utcDT.second)
				logWrite(str)
				timerZone = 3
			#either way, use 'on' temperature
			switchTemperature = switch_temperature_day
			changesMade += 1

	if timerZone == 1:
		print ("timerZone = 1")
		# assumes that there is an off1 and on2
		checkTime = datetime.datetime(utcDT.year, utcDT.month, utcDT.day, todaysTimesGMT[1][0], todaysTimesGMT[1][1])
		print (" checkTime (2nd entry in todaysTimesGMT):", checkTime)
		print (" nowTime:", utcDT)
		diff = checkTime - utcDT
		print (" diff(1):", diff)
		if utcDT > checkTime:
			print (" Changing to timerZone2 am off")
			str = "T3#%04u-%02u-%02uT%02u:%02u:%02uZ#Timerzone Changed#2a-off" % \
				(utcDT.year, utcDT.month, utcDT.day, utcDT.hour, utcDT.minute, utcDT.second)
			logWrite(str)
			timerZone = 2
			switchTemperature = switch_temperature_night
			changesMade += 1

	if timerZone == 2:
		print ("timerZone = 2")
		# assumes that there is an off1 and on2
		checkTime = datetime.datetime(utcDT.year, utcDT.month, utcDT.day, todaysTimesGMT[2][0], todaysTimesGMT[2][1])
		print (" checkTime (3rd entry in todaysTimesGMT):", checkTime)
		print (" nowTime:", utcDT)
		diff = checkTime - utcDT
		print (" diff(2):", diff)
		if utcDT > checkTime:
			print (" Changing to timerZone3 pm on")
			str = "T3#%04u-%02u-%02uT%02u:%02u:%02uZ#Timerzone Changed#3p-on" % \
				(utcDT.year, utcDT.month, utcDT.day, utcDT.hour, utcDT.minute, utcDT.second)
			logWrite(str)
			timerZone = 3
			switchTemperature = switch_temperature_day
			changesMade += 1

	if timerZone == 3:
		print ("timerZone = 3")
		# assumes that there is an off1 and on2
		checkTime = datetime.datetime(utcDT.year, utcDT.month, utcDT.day, todaysTimesGMT[3][0], todaysTimesGMT[3][1])
		print ("checkTime (3rd entry in todaysTimesGMT):", checkTime)
		print (" nowTime:", utcDT)
		diff = checkTime - utcDT
		print (" diff(3):", diff)
		if utcDT > checkTime:
			print (" Changing to timerZone4 pm off")
			str = "T3#%04u-%02u-%02uT%02u:%02u:%02uZ#Timerzone Changed#4p-off" % \
				(utcDT.year, utcDT.month, utcDT.day, utcDT.hour, utcDT.minute, utcDT.second)
			logWrite(str)
			timerZone = 4
			switchTemperature = switch_temperature_night
			changesMade += 1

	if timerZone == 4:
		print ("timerZone = 4")
		# check when to flip to next day
		# just need to check when timerZone is 4 and it's after midnight. assumes ontime is > 00:59
		# don't care about date
		print ("nowTime:", utcDT)
		if utcDT.hour == 0 and utcDT.minute > 1:
			print (" Changing to timerZone0 am off")
			str = "T3#%04u-%02u-%02uT%02u:%02u:%02uZ#Timerzone Changed#0a-off" % \
				(utcDT.year, utcDT.month, utcDT.day, utcDT.hour, utcDT.minute, utcDT.second)
			logWrite(str)
			timerZone = 0
			switchTemperature = switch_temperature_night
			setTimes() # set day, weekend etc.
			changesMade += 1

	# timerZone and switchTemperature have been set
	if changesMade:
		print ("TimerZone changes made: timerZone:", timerZone, " switchTemp:", switchTemperature)

	# if don't do this here, the heating light comes on when the timer light is off
	if timerZone == 1 or timerZone == 3:
		p.digital_write(LED_TIMER, 1)
		#t#print("timerLED on")	#t#
	else:
		p.digital_write(LED_TIMER, 0)
		#t#print("timerLED off")	#t#
	oldYearDay = yearDay

# read DS1820 thermometer devices ###################################

def read_pitemp():
	try:
		f4 = open(internalTempFilename) # unix system file
	except:
		return -99

	lines = f4.readlines()
	f4.close
	ti = lines[0] # just read it?
	t2 = ti[0:2] + "." + ti[2]
	return t2

#####################################################################
# this function gets the 'current' temp, merging various sources
def readTemp():
	global currentTemperature, pitemp
	global aaSensor, acSensor, adSensor
	global aaFound, acFound, adFound
	global tempCcable, tempCboard # without this, gets rounded somehow, try with this
	# or maybe it is using a previous value, cos of ambiguous location, inserted at top of code

	# physical read of temperature values
	pitemp = read_pitemp()	# from system file
	#t#pitemp = "-99"				#t#
	DS18in.ReadTemp()
	time.sleep(0.1)
	DS18out.ReadTemp()
	
	aaFound = aaSensor.ReadFile()
	adFound = adSensor.ReadFile()
	if aaFound:
		# check how old it is? if aaSensor.isLate()....
		currentTemperature = aaSensor.value	# this is the basis, and for initial testing the only value under consideration
		currentDate = aaSensor.DateAsString()
		print ("Current aa temperature as read: ", currentTemperature, " at:", currentDate)

	else:
		currentTemperature = aaSensor.value	# this will be the old version, but still ok-ish?
		currentDate = aaSensor.DateAsString()
		print ("Using old temperature: ", currentTemperature, " as at:", currentDate)

	acFound = acSensor.ReadFile()
	if acFound:
		print ("acFound")
	else:
		print ("acNotFound")

	print ("readTemp returning", currentTemperature)
	return currentTemperature



# separate function to change relay itself? So easily changed for non piface?
def setHeatingOnOrOff(onOrOff):
	global heatingChangeTimeUtc, heatingOnOrOff
	# run the change without checking, will take care of mis-matches
	heatingChangeTimeUtc = datetime.datetime.utcnow()

	p.digital_write(LED_HEATING,onOrOff) # 1 = on

	str = "H#"
	# write to log: H#datetime#SW-ON
	str += "%04u-%02u-%02uT" % (heatingChangeTimeUtc.year, heatingChangeTimeUtc.month, heatingChangeTimeUtc.day)
	str += "%02u:%02u:%02uZ#" % (heatingChangeTimeUtc.hour, heatingChangeTimeUtc.minute, heatingChangeTimeUtc.second)
	if onOrOff == 1:
		str += "SW-ON"
	else:
		str += "SW-OFF"
	logWrite(str)
	print (str)
	# update global variables
	heatingOnOrOff = onOrOff


def readOverrideStatus():
	global overrideHeatingChar
	keepOhc = overrideHeatingChar # keep old value
	oneLine = ""
	try:
		f2 = open(overrideFilename,"r")
		oneLine = f2.read()
	except:
		print ("Cannot open override file", overrideFilename)
		return False
	f2.close()
	#print ("Override line:", oneLine)
	if len(oneLine) > 0:
		thisval = oneLine[0]
		if thisval == 'X':
			if keepOhc != 'X':
				print ("Change to override from", keepOhc + " to none(X)")
				str = "H#"
				# write to log: H#datetime#overridechange
				str += "%04u-%02u-%02uT" % (heatingChangeTimeUtc.year, heatingChangeTimeUtc.month, heatingChangeTimeUtc.day)
				str += "%02u:%02u:%02uZ#" % (heatingChangeTimeUtc.hour, heatingChangeTimeUtc.minute, heatingChangeTimeUtc.second)
				str += "Change to override from " + keepOhc + " to none(X)"
				logWrite(str)
			overrideHeatingChar = 'X'
			return True
		if thisval == 'N':
			if keepOhc != 'N':
				print ("Change to override from", keepOhc, "to on(N)")
				str = "H#"
				# write to log: H#datetime#overridechange
				str += "%04u-%02u-%02uT" % (heatingChangeTimeUtc.year, heatingChangeTimeUtc.month, heatingChangeTimeUtc.day)
				str += "%02u:%02u:%02uZ#" % (heatingChangeTimeUtc.hour, heatingChangeTimeUtc.minute, heatingChangeTimeUtc.second)
				str += "Change to override from " + keepOhc + " to on(N)"
				logWrite(str)
			overrideHeatingChar = 'N'
			return True
		if thisval == 'F':
			if keepOhc != 'F':
				str = "H#"
				# write to log: H#datetime#overridechange
				str += "%04u-%02u-%02uT" % (heatingChangeTimeUtc.year, heatingChangeTimeUtc.month, heatingChangeTimeUtc.day)
				str += "%02u:%02u:%02uZ#" % (heatingChangeTimeUtc.hour, heatingChangeTimeUtc.minute, heatingChangeTimeUtc.second)
				str += "Change to override from " + keepOhc + " to off(F)"
				logWrite(str)
				print ("Change to override from", keepOhc, "to off(F)")
			overrideHeatingChar = 'F'
			return True

	return False # meaning cannot read

def determineHeatingOnOff():
	global utcDT, heatingOnOrOff, HEATING_CHANGE_DELAY, combinedTemp
	setTimes() # not necessary again?

	# if last change (heatingChangeTime < HEATING_CHANGE_DELAY mins, exit
	td = utcDT - heatingChangeTimeUtc
	tcompare = td.total_seconds()
	print ("heating_change_delay: ", HEATING_CHANGE_DELAY, "(mins) ; compare-secs: ", tcompare)

	# read sensors... always do for log
	print ("Continuing after time test to check sensors")
	combinedTemp = float(readTemp())
	print ("combinedTemp as read: ",combinedTemp)
	if (combinedTemp < -90): # error condition
		print("Can't read aa temperature")
		return 0

	if ((tcompare / 60) < HEATING_CHANGE_DELAY):
		print (" Delaying temperature comparison after change")
		return 0
	print ("Continuing after time test")
	
	# read override values from file?
	# 1 = On, 2 = Off (0 is none), global set in line below
	#print ("Reading override file")
	readOverrideStatus() # if a valid read - no that's not enough, have to ignore retval
	if overrideHeatingChar == 'N':
		if heatingOnOrOff == 0:
			print ("Overriding heating on")
			setHeatingOnOrOff(1)
		else:
			print ("Not checking, heating override is on")
		return
	if overrideHeatingChar == 'F':
		if heatingOnOrOff == 1:
			print ("Overriding heating off")
			setHeatingOnOrOff(0)
		else:
			print ("Not checking, heating override is off")
		return
	# if get here, overrideHeatingChar must be 'X' = none

	if heatingOnOrOff == 0:
		print ("heating is off, so check if should come on")
		# ignore time, this is taken into account by switch_temp
		# Now have heatingHysteresis as well as the 'time hysterisis' above
		print ("swTemp: ", switchTemperature, " hyst: ", heatingHysteresis," combinedTemp: ", combinedTemp)
		if combinedTemp < switchTemperature:
			print ("CombinedTemp ", combinedTemp, " now less than switch temp ", switchTemperature, ": turn heating on")
			setHeatingOnOrOff(1)
		else:
			print ("No change: combined temp ", combinedTemp, " is still higher/equal to the switch temp", switchTemperature)

	else:
		print ("heating is on, so check if should go off")
		print ("swTemp: ", switchTemperature, " hyst: ", heatingHysteresis, " combinedTcmp: ", combinedTemp)

		xx = switchTemperature + heatingHysteresis
		if (xx < combinedTemp):
			print ("CombinedTemp ", combinedTemp, "now greater than switchTemp + hysteresis ", xx, ": turn heating off")
			setHeatingOnOrOff(0)
		else:
			print ("CombinedTemp ", combinedTemp, " is still less than/equal to switchTemp + hysteresis", xx)





###########################################################
# Startup lines
###########################################################
#print (progName, "Start time (UTC): ", utcDT)

str = "B1#%04u-%02u-%02uT%02u:%02u:%02uZ#%s#Startup" % (utcDT.year, utcDT.month, utcDT.day, utcDT.hour, utcDT.minute, utcDT.second, progName)
logWrite(str)

str = "B2#%04u-%02u-%02uT%02u:%02u:%02uZ#" % (utcDT.year, utcDT.month, utcDT.day, utcDT.hour, utcDT.minute, utcDT.second)
str += "%04u-%02u-%02u %02u:%02u:%02u" % (nowDT.year, nowDT.month, nowDT.day, nowDT.hour, nowDT.minute, nowDT.second)
if isBST:
	str += "#BST"
else:
	str += "#GMT"
str += "#YD:%u" % yearDay
if isWeekend:
	str += "#WE"
else:
	str += "#WD"
logWrite(str)

str = "B3#%04u-%02u-%02uT%02u:%02u:%02uZ" % \
	(utcDT.year, utcDT.month, utcDT.day, utcDT.hour, utcDT.minute, utcDT.second)
str += "#TodaysTimesGMT#%02u:%02u" % (todaysTimesGMT[0][0], todaysTimesGMT[0][1])
if todaysTimesGMT[1][0] > -1:
	str += "#%02u:%02u" % (todaysTimesGMT[1][0], todaysTimesGMT[1][1])
else:
	str += "#--"
if todaysTimesGMT[2][0] > -1:
	str += "#%02u:%02u" % (todaysTimesGMT[2][0], todaysTimesGMT[2][1])
else:
	str += "#--"
str += "#%02u:%02u" % (todaysTimesGMT[3][0], todaysTimesGMT[3][1])
logWrite(str)

str = "B4#%04u-%02u-%02uT%02u:%02u:%02uZ" % \
	(utcDT.year, utcDT.month, utcDT.day, utcDT.hour, utcDT.minute, utcDT.second)
str += "#TodaysTemps#%.1f#%.1f" % (switch_temperature_day, switch_temperature_night)
logWrite(str)


p.init()
# brief pause, then set all LEDs off??
resetAllOutputs()	# sets all outputs to off, doesn't change any variables

checkTimerzone()	# calls setTimes()

determineHeatingOnOff()

print ("About to start loop =============================")
while True:
	#print ("Looping: ------", utcDT)
	setTimes()

	if (utcDT.second % 15) == 0:		# reconsider this strategy, if the final time.sleep is > 1 sec
		print ("15sec: +++++", utcDT.second)
		p.digital_write(LED_BLINK,1)
		checkTimerzone() #calls setTimes (again)
		determineHeatingOnOff()

		str = "L#"
		str += "%04u-%02u-%02uT" % (utcDT.year, utcDT.month, utcDT.day)
		str += "%02u:%02u:%02uZ#" % (utcDT.hour, utcDT.minute, utcDT.second)
		str += pitemp + "#"
		str += "%.2f#" % DS18in.value
		str += "%.2f#" % DS18out.value
		if timerZone == 1 or timerZone == 3:
			str += "D#"
			p.digital_write(LED_TIMER, 1)
		else:
			str += "N#"
			p.digital_write(LED_TIMER, 0)
		if heatingOnOrOff == 0:
			str += "h"
		else:
			str += "H"
		str += "#W"
		#str += "#0#x" # 1st=overridestatus, 2nd = placeholder for anything else
		str += "#%s#x" % overrideHeatingChar	# 1st=overridestatus, 2nd = placeholder for anything else
		str += "#" + ('A' if aaFound else 'a')
		str += 'C' if acFound else 'c'
		str += 'D' if adFound else 'd'
		str += "#%.2f" % combinedTemp
		str += "#%.1f" % float(aaSensor.value)
		str += "#%.1f" % float(acSensor.sensor1.value)
		str += "#%.1f" % float(adSensor.sensor1.value)
		print (str)

		logWrite(str)

		# can no longer see these anyway...
		#if aaFound == 'a' or acFound == 'c':
		#	p.digital_write(LED_WARN2, 1)
		#else:
		#	p.digital_write(LED_WARN2, 0)

		if (utcDT.second == 0): # once a minute, too often?] #if 1:
			netWrite(netfilepathS, piNetfilename, str) # copy log to sdrive 
			netWrite(netfilepathW, piNetfilename, str)

		pb1 = p.digital_read(PB1)	# this is the nearest button to the USB port, old piface
		#t#pb1 = 0	#t#
		if (pb1 == 1):
			print ("Quitting program")
			resetAllOutputs()
			exit(0)
		p.digital_write(LED_BLINK,0)

	time.sleep(1)

exit()

#########################################################
# version 14/07/16, only change from 11/03/16 = comments
# c:\progs\python\heatPf
# s:\PiNet\pi92\python
#########################################################

# sudo mount.cifs //192.168.1.69/share  //nas/sdrive
# sudo mount.cifs //192.168.1.90/Public //nas/wdrive

# sudo cp -p /nas/sdrive/PiNet/pi92/python/heatPf4.py .
# sudo cp -p /nas/sdrive/PiNet/pi92/python/heatPf.ini .
# sudo chown pi:pi heatPf4.py

# sudo cp -p /nas/sdrive/PiNet/pi92/python/IotSensors.py .
# sudo cp -p /nas/sdrive/PiNet/pi92/python/CjsGen.py .
# libs don't need to change permissions / owners

# sudo cp -p heatPf4.py heatPf.py
# sudo python3 heatPf.py
# sudo nohup python3 heatPf.py > heatPfNh3.log &



