import argparse
import hashlib
import json
import os
import re
import sys
import uuid
import zipfile
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright


def _extract_profile_username(url: str) -> str:
    try:
        parts = url.replace("https://", "").replace("http://", "").split("/")
        if len(parts) < 2:
            return ""
        domain = parts[0].lower()
        if "x.com" not in domain and "twitter.com" not in domain:
            return ""
        user = parts[1].split("?")[0].strip()
        if not user or user in {"home", "explore", "search", "i", "notifications", "messages"}:
            return ""
        return user
    except:
        return ""


_STATUS_RE = re.compile(r"/status/(\d+)")


def _extract_status_id(href: str) -> str:
    if not href:
        return ""
    m = _STATUS_RE.search(href)
    return m.group(1) if m else ""


def _fallback_key(author: str, dt_str: str, text: str) -> str:
    raw = f"{author}|{dt_str}|{(text or '').strip()[:140]}"
    return "fb_" + hashlib.md5(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _save_auth_json_from_cookie_string(raw: str, path: str = "auth.json") -> None:
    text = (raw or "").strip().strip("'\"")
    if not text:
        raise ValueError("Cookie string is empty.")
    if text.lower().startswith("cookie:"):
        text = text.split(":", 1)[1].strip()

    parsed = {}
    for part in text.split(";"):
        p = part.strip()
        if not p or "=" not in p:
            continue
        k, v = p.split("=", 1)
        k = k.strip()
        v = v.strip()
        if k:
            parsed[k] = v

    if "auth_token" not in parsed or "ct0" not in parsed:
        raise ValueError("Cookie must include auth_token and ct0.")

    cookies = []
    for name, value in parsed.items():
        for domain in (".x.com", ".twitter.com"):
            cookies.append({
                "name": name,
                "value": value,
                "domain": domain,
                "path": "/",
                "httpOnly": False,
                "secure": True,
                "sameSite": "Lax"
            })

    with open(path, "w", encoding="utf-8") as f:
        json.dump({"cookies": cookies, "origins": []}, f, ensure_ascii=False, indent=2)


def _auth_status(path: str = "auth.json") -> tuple[bool, int]:
    if not os.path.exists(path):
        return False, 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cookies = data.get("cookies", []) if isinstance(data, dict) else []
        names = {c.get("name") for c in cookies if isinstance(c, dict)}
        return ("auth_token" in names and "ct0" in names), len(cookies)
    except Exception:
        return False, 0


def _wait_media_ready(locator, timeout_ms: int = 5000) -> None:
    """Best-effort wait until images/posters inside a tweet card are loaded."""
    try:
        locator.evaluate(
            """async (node, timeout) => {
                if (!node) return;

                const waitOneImage = (img, leftMs) => new Promise((resolve) => {
                    if (!img) return resolve();
                    if (img.complete && img.naturalWidth > 0) return resolve();

                    let done = false;
                    const finish = () => {
                        if (done) return;
                        done = true;
                        img.removeEventListener('load', finish);
                        img.removeEventListener('error', finish);
                        resolve();
                    };
                    img.addEventListener('load', finish, { once: true });
                    img.addEventListener('error', finish, { once: true });
                    setTimeout(finish, Math.max(0, leftMs));
                });

                const start = Date.now();
                const imgs = Array.from(node.querySelectorAll('img'));
                for (const img of imgs) {
                    const elapsed = Date.now() - start;
                    const left = timeout - elapsed;
                    if (left <= 0) break;
                    await waitOneImage(img, left);
                }
            }""",
            timeout_ms,
        )
    except Exception:
        # Do not block capture if waiting fails.
        pass


def run(url: str, output: str, use_auth: bool,
        headed: bool = False,
        scale_factor: float = 2.0, theme: str = "dark",
        img_format: str = "png", padding: int = 0, bg_color: str = "transparent"):
    with sync_playwright() as p:
        context_args = {}
        if use_auth and os.path.exists("auth.json"):
            context_args["storage_state"] = "auth.json"

        browser = p.chromium.launch(headless=not headed)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=scale_factor,
            color_scheme=theme,
            **context_args
        )

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
            article_locator = page.locator('article[data-testid="tweet"]').first
            article_locator.wait_for(state="visible", timeout=60000)

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

            page.wait_for_timeout(3000)

            if padding > 0:
                print("Injecting beautiful wrapper...")
                page.evaluate(f'''(pad, bg) => {{
                    const article = document.querySelector('article[data-testid="tweet"]');
                    if (article) {{
                        const wrapper = document.createElement('div');
                        wrapper.id = 'xscreenshot-wrapper';
                        wrapper.style.padding = pad + 'px';
                        wrapper.style.background = bg;
                        wrapper.style.display = 'inline-block';
                        wrapper.style.borderRadius = '24px';

                        article.parentNode.insertBefore(wrapper, article);

                        article.style.borderRadius = '16px';
                        article.style.overflow = 'hidden';
                        article.style.border = '1px solid rgba(128,128,128,0.2)';

                        wrapper.appendChild(article);
                    }}
                }}''', padding, bg_color)

                article_locator = page.locator('#xscreenshot-wrapper')
                page.wait_for_timeout(500)

            print(f"Taking screenshot to {output}...")
            _wait_media_ready(article_locator, timeout_ms=6000)
            if img_format.lower() in ['jpeg', 'jpg']:
                article_locator.screenshot(path=output, type="jpeg", quality=90)
            else:
                article_locator.screenshot(path=output, type="png")

            print("Screenshot saved.")

        except Exception as e:
            print(f"Error finding tweet or taking screenshot: {e}")
            page.screenshot(path=output)
            print(f"Saved full page screenshot to {output} instead due to error.")

        finally:
            browser.close()


