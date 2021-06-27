from selenium import webdriver
from tabulate import tabulate
from bs4 import BeautifulSoup
from os.path import exists
from time import sleep
from os import remove
import json
import re

index=None
temp_list=[]
tabulate_table = {}
file_name='unix_dashboard.html'
ticket_list = ["RITM*", "INC*", "CHG*"]
regex = '(?:% s)' % '|'.join(ticket_list) 

options = webdriver.FirefoxOptions();
options.add_argument('--no-sandbox')
options.add_argument('--headless')
sninstance = "https://bumchik.service-now.com"
sninstanceuser = "dichik"
sninstancepwd = "khikhikhi"
browser = webdriver.Firefox(executable_path='./geckodriver',options=options)
browser.get(str(sninstance) + "/login.do") 
username = browser.find_element_by_id("user_name")
password = browser.find_element_by_id("user_password")
username.send_keys(str(sninstanceuser))
password.send_keys(str(sninstancepwd))
login_attempt = browser.find_element_by_id("sysverb_login")
login_attempt.click()

if exists(file_name):
    remove(file_name)

browser.get(str(sninstance) + '/home.do?sysparm_stack=no&sysparm_force_row_count=999999999&sysparm_media=print')
sleep(5)    

with open(file_name, "w") as f:
    f.write(browser.page_source)
browser.get(str(sninstance) + "/logout.do") 
sleep(3)
browser.close()

with open('unix_dashboard.html') as fp:
     soup = BeautifulSoup(fp, 'html.parser')

for i in soup.find_all('td', {'class': 'drag_section_movearea'}):
     tabulate_table[i.text] = {'headers': [], 'data': []}
                          
for i in soup.find_all('th'):
     if bool(i.attrs):
         tabulate_table[list(tabulate_table)[index]]['headers'].append(i.text)
     else:
         if index  is None:
             index=0
         else:
             index+=1

for i in soup.find_all('td')[5:]:
      if i.has_attr('class'):
          if i.text != "":
              if i.get('class') == ['drag_section_movearea']:
                  index=i.text
                  index_len=len(list(tabulate_table[index]['headers']))
              if i.get('class') == ['vt']:
                  if len(temp_list) == 2:
                      temp_list=[]
                  if re.match(regex, i.text):
                      if len(temp_list) == 1:
                          temp_list.append("")
                      else:
                          temp_list.append(i.text)
                  else:
                      temp_list.append(i.text)
      if len(temp_list) == 2:
          if not temp_list in tabulate_table[index]['data']:
              tabulate_table[index]['data'].append(temp_list)
              
for ind, tic_type in enumerate(list(tabulate_table)):
      print("####"+ tic_type + "####")
      print(tabulate(tabular_data=tabulate_table[tic_type]['data'], headers=tabulate_table[tic_type]['headers'], tablefmt='html'))
      print("\n")
