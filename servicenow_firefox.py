from selenium import webdriver
from os.path import join, dirname, abspath
from os import getcwd, remove
from time import sleep

options = webdriver.FirefoxOptions();
options.add_argument('--no-sandbox')
options.add_argument('--headless')
options.set_preference("browser.download.folderList", 2);
options.set_preference("browser.download.dir", getcwd());
options.set_preference("browser.download.useDownloadDir", True);
options.set_preference("browser.download.viewableInternally.enabledTypes", "");
options.set_preference("browser.helperApps.neverAsk.saveToDisk", "application/pdf;text/plain;application/text;text/xml;application/xml");
options.set_preference("pdfjs.disabled", True);

sninstance = "https://bumbchik.service-now.com"
sninstanceuser = "chikibum"
sninstancepwd = "khikhikhi"
browser = webdriver.Firefox(executable_path='./geckodriver',options=options)
browser.get(str(sninstance) + "/login.do") 
sleep(5)

remove('export.pdf')

username = browser.find_element_by_id("user_name")
password = browser.find_element_by_id("user_password")
username.send_keys(str(sninstanceuser))
password.send_keys(str(sninstancepwd))
login_attempt = browser.find_element_by_id("sysverb_login")
login_attempt.click()

sleep(10)
browser.switch_to.frame("gsft_main")
export_report = browser.find_element_by_xpath("//button[@onclick=\"homeExport('', 'true')\"]")
export_report.click()
sleep(3)
click_export = browser.find_element_by_xpath("//button[@onclick=\"return g_export_schedule_dialog.ok()\"]")
click_export.click()
sleep(10)
down_load = browser.find_element_by_id('download_button')
down_load.click()
sleep(20)
browser.close()
