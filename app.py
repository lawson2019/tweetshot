from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
from typing import Optional
import json
import os
import uuid
import zipfile
from screenshot import run as take_screenshot, run_batch, run_batch_generator

app = FastAPI(title="X Screenshot API")

# Ensure static and output dirs exist
os.makedirs("static", exist_ok=True)
os.makedirs("outputs", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")



class BatchRequest(BaseModel):
    url: str
    count: int = 5
    since_hours: Optional[int] = None
    scale_factor: float = 2.0
    theme: str = "dark"
    img_format: str = "png"
    padding: int = 0
    bg_color: str = "transparent"
    zip_output: bool = False
    export_json: bool = False
    headed: bool = False
    cookie_string: Optional[str] = None
    since_date: Optional[str] = None
    sys_types: Optional[list[str]] = None
    sys_media: Optional[list[str]] = None
    sys_links: Optional[list[str]] = None


def _save_auth_from_cookie_string(raw: str) -> None:
    cookie_text = (raw or "").strip().strip("'\"")
    if not cookie_text:
        raise HTTPException(status_code=400, detail="Cookie string is empty.")
    if cookie_text.lower().startswith("cookie:"):
        cookie_text = cookie_text.split(":", 1)[1].strip()

    parsed: dict[str, str] = {}
    for part in cookie_text.split(";"):
        p = part.strip()
        if not p or "=" not in p:
            continue
        k, v = p.split("=", 1)
        k = k.strip()
        v = v.strip()
        if k:
            parsed[k] = v

    if "auth_token" not in parsed or "ct0" not in parsed:
        raise HTTPException(status_code=400, detail="Cookie missing auth_token/ct0. Please paste full Request Cookie header from logged-in x.com.")

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

    auth_data = {"cookies": cookies, "origins": []}
    with open("auth.json", "w", encoding="utf-8") as f:
        json.dump(auth_data, f, ensure_ascii=False, indent=2)


def _read_auth_status() -> dict:
    path = "auth.json"
    if not os.path.exists(path):
        return {"logged_in": False, "has_auth_file": False, "cookie_count": 0}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cookies = data.get("cookies", []) if isinstance(data, dict) else []
        names = {c.get("name") for c in cookies if isinstance(c, dict)}
        logged_in = "auth_token" in names and "ct0" in names
        return {
            "logged_in": logged_in,
            "has_auth_file": True,
            "cookie_count": len(cookies),
            "updated_at": int(os.path.getmtime(path)),
        }
    except Exception:
        return {"logged_in": False, "has_auth_file": True, "cookie_count": 0}

@app.get("/")
def read_root():
    response = FileResponse("static/index.html")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/api/auth/status")
def get_auth_status():
    return JSONResponse(content=_read_auth_status())



@app.post("/api/screenshot/batch")
def create_batch_screenshot(req: BatchRequest):
    if not req.url or "x.com" not in req.url and "twitter.com" not in req.url:
        raise HTTPException(status_code=400, detail="Invalid X (Twitter) URL provided.")
    if req.count <= 0 or req.count > 500:
        raise HTTPException(status_code=400, detail="Count must be between 1 and 500.")
        
    username = "batch"
    try:
        parts = req.url.replace("https://", "").replace("http://", "").split("/")
        if len(parts) >= 2:
            username = parts[1].split("?")[0]
    except:
        pass
        
    job_id = f"{username}_{str(uuid.uuid4())[:6]}"
    # We will output directly to 'outputs/' and prefix with job_id to avoid creating a folder
    
    try:
        if req.cookie_string and req.cookie_string.strip():
            _save_auth_from_cookie_string(req.cookie_string)

        captured = run_batch(
            url=req.url,
            output_dir="outputs", # Flat directory
            count=req.count,
            use_auth=True,
            headed=req.headed,
            scale_factor=req.scale_factor,
            theme=req.theme,
            img_format=req.img_format,
            padding=req.padding,
            bg_color=req.bg_color,
            job_id=job_id, # Passing job_id to prefix the files
            since_date=req.since_date,
            since_hours=req.since_hours,
            sys_types=req.sys_types,
            sys_media=req.sys_media,
            sys_links=req.sys_links
        )
        
        if not captured:
            raise HTTPException(status_code=500, detail="No tweets could be captured.")
            
        if req.export_json:
            metadata_filename = f"{job_id}_metadata.json"
            metadata_path = f"outputs/{metadata_filename}"
            metadata_content = [x["metadata"] for x in captured]
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(metadata_content, f, ensure_ascii=False, indent=2)
            
        if req.zip_output:
            zip_path = f"outputs/{job_id}.zip"
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for item in captured:
                    zipf.write(item["path"], arcname=item["filename"])
                    os.remove(item["path"]) # Cleanup raw files after zipping
                
                if req.export_json:
                    zipf.write(metadata_path, arcname=metadata_filename)
                    os.remove(metadata_path) # Cleanup metadata file after zipping
                    
            if not os.path.exists(zip_path):
                raise HTTPException(status_code=500, detail="Batch Zip failed, file not created.")
                
            return JSONResponse(content={
                "id": job_id, 
                "url": f"/api/zip/{job_id}", 
                "is_zip": True,
                "filename": f"{job_id}.zip",
                "metadata": [x["metadata"] for x in captured]
            })
        else:
            # Return list of API urls to download individually
            images_data = []
            for item in captured:
                file_id = os.path.basename(item["path"]).split('.')[0]
                ext = item["path"].split('.')[-1]
                images_data.append({
                    "url": f"/api/image/{file_id}?ext={ext}",
                    "filename": item["filename"]
                })
            return JSONResponse(content={"id": job_id, "images": images_data, "is_zip": False, "metadata": [x["metadata"] for x in captured]})
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch screenshot failed: {str(e)}")

@app.post("/api/screenshot/batch-stream")
def create_batch_screenshot_stream(req: BatchRequest):
    if not req.url or "x.com" not in req.url and "twitter.com" not in req.url:
        raise HTTPException(status_code=400, detail="Invalid X (Twitter) URL provided.")
    if req.count <= 0 or req.count > 500:
        raise HTTPException(status_code=400, detail="Count must be between 1 and 500.")
        
    username = "batch"
    try:
        parts = req.url.replace("https://", "").replace("http://", "").split("/")
        if len(parts) >= 2:
            username = parts[1].split("?")[0]
    except:
        pass
        
    job_id = f"{username}_{str(uuid.uuid4())[:6]}"
    
    def stream_generator():
        try:
            if req.cookie_string and req.cookie_string.strip():
                _save_auth_from_cookie_string(req.cookie_string)

            captured = []
            
            # Use the generator version
            gen = run_batch_generator(
                url=req.url,
                output_dir="outputs",
                count=req.count,
                use_auth=True,
                headed=req.headed,
                scale_factor=req.scale_factor,
                theme=req.theme,
                img_format=req.img_format,
                padding=req.padding,
                bg_color=req.bg_color,
                job_id=job_id,
                since_date=req.since_date,
                since_hours=req.since_hours,
                sys_types=req.sys_types,
                sys_media=req.sys_media,
                sys_links=req.sys_links
            )
            
            for item in gen:
                captured.append(item)
                file_id = os.path.basename(item["path"]).split('.')[0]
                ext = item["path"].split('.')[-1]
                data = {
                    "type": "image",
                    "url": f"/api/image/{file_id}?ext={ext}",
                    "filename": item["filename"],
                    "metadata": item["metadata"]
                }
                yield json.dumps(data) + "\n"

            if not captured:
                yield json.dumps({"type": "error", "detail": "No tweets could be captured."}) + "\n"
                return

            metadata_filename = f"{job_id}_metadata.json"
            metadata_path = f"outputs/{metadata_filename}"
            
            if req.export_json:
                metadata_content = [x["metadata"] for x in captured]
                with open(metadata_path, "w", encoding="utf-8") as f:
                    json.dump(metadata_content, f, ensure_ascii=False, indent=2)
                
            zip_url = None
            if req.zip_output:
                zip_path = f"outputs/{job_id}.zip"
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for item in captured:
                        zipf.write(item["path"], arcname=item["filename"])
                        os.remove(item["path"]) # Cleanup raw files after zipping
                    
                    if req.export_json:
                        zipf.write(metadata_path, arcname=metadata_filename)
                        os.remove(metadata_path) # Cleanup metadata file after zipping
                
                if os.path.exists(zip_path):
                    zip_url = f"/api/zip/{job_id}"
            
            yield json.dumps({
                "type": "complete",
                "count": len(captured),
                "zip_url": zip_url,
                "job_id": job_id
            }) + "\n"
            
        except Exception as e:
            yield json.dumps({"type": "error", "detail": str(e)}) + "\n"

    return StreamingResponse(stream_generator(), media_type="application/x-ndjson")

@app.get("/api/image/{file_id}")
def get_image(file_id: str, ext: str = "png"):
    file_path = f"outputs/{file_id}.{ext}"
    media_type = "image/jpeg" if ext in ["jpg", "jpeg"] else "image/png"
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type=media_type)
    raise HTTPException(status_code=404, detail="Image not found")

@app.get("/api/zip/{job_id}")
def get_zip(job_id: str):
    file_path = f"outputs/{job_id}.zip"
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type="application/zip", filename=f"tweets_{job_id[:8]}.zip")
    raise HTTPException(status_code=404, detail="Zip file not found")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
