import argparse
import os
import sys
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright

def _extract_profile_username(url: str) -> str:
    try:
        parts = url.replace("https://", "").replace("http://", "").split("/")
        if len(parts) >= 2:
            return parts[1].split("?")[0]
    except:
        pass
    return ""

def run(url: str, output: str, use_auth: bool, 
        scale_factor: float = 2.0, theme: str = "dark", 
        img_format: str = "png", padding: int = 0, bg_color: str = "transparent"):
    with sync_playwright() as p:
        context_args = {}
        if use_auth and os.path.exists("auth.json"):
            context_args["storage_state"] = "auth.json"
        
        # Use headless=True for now. If blocked by anti-bot, we can change to headless=False
        browser = p.chromium.launch(headless=True)
        # Configure context
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=scale_factor,
            color_scheme=theme, # Attempt to set preferred color scheme
            **context_args
        )
        
        # Add a cookie to force theme if color_scheme doesn't perfectly override X's settings
        night_mode_val = "1" if theme == "dark" else "0"
        context.add_cookies([{
            "name": "night_mode",
            "value": night_mode_val,
            "domain": ".x.com",
            "path": "/"
        }, {
            "name": "night_mode",
            "value": night_mode_val,
            "domain": ".twitter.com",
            "path": "/"
        }])
        
        page = context.new_page()
        
        print(f"Navigating to {url}...")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"Failed to navigate: {e}")
            browser.close()
            sys.exit(1)
            
        print("Waiting for tweet element to load...")
        try:
            # Find the first tweet article
            article_locator = page.locator('article[data-testid="tweet"]').first
            article_locator.wait_for(state="visible", timeout=20000)
            
            # Additional logic to hide overlays
            print("Hiding overlays...")
            page.evaluate('''() => {
                const bottoms = document.querySelectorAll('div[data-testid="BottomBar"]');
                bottoms.forEach(b => b.style.display = 'none');
                
                const fixedEls = document.querySelectorAll('div[style*="position: fixed"]');
                for (let el of fixedEls) {
                    if (el.style.bottom === "0px") {
                        el.style.display = 'none';
                    }
                }
            }''')
            
            # Small wait to ensure fonts and images/videos render
            page.wait_for_timeout(3000)
            
            # Ensure wrapper logic if padding is requested
            if padding > 0:
                print("Injecting beautiful wrapper...")
                # We will wrap the article in a new div with padding and background
                page.evaluate(f'''(pad, bg) => {{
                    const article = document.querySelector('article[data-testid="tweet"]');
                    if (article) {{
                        const wrapper = document.createElement('div');
                        wrapper.id = 'xscreenshot-wrapper';
                        wrapper.style.padding = pad + 'px';
                        wrapper.style.background = bg;
                        // To make the background continuous, ensure it's a block
                        wrapper.style.display = 'inline-block';
                        wrapper.style.borderRadius = '24px';
                        
                        // Insert wrapper before article, then move article inside
                        article.parentNode.insertBefore(wrapper, article);
                        
                        // X's article usually has border radius that might look weird on transparent
                        article.style.borderRadius = '16px';
                        article.style.overflow = 'hidden';
                        article.style.border = '1px solid rgba(128,128,128,0.2)';
                        
                        wrapper.appendChild(article);
                    }}
                }}''', padding, bg_color)
                
                # Change the locator to our new wrapper
                article_locator = page.locator('#xscreenshot-wrapper')
                page.wait_for_timeout(500)
            
            # Use 'jpeg' if requested and 'png' otherwise. 
            # Note: Playwright's element.screenshot only supports jpeg/png.
            # quality is only valid for jpeg.
            print(f"Taking screenshot to {output}...")
            if img_format.lower() == 'jpeg' or img_format.lower() == 'jpg':
                article_locator.screenshot(path=output, type="jpeg", quality=90)
            else:
                article_locator.screenshot(path=output, type="png")
                
            print("Screenshot saved.")
            
        except Exception as e:
            print(f"Error finding tweet or taking screenshot: {e}")
            # Fallback
            page.screenshot(path=output)
            print(f"Saved full page screenshot to {output} instead due to error.")
            
        finally:
            browser.close()

