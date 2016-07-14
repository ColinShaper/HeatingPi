import time
import datetime
import re

redate =   re.compile('(20[0-9]{2})-([0-9]{2})-([0-9]{2})[ T]([0-9]{2}):([0-9]{2}):([0-9]{2})Z')

def isodateStrToDateTime(str1):
	m = redate.match(str1)
	if (m):
		return (True, datetime.datetime(*time.strptime(str1, "%Y-%m-%dT%H:%M:%SZ")[:6]))
	return (False, 0)




