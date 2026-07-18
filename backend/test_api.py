import requests
import json

url = "http://127.0.0.1:8000/api/gateway/execute-ussd/"
data = {
    "gateway_id": 1,
    "ussd_code": "*123#"
}
headers = {"Content-Type": "application/json"}

response = requests.post(url, json=data, headers=headers)
print(response.status_code)
print(response.json())