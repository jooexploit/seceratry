from assistant_app.main import fetch_quran_segment, load_config, normalize_mode


def verify_fix():
    print("Loading config...")
    config = load_config()
    mode = normalize_mode(config.get("quran_khatma", {}).get("mode", "rub"))

    print(f"Attempting to fetch first unit in mode={mode}...")
    try:
        verses = fetch_quran_segment(1, mode, config)
        print("Successfully fetched verses.")
        print(f"Verse count: {len(verses)}")
        if verses:
            print("First verse key:", verses[0].get("key"))
            print("First verse text sample:", str(verses[0].get("text", ""))[:100])
    except Exception as e:
        print(f"FAILED: {e}")


if __name__ == "__main__":
    verify_fix()