def run_batch_generator(url: str, output_dir: str, count: int, use_auth: bool,
              headed: bool = False,
              scale_factor: float = 2.0, theme: str = "dark",
              img_format: str = "png", padding: int = 0, bg_color: str = "transparent", job_id: str = "batch", since_date: str = None,
              since_hours: int = None,
              sys_types: list = None, sys_media: list = None, sys_links: list = None):
    max_skip_retries = 10
    max_consecutive_skips = 10

    sys_types = sys_types or ["original", "retweet", "reply", "quote"]
    sys_media = sys_media or ["text", "image", "video"]
    sys_links = sys_links or ["no_links", "has_links"]

    is_all_filters_selected = (
        set(sys_types) == {"original", "retweet", "reply", "quote"} and
        set(sys_media) == {"text", "image", "video"} and
        set(sys_links) == {"no_links", "has_links"}
    )

    original_url = url
    profile_user = _extract_profile_username(url)
    if profile_user and "/status/" not in url:
        url = f"https://x.com/{profile_user}"
        print(f"Using profile posts timeline: {url}")

    target_date = None
    is_count_mode = not since_hours and not since_date
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

        browser = p.chromium.launch(headless=not headed)
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
        captured_count = 0
        processed_hrefs = set()
        transient_failures = {}

        def _goto_and_wait_tweets(target_url: str) -> bool:
            print(f"Navigating to {target_url}...")
            try:
                page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                print(f"Failed to navigate: {e}")
                return False

            print("Waiting for tweets to load...")
            try:
                page.wait_for_selector('article[data-testid="tweet"]', state="visible", timeout=60000)
                page.wait_for_timeout(3000)
                return True
            except Exception as e:
                print(f"Tweet wait timeout on {target_url}: {e}")
                return False

        try:
            loaded = _goto_and_wait_tweets(url)
            if not loaded and url != original_url:
                print(f"Fallback to original timeline: {original_url}")
                loaded = _goto_and_wait_tweets(original_url)
                if loaded:
                    url = original_url

            if not loaded:
                raise Exception("No tweet timeline loaded")

            # Ensure we are in profile "Posts" tab and start from top.
            if profile_user and "/status/" not in url:
                try:
                    posts_tab = page.locator(f'a[role="tab"][href="/{profile_user}"]').first
                    if posts_tab.count() > 0:
                        posts_tab.click(timeout=2500)
                        page.wait_for_timeout(1200)
                    page.evaluate("window.scrollTo(0, 0)")
                    page.wait_for_timeout(400)
                except Exception as e:
                    print(f"Could not force posts tab: {e}")

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
            consecutive_skipped = 0
            stop_due_to_skips = False

            while captured_count < count and consecutive_no_new < 30 and not stop_due_to_skips:
                articles = page.locator('article[data-testid="tweet"]').all()
                found_new_this_scroll = False

                for i in range(len(articles)):
                    if captured_count >= count:
                        break

                    try:
                        author = ""
                        try:
                            author = (articles[i].locator('[data-testid="User-Name"] a[href^="/"]').first.get_attribute("href") or "").strip("/")
                        except:
                            author = ""

                        time_el = articles[i].locator('time[datetime]').first
                        dt_str = None
                        href = None
                        if time_el.count() > 0:
                            dt_str = time_el.get_attribute('datetime')
                            try:
                                href = time_el.evaluate("el => el.closest('a') ? el.closest('a').getAttribute('href') : null")
                            except:
                                href = None

                        if not href:
                            try:
                                href = articles[i].locator('a[href*="/status/"]').first.get_attribute('href')
                            except:
                                href = None

                        status_id = _extract_status_id(href or "")

                        text_content = ""
                        tweet_text_elem = articles[i].locator('[data-testid="tweetText"]')
                        if tweet_text_elem.count() > 0:
                            try:
                                text_content = tweet_text_elem.first.inner_text()
                            except:
                                pass

                        item_key = status_id if status_id else _fallback_key(author, dt_str or "", text_content)
                        if item_key in processed_hrefs:
                            continue

                        found_new_this_scroll = True

                        social_context = articles[i].locator('[data-testid="socialContext"]').first
                        if social_context.count() > 0:
                            try:
                                ctx_text = (social_context.inner_text() or "").strip().lower()
                                if "pinned" in ctx_text:
                                    if not is_count_mode:
                                        print(f"Skipping pinned tweet: {href or item_key}")
                                        processed_hrefs.add(item_key)
                                        consecutive_skipped += 1
                                        if consecutive_skipped >= max_consecutive_skips:
                                            print(f"Reached {max_consecutive_skips} consecutive skipped tweets, stopping batch capture.")
                                            stop_due_to_skips = True
                                            break
                                        continue
                            except:
                                pass

                        tweet_is_old = False
                        tweet_dt = None
                        date_str = ""
                        if dt_str:
                            try:
                                tweet_dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
                                date_str = tweet_dt.strftime("%Y%m%d") + "_"
                                if target_date and tweet_dt < target_date:
                                    tweet_is_old = True
                                    print(f"Skipping old tweet: {tweet_dt}")
                            except:
                                pass

                        if tweet_is_old:
                            processed_hrefs.add(item_key)
                            consecutive_skipped += 1
                            if consecutive_skipped >= max_consecutive_skips:
                                print(f"Reached {max_consecutive_skips} consecutive skipped tweets, stopping batch capture.")
                                stop_due_to_skips = True
                                break
                            continue

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
                            if is_original and "original" not in sys_types:
                                tweet_is_invalid = True
                            if is_retweet and "retweet" not in sys_types:
                                tweet_is_invalid = True
                            if is_reply and "reply" not in sys_types:
                                tweet_is_invalid = True
                            if is_quote and "quote" not in sys_types:
                                tweet_is_invalid = True

                            if is_text_only and "text" not in sys_media:
                                tweet_is_invalid = True
                            if has_image and "image" not in sys_media:
                                tweet_is_invalid = True
                            if has_video and "video" not in sys_media:
                                tweet_is_invalid = True

                            if not has_link and "no_links" not in sys_links:
                                tweet_is_invalid = True
                            if has_link and "has_links" not in sys_links:
                                tweet_is_invalid = True

                            if tweet_is_invalid:
                                print(f"Skipping tweet due to advanced filters (Orig:{is_original}, RT:{is_retweet}, Reply:{is_reply}, Img:{has_image}, Vid:{has_video}, Link:{has_link})")
                                processed_hrefs.add(item_key)
                                consecutive_skipped += 1
                                if consecutive_skipped >= max_consecutive_skips:
                                    print(f"Reached {max_consecutive_skips} consecutive skipped tweets, stopping batch capture.")
                                    stop_due_to_skips = True
                                    break
                                continue

                        articles[i].scroll_into_view_if_needed()
                        page.wait_for_timeout(1000)

                        show_more_link = articles[i].locator('[data-testid="tweet-text-show-more-link"]')
                        if show_more_link.count() > 0:
                            try:
                                show_more_link.first.click(timeout=2000)
                                page.wait_for_timeout(800)
                            except Exception as e:
                                print(f"Could not click 'Show more': {e}")

                        # Re-locate by status id if available after expansion/layout shifts.
                        if status_id:
                            canonical_link = page.locator(
                                f'article[data-testid="tweet"] a[href*="/status/{status_id}"]'
                            ).first
                            if canonical_link.count() > 0:
                                refreshed_article = canonical_link.locator("xpath=ancestor::article[1]").first
                                if refreshed_article.count() > 0:
                                    articles[i] = refreshed_article

                        wrapper_id = f"wrapper_{captured_count}"
                        if padding > 0:
                            try:
                                el_handle = articles[i].element_handle(timeout=1000)
                                if not el_handle:
                                    continue
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
                                target_locator = articles[i]
                        else:
                            target_locator = articles[i]

                        idx = captured_count + 1
                        ext = 'jpg' if img_format.lower() in ['jpeg', 'jpg'] else 'png'

                        username_item = "user"
                        tweet_id = status_id[:15] if status_id else f"{idx:03d}"
                        try:
                            if href:
                                parts = href.strip("/").split("/")
                                if len(parts) >= 3 and "status" in parts:
                                    s_idx = parts.index("status")
                                    username_item = parts[s_idx - 1]
                        except:
                            pass

                        if not username_item and author:
                            username_item = author

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
                            # Ensure bottom action bar has rendered before screenshot.
                            action_bar = articles[i].locator('[role="group"]').first
                            if action_bar.count() > 0:
                                try:
                                    action_bar.wait_for(state="visible", timeout=2000)
                                except Exception:
                                    pass
                            
                            # Wait for media content more aggressively
                            try:
                                # Wait for any images in the tweet to be loaded
                                images = target_locator.locator('img')
                                count_imgs = images.count()
                                if count_imgs > 0:
                                    for idx_img in range(count_imgs):
                                        img = images.nth(idx_img)
                                        # JS wait for complete property
                                        page.evaluate(
                                            "(img) => new Promise((resolve) => { "
                                            "  if (img.complete) resolve(); "
                                            "  else { "
                                            "    img.addEventListener('load', resolve, {once:true}); "
                                            "    img.addEventListener('error', resolve, {once:true}); "
                                            "  } "
                                            "})", 
                                            img.element_handle()
                                        )
                            except Exception as e:
                                print(f"Warning waiting for images: {e}")

                            _wait_media_ready(target_locator, timeout_ms=10000)
                            page.wait_for_timeout(500) # Extra safety buffer

                            target_locator.screenshot(**kwargs)
                            captured_count += 1
                            result_item = {"path": out_path, "filename": out_name, "metadata": metadata}
                            yield result_item
                            
                            processed_hrefs.add(item_key)
                            transient_failures.pop(item_key, None)
                            consecutive_skipped = 0
                            print(f"Captured {out_path}")
                        except Exception as e:
                            fail_count = transient_failures.get(item_key, 0) + 1
                            transient_failures[item_key] = fail_count
                            print(f"Failed to screenshot or add metadata for {href or item_key} (attempt {fail_count}): {e}")
                            if fail_count >= max_skip_retries:
                                print(f"Giving up after repeated failures: {href or item_key}")
                                processed_hrefs.add(item_key)
                                consecutive_skipped += 1
                                if consecutive_skipped >= max_consecutive_skips:
                                    print(f"Reached {max_consecutive_skips} consecutive skipped tweets, stopping batch capture.")
                                    stop_due_to_skips = True
                                    break

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
                        consecutive_skipped += 1
                        if consecutive_skipped >= max_consecutive_skips:
                            print(f"Reached {max_consecutive_skips} consecutive skipped tweets, stopping batch capture.")
                            stop_due_to_skips = True
                            break
                        continue

                if stop_due_to_skips:
                    break

                if not found_new_this_scroll:
                    consecutive_no_new += 1
                else:
                    consecutive_no_new = 0

                page.evaluate("window.scrollBy(0, window.innerHeight * 0.55)")
                page.wait_for_timeout(2500)

        except Exception as e:
            print(f"Error during batch screenshot: {e}")

        finally:
            browser.close()


