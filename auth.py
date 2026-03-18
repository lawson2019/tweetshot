import json

def create_auth_file():
    print("=" * 60)
    print("如何使用您自己已经登录的浏览器获取授权：")
    print("1. 在您已经登录 X/Twitter 的浏览器中，打开网页 https://x.com")
    print("2. 按下键盘 F12 (或右键点击页面 -> 检查) 打开开发者工具")
    print("3. 点击顶部的 'Console' (控制台) 标签页")
    print("4. 在输入框中输入并回车执行以下命令：")
    print("   document.cookie")
    print("5. 复制输出的那一大长串字符串（不要带最外层的单引号或双引号），并将其粘贴到下面：")
    print("=" * 60)
    
    raw_cookies = input("👇 请在此处右键/Ctrl+V粘贴您的 cookie 字符串:\n> ")
    
    if not raw_cookies.strip():
        print("未检测到输入。请重试。")
        return
    
    if "auth_token" not in raw_cookies:
        print("⚠️ 警告：您粘贴的字符串中没有找到 auth_token，请确保您是在已登录账号的 x.com 页面操作！")
        
    # parse the string
    cookies = []
    # Strip potential surrounding quotes from the console output
    raw_cookies = raw_cookies.strip('\'"') 
    
    pairs = raw_cookies.split(";")
    for p in pairs:
        p = p.strip()
        if "=" in p:
            k, v = p.split("=", 1)
            cookies.append({
                "name": k.strip(),
                "value": v.strip(),
                "domain": ".x.com",
                "path": "/",
                "httpOnly": False, # Basic assumption
                "secure": True,
                "sameSite": "Lax"
            })
            # Also add to twitter.com just in case
            cookies.append({
                "name": k.strip(),
                "value": v.strip(),
                "domain": ".twitter.com",
                "path": "/",
                "httpOnly": False,
                "secure": True,
                "sameSite": "Lax"
            })
            
    auth_data = {
        "cookies": cookies,
        "origins": []
    }
    
    with open("auth.json", "w", encoding="utf-8") as f:
        json.dump(auth_data, f, indent=2)
        
    print("\n✅ 成功！您的登录状态已提取并保存到 auth.json。")
    print("现在 WebUI 将自动使用您自己的账号身份来截取高质量推文！")

if __name__ == "__main__":
    create_auth_file()
