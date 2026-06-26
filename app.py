from flask import Flask, request, jsonify
import re
import json
import time
import random
import requests
from bs4 import BeautifulSoup
from typing import Dict, List, Optional, Any
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes


class InstagramDownloader:
    def __init__(self, delay_mode: str = "random", fixed_delay: float = 1.5, delay_min: float = 1.0,
                 delay_max: float = 1.0):
        """
        Initialize Instagram Downloader
        
        Args:
            delay_mode: "fixed" or "random"
            fixed_delay: Fixed delay in seconds
            delay_min: Minimum delay for random mode
            delay_max: Maximum delay for random mode
        """
        self.delay_mode = delay_mode
        self.fixed_delay = fixed_delay
        self.delay_min = delay_min
        self.delay_max = delay_max
        
        # Session for maintaining cookies/headers
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "max-age=0",
            "Sec-CH-UA": '"Not)A;Brand";v="8", "Chromium";v="138", "Brave";v="138"',
            "Sec-CH-UA-Mobile": "?0",
            "Sec-CH-UA-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-User": "?1",
            "Sec-GPC": "1",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
        })

    def _delay_request(self):
        """Apply delay based on configuration"""
        if self.delay_mode == "random":
            sec = random.uniform(self.delay_min, self.delay_max)
        else:
            sec = self.fixed_delay
        time.sleep(sec)

    def _validate_instagram_url(self, url: str) -> bool:
        """Validate if URL is a valid Instagram URL"""
        if not url:
            return False
        
        # First check if it's an Instagram URL
        pattern = r'^https?://(www\.)?instagram\.com/.*'
        if not re.match(pattern, url, re.IGNORECASE):
            return False
        
        # Extract the path without query parameters
        from urllib.parse import urlparse
        parsed = urlparse(url)
        path = parsed.path.rstrip('/')
        
        # Check allowed URL types (without query parameters)
        valid_patterns = [
            r'^/[-_A-Za-z0-9]+$',  # profile
            r'^/p/[-_A-Za-z0-9]+$',  # post
            r'^/reel/[-_A-Za-z0-9]+$',  # reel
            r'^/stories/[-_A-Za-z0-9]+/[-_A-Za-z0-9]+$',  # story
            r'^/tv/[-_A-Za-z0-9]+$',  # IGTV
            r'^/guide/[-_A-Za-z0-9]+$',  # Guide
        ]
        
        for pattern in valid_patterns:
            if re.match(pattern, path):
                return True
        
        return False

    def _extract_js_variable(self, name: str, source: str) -> Optional[str]:
        """Extract JavaScript variable value from source"""
        pattern = re.escape(name) + r'\s*=\s*"([^"]+)"'
        match = re.search(pattern, source)
        return match.group(1) if match else None

    def _parse_media_html(self, html_content: str) -> Dict[str, Any]:
        """
        Parse the HTML content to extract media information
        
        Returns:
            Dict with images and videos information
        """
        result = {
            "results_images": 0,
            "results_videos": 0,
            "images": [],
            "videos": []
        }
        
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Find all download items
        download_items = soup.select('ul.download-box li')
        
        for item in download_items:
            # Get thumbnail
            thumb_img = item.select_one('div.download-items__thumb img')
            thumb_url = None
            if thumb_img:
                src = thumb_img.get('src', '')
                data_src = thumb_img.get('data-src', '')
                if not src or src == '/imgs/loader.gif':
                    thumb_url = data_src or src
                else:
                    thumb_url = src
            
            # Check icon for media type
            icon = item.select_one('div.download-items__thumb i')
            icon_class = icon.get('class', []) if icon else []
            icon_class_str = ' '.join(icon_class) if icon_class else ''
            
            is_image = 'icon-dlimage' in icon_class_str
            is_video = 'icon-dlvideo' in icon_class_str
            
            # Find download buttons
            btn_links = item.select('div.download-items__btn a')
            
            # Find video link
            video_href = None
            for link in btn_links:
                if link.has_attr('video'):
                    video_href = link.get('href')
                    is_video = True
                    break
                if 'download video' in link.get_text().lower():
                    video_href = link.get('href')
                    is_video = True
                    break
            
            # If no video link found but icon says video, use first link
            if is_video and not video_href and btn_links:
                video_href = btn_links[0].get('href')
            
            # Get resolutions from select options
            resolutions = []
            select = item.select_one('div.photo-option select')
            if select:
                for option in select.find_all('option'):
                    label = option.get_text().strip()
                    value = option.get('value', '')
                    if label and value:
                        resolutions.append({label: value})
            
            if is_image:
                result["results_images"] += 1
                result["images"].append({
                    "thumb_url": thumb_url,
                    "resolutions_count": len(resolutions),
                    "resolution": resolutions
                })
            elif is_video:
                result["results_videos"] += 1
                result["videos"].append({
                    "thumb_url": thumb_url,
                    "video_src": video_href,
                    "resolutions_count": len(resolutions),
                    "resolution": resolutions
                })
        
        return result

    def download_instagram_content(self, target_url: str) -> Dict[str, Any]:
        """
        Main method to download Instagram content
        
        Args:
            target_url: Instagram URL (profile, post, reel, or story)
            
        Returns:
            Dict with success status and media information
        """
        # Validate URL
        if not target_url:
            return {"error": "Missing 'url' parameter"}
        
        target_url = target_url.strip()
        
        if not self._validate_instagram_url(target_url):
            return {"error": "URL must be a valid Instagram link. Only profile, post, reel, or story URLs are supported."}
        
        try:
            # STEP 1: Get initial page with tokens
            print(f"Fetching initial page for {target_url}...")
            response = self.session.get("https://saveinsta.to/en/highlights")
            response.raise_for_status()
        except requests.RequestException as e:
            return {"error": f"Failed to fetch initial page: {str(e)}"}
        
        html_content = response.text
        
        # Extract JavaScript variables
        script_pattern = r'<script[^>]*>var\s+k_url_search="[^"]+"(.*?)</script>'
        script_match = re.search(script_pattern, html_content, re.DOTALL)
        
        if not script_match:
            return {"error": "JS token block not found"}
        
        script_block = script_match.group(1)
        
        k_prefix_name = self._extract_js_variable("k_prefix_name", script_block)
        k_exp = self._extract_js_variable("k_exp", script_block)
        k_token = self._extract_js_variable("k_token", script_block)
        
        if not all([k_prefix_name, k_exp, k_token]):
            return {"error": "Failed to extract required tokens"}
        
        # STEP 2: Apply delay
        self._delay_request()
        
        # STEP 3: Get CF token
        print("Getting CF token...")
        try:
            cf_response = self.session.post(
                "https://saveinsta.to/api/userverify",
                data={"url": target_url},
                headers={
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "Origin": "https://saveinsta.to",
                    "Referer": "https://saveinsta.to/en/video",
                    "X-Requested-With": "XMLHttpRequest"
                }
            )
            cf_response.raise_for_status()
            cf_data = cf_response.json()
            
            if not cf_data or "token" not in cf_data:
                return {"error": "CF token not returned"}
            
            cftoken = cf_data["token"]
        except (requests.RequestException, json.JSONDecodeError) as e:
            return {"error": f"Failed to get CF token: {str(e)}"}
        
        # STEP 4: Apply delay
        self._delay_request()
        
        # STEP 5: Request final content
        print("Fetching media content...")
        try:
            final_response = self.session.post(
                "https://saveinsta.to/api/ajaxSearch",
                data={
                    "k_exp": k_exp,
                    "k_token": k_token,
                    "q": target_url,
                    "t": "media",
                    "lang": "en",
                    "v": "v2",
                    "cftoken": cftoken
                },
                headers={
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "Origin": "https://saveinsta.to",
                    "Referer": "https://saveinsta.to/en/highlights",
                    "X-Requested-With": "XMLHttpRequest"
                }
            )
            final_response.raise_for_status()
            final_data = final_response.json()
        except (requests.RequestException, json.JSONDecodeError) as e:
            return {"error": f"Failed to fetch media content: {str(e)}"}
        
        # STEP 6: Parse final HTML
        if final_data.get("status") == "ok" and "data" in final_data:
            parsed_media = self._parse_media_html(final_data["data"])
            return {
                "success": True,
                "media": parsed_media
            }
        else:
            return {
                "error": "Invalid response",
                "raw": final_data
            }