def run_batch(url: str, output_dir: str, count: int, use_auth: bool,
              headed: bool = False,
              scale_factor: float = 2.0, theme: str = "dark",
              img_format: str = "png", padding: int = 0, bg_color: str = "transparent", job_id: str = "batch", since_date: str = None,
              since_hours: int = None,
              sys_types: list = None, sys_media: list = None, sys_links: list = None):
    return list(run_batch_generator(
        url, output_dir, count, use_auth, headed, scale_factor, theme, img_format, padding, bg_color, job_id, since_date, since_hours, sys_types, sys_media, sys_links
    ))


def _cmd_auth_status(args) -> int:
    ok, cnt = _auth_status(args.auth_file)
    if ok:
        print(f"Logged in. cookies={cnt}")
        return 0
    print(f"Auth invalid or missing. cookies={cnt}")
    return 2


def _cmd_auth_set_cookie(args) -> int:
    raw = args.cookie
    if not raw and args.cookie_file:
        with open(args.cookie_file, "r", encoding="utf-8") as f:
            raw = f.read()
    if not raw:
        print("No cookie provided. Use --cookie or --cookie-file.")
        return 1
    try:
        _save_auth_json_from_cookie_string(raw, args.auth_file)
    except Exception as e:
        print(f"Failed: {e}")
        return 1
    ok, cnt = _auth_status(args.auth_file)
    print(f"Saved {args.auth_file}. auth_ok={ok}, cookies={cnt}")
    return 0 if ok else 2


