from aiohttp import web
from database.users_chats_db import db
from utils import get_settings, save_group_settings
import json

routes = web.RouteTableDef()

@routes.get("/", allow_head=True)
async def root_route_handler(request):
    return web.json_response("🚀 Bot is Running with Web Dashboard!")

@routes.get("/dashboard")
async def dashboard(request):
    html = """
    <!DOCTYPE html>
    <html>
    <head><title>Bot Settings Dashboard</title></head>
    <body>
        <h2>🤖 Bot Settings Dashboard</h2>
        <form action="/update_settings" method="post">
            <label>Group ID (e.g., -100123456789):</label><br>
            <input type="text" name="group_id" required><br><br>
            
            <label>Shortner 1 (Website):</label><br>
            <input type="text" name="shortner" placeholder="linkshortify.com"><br>
            <label>Shortner 1 (API):</label><br>
            <input type="text" name="api" placeholder="your_api_key"><br><br>
            
            <label>Shortner 2 (Website):</label><br>
            <input type="text" name="shortner_two" placeholder="mdiskshortner.link"><br>
            <label>Shortner 2 (API):</label><br>
            <input type="text" name="api_two" placeholder="your_api_key"><br><br>
            
            <label>Shortner 3 (Website):</label><br>
            <input type="text" name="shortner_three" placeholder="tnshort.net"><br>
            <label>Shortner 3 (API):</label><br>
            <input type="text" name="api_three" placeholder="your_api_key"><br><br>
            
            <label>Tutorial Link:</label><br>
            <input type="text" name="tutorial" placeholder="https://t.me/your_tutorial"><br><br>
            
            <label>File Caption (use {file_name}, {file_size}):</label><br>
            <textarea name="caption" rows="3" cols="50">📁 {file_name}\n📦 {file_size}</textarea><br><br>
            
            <label>IMDB Template:</label><br>
            <textarea name="template" rows="3" cols="50">🎬 {title}\n⭐ {rating}/10</textarea><br><br>
            
            <input type="submit" value="Update Settings">
        </form>
        <p><i>Note: Leave blank to keep current settings.</i></p>
    </body>
    </html>
    """
    return web.Response(text=html, content_type='text/html')

@routes.post("/update_settings")
async def update_settings(request):
    data = await request.post()
    group_id = data.get('group_id')
    if not group_id:
        return web.json_response({"error": "Group ID required"}, status=400)
    try:
        grp_id = int(group_id)
    except:
        return web.json_response({"error": "Invalid Group ID"}, status=400)
    
    settings = await get_settings(grp_id)
    fields = ['shortner', 'api', 'shortner_two', 'api_two', 'shortner_three', 'api_three', 'tutorial', 'caption', 'template']
    for field in fields:
        val = data.get(field)
        if val and val.strip():
            settings[field] = val.strip()
    
    await save_group_settings(grp_id, 'shortner', settings['shortner'])
    await save_group_settings(grp_id, 'api', settings['api'])
    await save_group_settings(grp_id, 'shortner_two', settings['shortner_two'])
    await save_group_settings(grp_id, 'api_two', settings['api_two'])
    await save_group_settings(grp_id, 'shortner_three', settings['shortner_three'])
    await save_group_settings(grp_id, 'api_three', settings['api_three'])
    await save_group_settings(grp_id, 'tutorial', settings['tutorial'])
    await save_group_settings(grp_id, 'caption', settings['caption'])
    await save_group_settings(grp_id, 'template', settings['template'])
    
    return web.Response(text=f"<h2>✅ Settings updated successfully for Group {grp_id}!</h2><a href='/dashboard'>Go Back</a>", content_type='text/html')
