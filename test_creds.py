import requests
import json

def test_credentials():
    url = "https://oauth2.quran.foundation/oauth2/token"
    client_id = "7c573abe-1b9b-4a72-bf06-2aae93970fea"
    client_secret = "TAoKY4R93~9Y.Tcyu_eWMoCM_-"

    print(f"Testing credentials against {url}...")
    try:
        resp = requests.post(
            url,
            data={
                "grant_type": "client_credentials",
                "scope": "content"
            },
            auth=(client_id, client_secret),
            timeout=10
        )
        print(f"Status Code: {resp.status_code}")
        if resp.status_code == 200:
            print("Success! Token received.")
            print(resp.json().keys())
        else:
            print("Failed.")
            print(resp.text)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_credentials()