# Initialize downloader
downloader = InstagramDownloader(
    delay_mode="random",
    delay_min=1.0,
    delay_max=1.0
)


@app.route('/download', methods=['GET'])
def download_instagram():
    """
    API endpoint to download Instagram content
    Usage: GET /download?url=https://www.instagram.com/p/EXAMPLE/
    """
    url = request.args.get('url')
    
    if not url:
        return jsonify({"error": "Missing 'url' GET parameter"}), 400
    
    # Validate it's an Instagram URL
    if not re.match(r'^https?://(www\.)?instagram\.com/.*', url, re.IGNORECASE):
        return jsonify({"error": "URL must be a valid Instagram link"}), 400
    
    # Process the download
    result = downloader.download_instagram_content(url)
    
    if result.get("success"):
        return jsonify(result), 200
    else:
        return jsonify(result), 400


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "service": "Instagram Downloader API"})


@app.route('/', methods=['GET'])
def index():
    """Root endpoint with instructions"""
    return jsonify({
        "service": "Instagram Downloader API",
        "endpoints": {
            "/download": "GET with 'url' parameter - Download Instagram content",
            "/health": "GET - Health check"
        },
        "example": "/download?url=https://www.instagram.com/p/EXAMPLE/",
        "supported_types": ["profile", "post", "reel", "story", "igtv", "guide"]
    })


# ============================================
# VERCEL SPECIFIC - For Serverless Environment
# ============================================

# ⚠️ IMPORTANT: For Vercel, don't use app.run()
# Vercel will automatically use the 'app' object

# Local development ke liye
if __name__ == "__main__":
    print("🚀 Starting Instagram Downloader API Server...")
    print("📍 Local: http://localhost:5000")
    print("📥 Test: http://localhost:5000/download?url=https://www.instagram.com/reel/DWz5EjgSBeJ/")
    app.run(host='0.0.0.0', port=5000, debug=True)
