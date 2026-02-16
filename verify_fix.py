from personal_assistant import fetch_rub_text_from_api, load_config

def verify_fix():
    print("Loading config...")
    config = load_config()
    
    print("Attempting to fetch Rub 1...")
    try:
        text = fetch_rub_text_from_api(1, config)
        print("Successfully fetched text!")
        print(f"Text length: {len(text)}")
        print("First 100 chars:")
        print(text[:100])
    except Exception as e:
        print(f"FAILED: {e}")

if __name__ == "__main__":
    verify_fix()
