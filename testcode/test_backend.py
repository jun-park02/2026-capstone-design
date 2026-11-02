import requests

BACKEND_URL = "http://localhost:8000"

def test_health_check_api():
    res = requests.get(
        BACKEND_URL+"/health" 
    )

    assert res.status_code == 200

def test_dashboard_summary_api():
    pass