def run_batch(url: str, output_dir: str, count: int, use_auth: bool,
              scale_factor: float = 2.0, theme: str = "dark", 
              img_format: str = "png", padding: int = 0, bg_color: str = "transparent", job_id: str = "batch", since_date: str = None,
              since_hours: int = None,
              sys_types: list = None, sys_media: list = None, sys_links: list = None):
    
    all_types = {"original", "retweet", "reply", "quote"}
    all_media = {"text", "image", "video"}
    all_links = {"no_links", "has_links"}

    def normalize(selected, all_options):
        if not selected:
            return set(all_options)
        normalized = {str(x).strip().lower() for x in selected if str(x).strip()}
        normalized = normalized.intersection(all_options)
        return normalized if normalized else set(all_options)

    sys_types = normalize(sys_types, all_types)
    sys_media = normalize(sys_media, all_media)
    sys_links = normalize(sys_links, all_links)

    is_all_filters_selected = (
        sys_types.issuperset(all_types) and
        sys_media.issuperset(all_media) and
        sys_links.issuperset(all_links)
    )
    print(f"Advanced filters all-selected mode: {is_all_filters_selected}")
    print(f"Effective filters -> types:{sorted(sys_types)} media:{sorted(sys_media)} links:{sorted(sys_links)}")

    def normalize_canonical_status_href(href: str):
        if not href:
            return None
        h = href.split("?")[0].strip()
        if h.startswith("https://x.com/") or h.startswith("http://x.com/") or h.startswith("https://twitter.com/") or h.startswith("http://twitter.com/"):
            try:
                h = "/" + h.split("/", 3)[3]
            except:
                return None
        # Canonical only: /{user}/status/{digits}
        parts = h.strip("/").split("/")
        if len(parts) == 3 and parts[1] == "status" and parts[2].isdigit():
            return "/" + "/".join(parts)
        return None
    
    target_date = None
    if since_hours:
        target_date = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        print(f"Target since hours (UTC timestamp): {since_hours}h -> {target_date.isoformat()}")
    elif since_date:
        try:
            target_date = datetime.fromisoformat(f"{since_date}T00:00:00+00:00")
            print(f"Target since date: {target_date}")
        except Exception as e:
            print(f"Failed to parse since_date {since_date}: {e}")

    with sync_playwright() as p:
        context_args = {}
        if use_auth and os.path.exists("auth.json"):
            context_args["storage_state"] = "auth.json"
            
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=scale_factor,
            color_scheme=theme,
            **context_args
        )
        
        night_mode_val = "1" if theme == "dark" else "0"
        context.add_cookies([
            {"name": "night_mode", "value": night_mode_val, "domain": ".x.com", "path": "/"},
            {"name": "night_mode", "value": night_mode_val, "domain": ".twitter.com", "path": "/"}
        ])
        
        page = context.new_page()
        print(f"Navigating to {url}...")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"Failed to navigate: {e}")
            browser.close()
            return []
            
        print("Waiting for tweets to load...")
        captured_paths = []
        processed_keys = set()
        profile_username = _extract_profile_username(url)
        
        try:
            page.wait_for_selector('article[data-testid="tweet"]', state="visible", timeout=20000)
            page.wait_for_timeout(3000)
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(500)

            # Force focus on the profile Posts timeline to avoid landing in other tabs or stale positions.
            if profile_username:
                try:
                    posts_tab = page.locator(f'a[role="tab"][href="/{profile_username}"]').first
                    if posts_tab.count() > 0:
                        posts_tab.click(timeout=2000)
                        page.wait_for_timeout(1200)
                        page.wait_for_selector('article[data-testid="tweet"]', state="visible", timeout=10000)
                        page.evaluate("window.scrollTo(0, 0)")
                        page.wait_for_timeout(400)
                except:
                    pass
            
            # Hide overlays
            page.evaluate('''() => {
                const bottoms = document.querySelectorAll('div[data-testid="BottomBar"]');
                bottoms.forEach(b => b.style.display = 'none');
                const fixedEls = document.querySelectorAll('div[style*="position: fixed"]');
                for (let el of fixedEls) {
                    if (el.style.bottom === "0px") {
                        el.style.display = 'none';
                    }
                }
            }''')

            os.makedirs(output_dir, exist_ok=True)
            consecutive_no_new = 0

            while len(captured_paths) < count and consecutive_no_new < 5:
                # Process tweets in the same order they appear on page (top -> bottom).
                articles = page.locator('article[data-testid="tweet"]').all()
                found_new_this_scroll = False
                
                for i in range(len(articles)):
                    if len(captured_paths) >= count:
                        break
                        
                    try:
                        # Resolve canonical status href/timestamp by choosing the top-most canonical status anchor.
                        # This avoids picking quoted/embedded tweet status links lower in the card.
                        href = None
                        dt_str = None
                        meta_pick = articles[i].evaluate('''node => {
                            const canonicalPath = /^\\/[^\\/]+\\/status\\/\\d+(?:\\?.*)?$/;
                            const canonicalAbs = /^https?:\\/\\/(?:x|twitter)\\.com\\/[^\\/]+\\/status\\/\\d+(?:\\?.*)?$/i;
                            const isCanonical = (h) => canonicalPath.test(h) || canonicalAbs.test(h);

                            const anchors = Array.from(node.querySelectorAll('a[href*="/status/"]'));
                            const candidates = [];
                            for (const a of anchors) {
                                const rawHref = (a.getAttribute('href') || '').trim();
                                if (!rawHref || !isCanonical(rawHref)) continue;
                                let dt = null;

                                // Case A: <a ...><time datetime=...></time></a>
                                const tIn = a.querySelector('time[datetime]');
                                if (tIn) dt = tIn.getAttribute('datetime');

                                // Case B: <time datetime=...></time><a ...>
                                if (!dt) {
                                    const prev = a.previousElementSibling;
                                    if (prev && prev.tagName === 'TIME' && prev.getAttribute('datetime')) {
                                        dt = prev.getAttribute('datetime');
                                    }
                                }

                                candidates.push({ href: rawHref, datetime: dt, top: a.getBoundingClientRect().top });
                            }

                            if (candidates.length === 0) return null;
                            candidates.sort((x, y) => x.top - y.top);
                            const withDt = candidates.find(c => !!c.datetime);
                            return withDt || candidates[0];
                        }''')
                        if meta_pick:
                            href = normalize_canonical_status_href(meta_pick.get("href"))
                            dt_str = meta_pick.get("datetime")

                        if not href:
                            # Ignore non-canonical cards/modules for count mode.
                            continue
                        print(f"Candidate tweet: {href}")

                        if not dt_str:
                            try:
                                time_fallback = articles[i].locator('time[datetime]').first
                                if time_fallback.count() > 0:
                                    dt_str = time_fallback.get_attribute('datetime')
                            except:
                                pass

                        dedupe_key = href
                        if dedupe_key in processed_keys:
                            continue
                        processed_keys.add(dedupe_key)

                        # Skip pinned posts; for count mode user usually expects latest chronological posts.
                        try:
                            social_ctx = articles[i].locator('[data-testid="socialContext"]').first
                            if social_ctx.count() > 0:
                                social_text = (social_ctx.inner_text() or "").lower()
                                if "pinned" in social_text or "置顶" in social_text:
                                    print(f"Skipping pinned tweet: {href}")
                                    continue
                        except:
                            pass
                            
                        found_new_this_scroll = True
                        
                        tweet_is_old = False
                        tweet_dt = None
                        date_str = ""
                        try:
                            if dt_str:
                                tweet_dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
                                date_str = tweet_dt.strftime("%Y%m%d") + "_"
                                if target_date and tweet_dt < target_date:
                                    tweet_is_old = True
                                    print(f"Skipping old tweet: {tweet_dt} ({href})")
                            elif target_date:
                                print("No canonical tweet timestamp found for this card; skip age filter for this item.")
                        except:
                            pass
                                        
                        if tweet_is_old:
                            continue
                            
                        # Evaluate Advanced Filters
                        is_retweet = articles[i].locator('[data-testid="socialContext"]').count() > 0
                        is_reply = articles[i].locator('div:has-text("Replying to")').count() > 0
                        is_quote = articles[i].locator('time').count() >= 2
                        is_original = not is_retweet and not is_reply and not is_quote

                        has_image = articles[i].locator('[data-testid="tweetPhoto"]').count() > 0
                        has_video = articles[i].locator('[data-testid="videoPlayer"]').count() > 0
                        is_text_only = not has_image and not has_video

                        has_link = articles[i].locator('[data-testid="card.wrapper"]').count() > 0 or articles[i].locator('a[target="_blank"][href^="http"]').count() > 0

                        if not is_all_filters_selected:
                            tweet_is_invalid = False
                            # Type Check
                            if is_original and "original" not in sys_types: tweet_is_invalid = True
                            if is_retweet and "retweet" not in sys_types: tweet_is_invalid = True
                            if is_reply and "reply" not in sys_types: tweet_is_invalid = True
                            if is_quote and "quote" not in sys_types: tweet_is_invalid = True

                            # Media Check
                            if is_text_only and "text" not in sys_media: tweet_is_invalid = True
                            if has_image and "image" not in sys_media: tweet_is_invalid = True
                            if has_video and "video" not in sys_media: tweet_is_invalid = True

                            # Link Check
                            if not has_link and "no_links" not in sys_links: tweet_is_invalid = True
                            if has_link and "has_links" not in sys_links: tweet_is_invalid = True

                            if tweet_is_invalid:
                                print(f"Skipping tweet due to advanced filters: {href} (Orig:{is_original}, RT:{is_retweet}, Reply:{is_reply}, Img:{has_image}, Vid:{has_video}, Link:{has_link})")
                                continue
                        
                        # Scroll to it
                        tweet_locator = articles[i]
                        tweet_locator.scroll_into_view_if_needed()
                        page.wait_for_timeout(1000) # let images load
                        
                        # Default mode: do NOT click "Show more" to keep locator/layout stable.
                        page.wait_for_timeout(300)
                                
                        # Apply wrapper if needed
                        wrapper_id = f"wrapper_{len(captured_paths)}"
                        if padding > 0:
                            # Need to evaluate carefully because handles can be stale if react re-renders
                            try:
                                el_handle = tweet_locator.element_handle(timeout=1000)
                                if not el_handle: continue
                                page.evaluate(f'''([article_el, pad, bg, w_id]) => {{
                                    if (!article_el) return;
                                    const wrapper = document.createElement('div');
                                    wrapper.id = w_id;
                                    wrapper.style.padding = pad + 'px';
                                    wrapper.style.background = bg;
                                    wrapper.style.display = 'inline-block';
                                    wrapper.style.borderRadius = '24px';
                                    
                                    article_el.parentNode.insertBefore(wrapper, article_el);
                                    article_el.style.borderRadius = '16px';
                                    article_el.style.overflow = 'hidden';
                                    article_el.style.border = '1px solid rgba(128,128,128,0.2)';
                                    wrapper.appendChild(article_el);
                                }}''', [el_handle, padding, bg_color, wrapper_id])
                                target_locator = page.locator(f'#{wrapper_id}')
                                page.wait_for_timeout(500)
                            except:
                                target_locator = tweet_locator
                        else:
                            target_locator = tweet_locator
                            
                        # Screenshot
                        idx = len(captured_paths) + 1
                        ext = 'jpg' if img_format.lower() in ['jpeg', 'jpg'] else 'png'
                        
                        # Parse username and tweet_id
                        username_item = "user"
                        tweet_id = f"{idx:03d}"
                        if "/status/" in href:
                            try:
                                parts = href.strip("/").split("/")
                                if len(parts) >= 3 and "status" in parts:
                                    s_idx = parts.index("status")
                                    username_item = parts[s_idx-1]
                                    tweet_id = parts[s_idx+1].split("?")[0][:15] # limit length just in case
                            except:
                                pass
                                    # Extract Text Metadata
                        text_content = ""
                        tweet_text_elem = tweet_locator.locator('[data-testid="tweetText"]')
                        if tweet_text_elem.count() > 0:
                            try:
                                text_content = tweet_text_elem.first.inner_text()
                            except:
                                pass
                                
                        out_name = f"{username_item}_{tweet_id}.{ext}"
                        out_path = os.path.join(output_dir, f"{job_id}_{out_name}")

                        metadata = {
                            "tweet_id": tweet_id,
                            "author": username_item,
                            "date": date_str.strip('_'),
                            "timestamp_utc": tweet_dt.isoformat() if tweet_dt else None,
                            "text": text_content,
                            "is_original": is_original,
                            "is_retweet": is_retweet,
                            "is_reply": is_reply,
                            "is_quote": is_quote,
                            "has_image": has_image,
                            "has_video": has_video,
                            "has_external_link": has_link,
                            "image_filename": out_name
                        }
                        
                        kwargs = {"path": out_path}
                        if ext == 'jpg':
                            kwargs["type"] = "jpeg"
                            kwargs["quality"] = 90
                        else:
                            kwargs["type"] = "png"
                            
                        try:
                            # Extra-long cards can exceed screenshot height limits; shrink locally if needed.
                            try:
                                box = target_locator.bounding_box()
                                if box and box.get("height", 0) > 12000:
                                    print(f"Tweet card too tall ({int(box['height'])}px), applying temporary zoom for: {href}")
                                    tweet_locator.evaluate('''node => {
                                        node.style.zoom = '0.78';
                                        node.style.transformOrigin = 'top left';
                                    }''')
                                    page.wait_for_timeout(250)
                            except Exception as e:
                                print(f"Height pre-check failed for {href}: {e}")

                            # Hide UI elements
                            tweet_locator.evaluate('''node => {
                                const actionBars = node.querySelectorAll('[role="group"]');
                                actionBars.forEach(bar => {
                                    if (bar.id && bar.id.includes('hidden')) return;
                                    bar.style.opacity = '0';
                                    bar.style.height = '0';
                                    bar.style.overflow = 'hidden';
                                });
                            }''')
                            
                            page.wait_for_timeout(200)
                            
                            target_locator.screenshot(**kwargs)
                            captured_paths.append({"path": out_path, "filename": out_name, "metadata": metadata})
                            print(f"Captured {out_path}")
                        except Exception as e:
                            print(f"Failed to screenshot or add metadata for {href}: {e}")
                        
                        # Un-wrap to not mess up react's DOM tracking if we scroll back
                        if padding > 0:
                            page.evaluate(f'''([w_id]) => {{
                                const wrapper = document.getElementById(w_id);
                                if (wrapper) {{
                                    const article = wrapper.firstChild;
                                    wrapper.parentNode.insertBefore(article, wrapper);
                                    wrapper.remove();
                                }}
                            }}''', [wrapper_id])
                            
                    except Exception as e:
                        print(f"Skipping article due to error: {e}")
                        continue
                
                if not found_new_this_scroll:
                    consecutive_no_new += 1
                else:
                    consecutive_no_new = 0
                    
                # scroll down a bit
                page.evaluate("window.scrollBy(0, window.innerHeight * 0.8)")
                page.wait_for_timeout(2000)
                
        except Exception as e:
            print(f"Error during batch screenshot: {e}")
            
        finally:
            browser.close()
            
        return captured_paths

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Capture screenshot of an X (Twitter) post.")
    parser.add_argument("url", help="The URL of the X post.")
    parser.add_argument("-o", "--output", default="tweet.png", help="Output file path (default: tweet.png)")
    parser.add_argument("--no-auth", action="store_true", help="Run without using auth.json (guest mode)")
    
    args = parser.parse_args()
    run(args.url, args.output, use_auth=not args.no_auth)
