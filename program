from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as ec
from selenium.common.exceptions import NoSuchElementException, TimeoutException
import sys
import time

url = 'https://localhost:5024/esa/login.html'
username = 'esaadmin'
password = 'esaadmin'

options = webdriver.ChromeOptions()
options.add_argument('--ignore-certificate-errors')
# options.add_argument('-headless')

with webdriver.Chrome(options=options) as driver:

    try:
        driver.get(url)
        username_form = driver.find_element(By.ID, 'j_username')
        password_form = driver.find_element(By.ID, 'j_password')
        username_form.send_keys(username)
        password_form.send_keys(password)
        password_form.submit()
        driver.implicitly_wait(5)
        success_element = WebDriverWait(driver, 10).until(
            ec.presence_of_element_located((By.ID, "loginUserName"))
        )
    except (NoSuchElementException, TimeoutException):
        print(
            "Login failed due to wrong password or timeout exception\n \
            NOTE: Too many authentication failures disabled login page")
        success_element = False
        sys.exit(1)
    except Exception as e:
        print(f"Login failed with exception {e}")
        sys.exit(1)
    if success_element:
        print("Clicking on discover tab")
        discover_system = driver.find_element(By.ID, 'discoversystem_label')
        discover_system.click()
        discover_system_Advanced = driver.find_element(By.ID, 'discovery_tabs_tablist_advancedPaneID')
        discover_system_Advanced.click()
        time.sleep(5)
        snmp_listener_tab = driver.find_element(By.ID, 'discover_tabs_tablist_SNMPTrapID')
        snmp_listener_tab.click()
