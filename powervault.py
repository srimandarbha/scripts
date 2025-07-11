import sys
import requests
import json
import hashlib

# Suppress insecure HTTPS warnings (for self-signed certs)
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

# Configuration
USE_BASIC_AUTH = 1  # Set to 0 to use SHA-256-based auth
url = "https://<YourIPAddress>"  # Replace with your actual IP or hostname
username = "manage"
password = "Abcd_1234"

# Initialize sessionKey
sessionKey = None

if USE_BASIC_AUTH:
    # HTTP Basic Authentication
    headers = {'datatype': 'json'}
    response = requests.get(
        url + '/api/login',
        auth=(username, password),
        headers=headers,
        verify=False
    )
else:
    # SHA-256 Authentication
    auth_bytes = bytes(username + '_' + password, 'utf-8')
    auth_string = hashlib.sha256(auth_bytes).hexdigest()
    headers = {'datatype': 'json'}
    response = requests.get(
        url + '/api/login/' + auth_string,
        headers=headers,
        verify=False
    )

# Ensure the login was successful
if response.status_code != 200:
    print(f"Login failed: {response.status_code} - {response.text}")
    sys.exit(1)

# Extract session key
try:
    response_json = response.json()
    sessionKey = response_json['status'][0]['response']
except (KeyError, IndexError, json.JSONDecodeError) as e:
    print("Error parsing session key:", e)
    print("Raw response:", response.text)
    sys.exit(1)

# Use sessionKey to get system health
headers = {
    'sessionKey': sessionKey,
    'datatype': 'json'
}
health_response = requests.get(url + '/api/show/system', headers=headers, verify=False)

# Ensure health data request was successful
if health_response.status_code != 200:
    print(f"System health check failed: {health_response.status_code} - {health_response.text}")
    sys.exit(1)

try:
    health_json = health_response.json()
    print("Health = " + health_json['system'][0]['health'])
except (KeyError, IndexError, json.JSONDecodeError) as e:
    print("Error parsing health info:", e)
    print("Raw response:", health_response.text)
