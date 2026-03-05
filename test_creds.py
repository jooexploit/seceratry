import os
import requests


def run_credentials_check():
    url = os.getenv("QURAN_AUTH_URL", "https://oauth2.quran.foundation/oauth2/token")
    client_id = os.getenv("QURAN_CLIENT_ID", "")
    client_secret = os.getenv("QURAN_CLIENT_SECRET", "")

    if not client_id or not client_secret:
        raise SystemExit("Set QURAN_CLIENT_ID and QURAN_CLIENT_SECRET first.")

    print(f"Testing credentials against {url}...")
    try:
        resp = requests.post(
            url,
            data={
                "grant_type": "client_credentials",
                "scope": "content",
            },
            auth=(client_id, client_secret),
            timeout=10,
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
    run_credentials_check()
