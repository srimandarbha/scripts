from selenium.webdriver.common.keys import Keys
from selenium import webdriver
from os.path import exists
from os import remove
from time import sleep

dashboard_list = ["unix dashboard","edp dashboard","network dashboard","windows dashboard"]
options = webdriver.FirefoxOptions();
#options.add_argument('--no-sandbox')
#options.add_argument('--headless')
sninstance = "https://bumchikbum.service-now.com"
sninstanceuser = "bakbak"
sninstancepwd = "buu"
browser = webdriver.Firefox(executable_path='./geckodriver',options=options)
browser.get(str(sninstance) + "/login.do") 
username = browser.find_element_by_id("user_name")
password = browser.find_element_by_id("user_password")
username.send_keys(str(sninstanceuser))
password.send_keys(str(sninstancepwd))
login_attempt = browser.find_element_by_id("sysverb_login")
login_attempt.click()

def browse_dashboard(dashboard):
    browser.get(str(sninstance) + "/nav_to.do?uri=%2Fhome.do")
    sleep(5)
    browser.switch_to.frame("gsft_main")
    sleep(3)
    search_dashboard = browser.find_element_by_id('s2id_page_selector')
    search_dashboard.click()
    dashboard_query = browser.find_element_by_xpath("//input[@id=\"s2id_autogen1_search\"]")
    dashboard_query.send_keys(dashboard)
    dashboard_query.send_keys(Keys.ENTER)

for key in dashboard_list:
    file_name = '_'.join(key.split()) + '.html'
    if exists(file_name):
        remove(file_name)
    browse_dashboard(key)
    sleep(5)    
    browser.get(str(sninstance) + '/home.do?sysparm_stack=no&sysparm_force_row_count=999999999&sysparm_media=print')
    sleep(5)    
    with open(file_name, "w") as f:
        f.write(browser.page_source)

browser.get(str(sninstance) + "/logout.do") 
sleep(3)
browser.close()