def _norm_csv(values: str, allowed: set[str], name: str) -> list[str]:
    out = []
    for x in (values or "").split(","):
        v = x.strip().lower()
        if not v:
            continue
        if v not in allowed:
            raise ValueError(f"Invalid {name}: {v}. Allowed: {sorted(list(allowed))}")
        if v not in out:
            out.append(v)
    return out if out else sorted(list(allowed))


def _cmd_batch(args) -> int:
    if args.cookie:
        _save_auth_json_from_cookie_string(args.cookie, args.auth_file)
    if args.since_date and args.since_hours:
        print("Use only one of --since-date or --since-hours.")
        return 1
    if args.since_date:
        try:
            datetime.strptime(args.since_date, "%Y-%m-%d")
        except ValueError:
            print("Invalid --since-date, expected YYYY-MM-DD.")
            return 1
    try:
        sys_types = _norm_csv(args.types, {"original", "retweet", "reply", "quote"}, "types")
        sys_media = _norm_csv(args.media, {"text", "image", "video"}, "media")
        sys_links = _norm_csv(args.links, {"no_links", "has_links"}, "links")
    except ValueError as e:
        print(str(e))
        return 1

    os.makedirs(args.output_dir, exist_ok=True)
    job_id = args.job_id or f"cli_{str(uuid.uuid4())[:8]}"
    captured = run_batch(
        url=args.url,
        output_dir=args.output_dir,
        count=args.count,
        use_auth=not args.no_auth,
        headed=args.headed,
        scale_factor=args.scale_factor,
        theme=args.theme,
        img_format=args.format,
        padding=0,
        bg_color="transparent",
        job_id=job_id,
        since_date=args.since_date,
        since_hours=args.since_hours,
        sys_types=sys_types,
        sys_media=sys_media,
        sys_links=sys_links,
    )

    if not captured:
        print("No tweets captured.")
        return 2

    print(f"Captured {len(captured)} tweet(s):")
    for it in captured:
        print(f"- {it['path']}")

    if args.export_json:
        metadata_path = args.metadata_file or os.path.join(args.output_dir, f"{job_id}_metadata.json")
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump([x.get("metadata", {}) for x in captured], f, ensure_ascii=False, indent=2)
        print(f"Metadata: {metadata_path}")

    if args.zip_output:
        zip_path = args.zip_file or os.path.join(args.output_dir, f"{job_id}.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for it in captured:
                zf.write(it["path"], arcname=it["filename"])
        if args.zip_remove_raw:
            for it in captured:
                try:
                    os.remove(it["path"])
                except Exception:
                    pass
        print(f"Zip: {zip_path}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="screenshot.py",
        description=(
            "Tweetshot CLI for X/Twitter.\n"
            "Manage login cookies and run robust batch capture from profile timelines."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Quick Start:\n"
            "  python screenshot.py auth-status\n"
            "  python screenshot.py auth-set-cookie --cookie \"auth_token=...; ct0=...; twid=...\"\n"
            "  python screenshot.py batch \"https://x.com/username\" --count 5\n"
            "\n"
            "Common Workflows:\n"
            "  python screenshot.py batch \"https://x.com/username\" --since-hours 24 --count 500\n"
            "  python screenshot.py batch \"https://x.com/username\" --types original,reply --media text,image --links has_links\n"
            "  python screenshot.py batch \"https://x.com/username\" --zip-output --export-json --headed\n"
            "\n"
            "Notes:\n"
            "  - Default auth file: auth.json\n"
            "  - Batch mode defaults to headless browser and PNG output\n"
            "  - If both --since-hours and --since-date are set, --since-hours takes priority"
        ),
    )
    p.add_argument("--auth-file", default="auth.json", help="Auth file path (default: auth.json)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s1 = sub.add_parser(
        "auth-status",
        help="Check whether auth.json contains valid login cookies",
        description=(
            "Read auth file and verify required cookies (auth_token + ct0).\n"
            "Returns non-zero when auth is missing/invalid."
        ),
    )
    s1.set_defaults(func=_cmd_auth_status)

    s2 = sub.add_parser(
        "auth-set-cookie",
        help="Write auth.json from a Cookie header string",
        description=(
            "Create/update auth.json from a full Cookie header.\n"
            "Input must include at least auth_token and ct0."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python screenshot.py auth-set-cookie --cookie \"auth_token=...; ct0=...; twid=...\"\n"
            "  python screenshot.py auth-set-cookie --cookie-file cookies.txt"
        ),
    )
    s2.add_argument(
        "--cookie",
        default=None,
        help="Cookie header string (preferred, accepts optional leading 'Cookie:')",
    )
    s2.add_argument("--cookie-file", default=None, help="Path to text file containing the cookie string")
    s2.set_defaults(func=_cmd_auth_set_cookie)

    s3 = sub.add_parser(
        "batch",
        help="Batch capture from profile/timeline",
        description=(
            "Capture tweet cards from a profile timeline (top -> down), with optional\n"
            "time windows, advanced filters, metadata export, and zip packaging.\n"
            "\n"
            "Selection behavior:\n"
            "  - Opens profile posts timeline and scans in visual order\n"
            "  - Skips pinned tweet automatically\n"
            "  - Applies type/media/link filters before capture\n"
            "  - Stops after reaching --count successful captures"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Batch Examples:\n"
            "  python screenshot.py batch \"https://x.com/username\" --count 10\n"
            "  python screenshot.py batch \"https://x.com/username\" --since-date 2026-03-18 --count 500\n"
            "  python screenshot.py batch \"https://x.com/username\" --since-hours 12 --count 500\n"
            "  python screenshot.py batch \"https://x.com/username\" --types original,quote --media image --links has_links\n"
            "  python screenshot.py batch \"https://x.com/username\" --zip-output --zip-remove-raw --export-json\n"
            "\n"
            "Filter Values:\n"
            "  --types: original, retweet, reply, quote\n"
            "  --media: text, image, video\n"
            "  --links: no_links, has_links"
        ),
    )
    s3.add_argument(
        "url",
        help="Profile URL or tweet URL (x.com / twitter.com). For tweet URL, profile timeline is still used.",
    )
    s3.add_argument(
        "--count",
        type=int,
        default=5,
        help="Maximum number of successful captures (default: 5; practical upper bound: 500)",
    )
    s3.add_argument(
        "--since-date",
        default=None,
        help="Capture tweets since UTC date, format YYYY-MM-DD (inclusive from 00:00:00 UTC)",
    )
    s3.add_argument(
        "--since-hours",
        type=int,
        default=None,
        help="Capture tweets within recent N hours (UTC now minus N hours); overrides --since-date if both set",
    )
    s3.add_argument(
        "--types",
        default="original,retweet,reply,quote",
        help="Comma-separated tweet types to keep",
    )
    s3.add_argument(
        "--media",
        default="text,image,video",
        help="Comma-separated media kinds to keep",
    )
    s3.add_argument(
        "--links",
        default="no_links,has_links",
        help="Comma-separated link filter values",
    )
    s3.add_argument(
        "--no-auth",
        action="store_true",
        help="Ignore auth file and run as guest (may reduce accessible content)",
    )
    s3.add_argument("--headed", action="store_true", help="Show browser window for debugging (default: headless)")
    s3.add_argument("--theme", choices=["dark", "light"], default="dark", help="Browser color scheme")
    s3.add_argument("--scale-factor", type=float, default=2.0, help="Device scale factor used for screenshots")
    s3.add_argument("--format", choices=["png", "jpg", "jpeg"], default="png", help="Image output format")
    s3.add_argument("--output-dir", default="outputs", help="Directory for captured images and optional outputs")
    s3.add_argument("--job-id", default=None, help="Custom filename prefix; auto-generated when omitted")
    s3.add_argument(
        "--cookie",
        default=None,
        help="Cookie header string to write into auth file before capture (ignored if --no-auth is set)",
    )
    s3.add_argument("--export-json", action="store_true", help="Write metadata JSON for captured tweets")
    s3.add_argument("--metadata-file", default=None, help="Metadata JSON output path (default: <job_id>_metadata.json)")
    s3.add_argument("--zip-output", action="store_true", help="Package captured images into a zip archive")
    s3.add_argument("--zip-file", default=None, help="Zip output path (default: <job_id>.zip in output dir)")
    s3.add_argument("--zip-remove-raw", action="store_true", help="Delete raw image files after zip is created")
    s3.set_defaults(func=_cmd_batch)
    return p


if __name__ == "__main__":
    # Backward compatibility:
    #   python screenshot.py <url> -o tweet.png
    known_sub = {"auth-status", "auth-set-cookie", "batch"}
    if len(sys.argv) > 1 and sys.argv[1] not in known_sub and not sys.argv[1].startswith("-"):
        parser = argparse.ArgumentParser(description="Capture screenshot of an X (Twitter) post.")
        parser.add_argument("url", help="The URL of the X post.")
        parser.add_argument("-o", "--output", default="tweet.png", help="Output file path (default: tweet.png)")
        parser.add_argument("--no-auth", action="store_true", help="Run without using auth.json (guest mode)")
        parser.add_argument("--headed", action="store_true", help="Show browser window")
        parser.add_argument("--theme", choices=["dark", "light"], default="dark")
        parser.add_argument("--scale-factor", type=float, default=2.0)
        parser.add_argument("--format", choices=["png", "jpg", "jpeg"], default="png")
        args = parser.parse_args()
        run(
            args.url,
            args.output,
            use_auth=not args.no_auth,
            headed=args.headed,
            scale_factor=args.scale_factor,
            theme=args.theme,
            img_format=args.format,
            padding=0,
            bg_color="transparent",
        )
        sys.exit(0)

    cli = _build_parser()
    cli_args = cli.parse_args()
    try:
        code = int(cli_args.func(cli_args))
    except KeyboardInterrupt:
        code = 130
    except Exception as e:
        print(f"Error: {e}")
        code = 1
    sys.exit(code)
