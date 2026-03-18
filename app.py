from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional
import os
import uuid
import zipfile
import shutil
from screenshot import run as take_screenshot, run_batch

app = FastAPI(title="tweetshot")

# Ensure static and output dirs exist
os.makedirs("static", exist_ok=True)
os.makedirs("outputs", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")



class BatchRequest(BaseModel):
    url: str
    count: int = 5
    scale_factor: float = 2.0
    theme: str = "dark"
    img_format: str = "png"
    padding: int = 0
    bg_color: str = "transparent"
    zip_output: bool = False
    export_json: bool = False
    since_date: Optional[str] = None
    since_hours: Optional[int] = None
    sys_types: list[str] = ["original", "retweet", "reply", "quote"]
    sys_media: list[str] = ["text", "image", "video"]
    sys_links: list[str] = ["no_links", "has_links"]

@app.get("/")
def read_root():
    return FileResponse("static/index.html")



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
        captured = run_batch(
            url=req.url,
            output_dir="outputs", # Flat directory
            count=req.count,
            use_auth=True,
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
        
        if not captured:
            reason = "No tweets could be captured."
            if req.since_hours:
                reason += f" No matching tweets found within the last {req.since_hours} hour(s)."
            elif req.since_date:
                reason += f" No matching tweets found since {req.since_date} (UTC)."
            reason += " Try widening time range or relaxing advanced filters."
            raise HTTPException(status_code=422, detail=reason)
            
        if req.zip_output:
            zip_path = f"outputs/{job_id}.zip"
            metadata_list = [item["metadata"] for item in captured if "metadata" in item]
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for item in captured:
                    zipf.write(item["path"], arcname=item["filename"])
                    
                    if req.export_json and "metadata" in item:
                        import json
                        json_name = f"{item['filename'].rsplit('.', 1)[0]}.json"
                        metadata_str = json.dumps(item["metadata"], ensure_ascii=False, indent=4)
                        zipf.writestr(json_name, metadata_str)
                        
                    os.remove(item["path"]) # Cleanup raw files after zipping

            resp_content = {"id": job_id, "url": f"/api/zip/{job_id}", "filename": f"{job_id}.zip", "is_zip": True}
            if req.export_json:
                resp_content["metadata"] = metadata_list
            return JSONResponse(content=resp_content)
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
                
            resp_content = {"id": job_id, "images": images_data, "is_zip": False}
            if req.export_json:
                resp_content["metadata"] = [item["metadata"] for item in captured if "metadata" in item]
                
            return JSONResponse(content=resp_content)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch screenshot failed: {str(e)}")

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

