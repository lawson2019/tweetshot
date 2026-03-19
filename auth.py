import json

def create_auth_file():
    print("=" * 60)
    print("How to get a valid logged-in cookie string (must include auth_token):")
    print("1. Open https://x.com in a browser where you are already logged in")
    print("2. Open DevTools (F12) -> Network")
    print("3. Refresh the page and click any x.com request")
    print("4. In Request Headers, find the full Cookie: ... value and copy it")
    print("   Or go to Application/Storage -> Cookies -> https://x.com and copy auth_token/ct0/twid")
    print("5. Paste below (with or without the 'Cookie:' prefix)")
    print("=" * 60)

    raw_cookies = input("Paste your cookie string here:\n> ")

    if not raw_cookies.strip():
        print("No input detected. Please try again.")
        return

    # parse the string
    cookies = []
    raw_cookies = raw_cookies.strip().strip('\'"')
    if raw_cookies.lower().startswith("cookie:"):
        raw_cookies = raw_cookies.split(":", 1)[1].strip()

    parsed_names = set()
    pairs = raw_cookies.split(";")
    for p in pairs:
        p = p.strip()
        if "=" in p:
            k, v = p.split("=", 1)
            name = k.strip()
            value = v.strip()
            parsed_names.add(name)
            cookies.append({
                "name": name,
                "value": value,
                "domain": ".x.com",
                "path": "/",
                "httpOnly": False,
                "secure": True,
                "sameSite": "Lax"
            })
            cookies.append({
                "name": name,
                "value": value,
                "domain": ".twitter.com",
                "path": "/",
                "httpOnly": False,
                "secure": True,
                "sameSite": "Lax"
            })

    required = {"auth_token", "ct0"}
    missing = [x for x in required if x not in parsed_names]
    if missing:
        print(f"\nFailed: missing required cookie(s): {', '.join(missing)}")
        print("Do not use document.cookie; it cannot access HttpOnly auth_token.")
        return

    auth_data = {
        "cookies": cookies,
        "origins": []
    }
    
    with open("auth.json", "w", encoding="utf-8") as f:
        json.dump(auth_data, f, indent=2)
        
    print("\nSuccess: auth.json has been written with auth_token.")
    print("The WebUI will now use your logged-in account session for capture.")

if __name__ == "__main__":
    create_auth_file()
