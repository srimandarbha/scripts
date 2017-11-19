#!/usr/bin/env python
import urllib2
from BeautifulSoup import BeautifulSoup

WEBSITE='http://www.bbc.com'

r = urllib2.urlopen(WEBSITE)
html = r.read()
soup = BeautifulSoup(html)
print '##### Todays headlines in BBC #####\n'
for link in soup.findAll('h3'):
    if len(link.text.split()) > 1:
        print link.text
