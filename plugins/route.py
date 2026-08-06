from aiohttp import web
from database.users_chats_db import db
from utils import get_settings, save_group_settings, get_hash
from info import BIN_CHANNEL, BOT_TOKEN
import json
import html

# Global variable to store bot instance (set from bot.py)
_bot = None

def set_bot(bot_instance):
    global _bot
    _bot = bot_instance

routes = web.RouteTableDef()

# ---------- 🔥 STREAMING & DOWNLOAD HANDLERS (404 Fix) ----------
@routes.get("/watch/{msg_id}")
async def watch_handler(request):
    """Watch Online - Direct Redirect to Telegram CDN (Super Fast, Zero Load)"""
    global _bot
    if not _bot:
        return web.Response(text="Bot is not ready yet.", status=500)
    
    msg_id = int(request.match_info['msg_id'])
    
    try:
        # BIN_CHANNEL से Message फेच करें (जहाँ bot ने file भेजी थी)
        msg = await _bot.get_messages(chat_id=BIN_CHANNEL, message_ids=msg_id)
        if not msg or not msg.media:
            return web.Response(text="File not found or expired.", status=404)
        
        # Telegram CDN का Direct URL बनाएं
        file_path = await _bot.get_file(msg.media.file_id)
        download_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        
        # User को सीधा Telegram के CDN पर Redirect करें (तेज़ और Free)
        raise web.HTTPFound(download_url)
    except Exception as e:
        print(f"Streaming error: {e}")
        return web.Response(text=f"Error: {str(e)}", status=500)

@routes.get("/{msg_id}")
async def download_handler(request):
    """Fast Download - Same as Watch, Redirect to CDN"""
    return await watch_handler(request)

# ---------- DASHBOARD ROUTES (Group Owners के लिए) ----------
@routes.get("/", allow_head=True)
async def root_route_handler(request):
    return web.json_response({"status": "🚀 Bot is running!", "dashboard": "/dashboard"})

@routes.get("/dashboard")
async def dashboard(request):
    """Advanced, Clean Dashboard for Group Owners"""
    
    group_id = request.query.get('group_id', '')
    settings = {}
    if group_id and group_id.startswith('-'):
        try:
            grp_id = int(group_id)
            settings = await get_settings(grp_id)
        except:
            pass
    
    def get_val(key, default=''):
        return settings.get(key, default)
    
    # FIX: \n वाली डिफॉल्ट वैल्यू को f-string से बाहर रखा
    caption_default = "📁 {file_name}\n📦 {file_size}"
    template_default = "🎬 {title}\n⭐ {rating}/10"
    
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>⚙️ Bot Dashboard</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.0/font/bootstrap-icons.css">
        <style>
            body {{ background: #f0f2f5; font-family: 'Segoe UI', sans-serif; padding: 20px; }}
            .main-card {{ max-width: 950px; margin: 0 auto; background: white; border-radius: 20px; box-shadow: 0 10px 30px rgba(0,0,0,0.1); padding: 30px; }}
            .header {{ text-align: center; border-bottom: 2px solid #e9ecef; padding-bottom: 20px; margin-bottom: 25px; }}
            .header h1 {{ font-weight: 700; color: #1a1a2e; }}
            .form-label {{ font-weight: 600; font-size: 14px; color: #34495e; }}
            .form-control, .form-select {{ border-radius: 10px; border: 1px solid #ced4da; padding: 10px 15px; font-size: 14px; }}
            .toggle-section {{ background: #f8f9fc; padding: 20px; border-radius: 15px; margin-bottom: 25px; border: 1px solid #e3e6f0; }}
            .toggle-item {{ display: flex; justify-content: space-between; align-items: center; padding: 12px 0; border-bottom: 1px solid #eaecf4; }}
            .toggle-item:last-child {{ border-bottom: none; }}
            .toggle-label {{ display: flex; align-items: center; gap: 10px; font-weight: 500; color: #2c3e50; }}
            .toggle-label i {{ font-size: 20px; width: 25px; color: #4e73df; }}
            .toggle-switch {{ position: relative; width: 50px; height: 26px; flex-shrink: 0; }}
            .toggle-switch input {{ opacity: 0; width: 0; height: 0; }}
            .toggle-slider {{ position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #ccc; transition: .3s; border-radius: 26px; }}
            .toggle-slider:before {{ position: absolute; content: ""; height: 18px; width: 18px; left: 4px; bottom: 4px; background-color: white; transition: .3s; border-radius: 50%; }}
            .toggle-switch input:checked + .toggle-slider {{ background-color: #4e73df; }}
            .toggle-switch input:checked + .toggle-slider:before {{ transform: translateX(24px); }}
            .section-title {{ font-weight: 700; color: #1a1a2e; margin-top: 25px; margin-bottom: 15px; padding-bottom: 10px; border-bottom: 2px solid #e9ecef; display: flex; align-items: center; gap: 10px; }}
            .section-title i {{ color: #4e73df; }}
            .shortner-box {{ background: #f8f9fc; padding: 15px; border-radius: 10px; border-left: 4px solid #4e73df; margin-bottom: 15px; }}
            .shortner-box .row {{ margin-top: 5px; }}
            .btn-update {{ background: #1a1a2e; border: none; padding: 12px; font-weight: 600; border-radius: 50px; width: 100%; font-size: 16px; color: white; transition: 0.2s; }}
            .btn-update:hover {{ background: #4e73df; transform: scale(1.01); }}
            .note {{ font-size: 12px; color: #6c757d; margin-top: 5px; }}
            .group-id-input {{ background: #f8f9fc; border-radius: 10px; padding: 15px; margin-bottom: 20px; border: 1px dashed #b7b9cc; }}
            @media (max-width: 576px) {{ .main-card {{ padding: 20px; }} }}
        </style>
    </head>
    <body>
        <div class="main-card">
            <div class="header">
                <h1><i class="bi bi-robot" style="color:#4e73df;"></i> Bot Settings Dashboard</h1>
                <p>Manage your group's settings. Changes apply <strong>only to this group</strong>.</p>
            </div>

            <form action="/update_settings" method="post">
                <div class="group-id-input">
                    <label class="form-label"><i class="bi bi-tag"></i> <strong>Group ID (Required)</strong></label>
                    <input type="text" name="group_id" class="form-control" placeholder="Example: -100123456789" value="{group_id}" required>
                    <div class="note">⚠️ Bot must be Admin in this group.</div>
                </div>

                <!-- TOGGLES -->
                <div class="toggle-section">
                    <div class="section-title"><i class="bi bi-toggle-on"></i> Feature Toggles</div>
                    <div class="toggle-item">
                        <span class="toggle-label"><i class="bi bi-funnel"></i> Auto Filter</span>
                        <label class="toggle-switch"><input type="checkbox" name="auto_filter" {'checked' if get_val('auto_filter', True) else ''}><span class="toggle-slider"></span></label>
                    </div>
                    <div class="toggle-item">
                        <span class="toggle-label"><i class="bi bi-shield-lock"></i> File Secure</span>
                        <label class="toggle-switch"><input type="checkbox" name="file_secure" {'checked' if get_val('file_secure', False) else ''}><span class="toggle-slider"></span></label>
                    </div>
                    <div class="toggle-item">
                        <span class="toggle-label"><i class="bi bi-film"></i> IMDB Details</span>
                        <label class="toggle-switch"><input type="checkbox" name="imdb" {'checked' if get_val('imdb', False) else ''}><span class="toggle-slider"></span></label>
                    </div>
                    <div class="toggle-item">
                        <span class="toggle-label"><i class="bi bi-spellcheck"></i> Spell Check</span>
                        <label class="toggle-switch"><input type="checkbox" name="spell_check" {'checked' if get_val('spell_check', True) else ''}><span class="toggle-slider"></span></label>
                    </div>
                    <div class="toggle-item">
                        <span class="toggle-label"><i class="bi bi-clock-history"></i> Auto Delete</span>
                        <label class="toggle-switch"><input type="checkbox" name="auto_delete" {'checked' if get_val('auto_delete', True) else ''}><span class="toggle-slider"></span></label>
                    </div>
                    <div class="toggle-item">
                        <span class="toggle-label"><i class="bi bi-link-45deg"></i> Result Mode (Link)</span>
                        <label class="toggle-switch"><input type="checkbox" name="link" {'checked' if get_val('link', True) else ''}><span class="toggle-slider"></span></label>
                    </div>
                    <div class="toggle-item">
                        <span class="toggle-label"><i class="bi bi-check-circle"></i> Verification System</span>
                        <label class="toggle-switch"><input type="checkbox" name="is_verify" {'checked' if get_val('is_verify', True) else ''}><span class="toggle-slider"></span></label>
                    </div>
                </div>

                <!-- TIME -->
                <div class="section-title"><i class="bi bi-hourglass-split"></i> Verification Time (Seconds)</div>
                <div class="row g-3">
                    <div class="col-md-6">
                        <label class="form-label">1st → 2nd Gap</label>
                        <input type="number" name="verify_time" class="form-control" placeholder="600" value="{get_val('verify_time', 600)}">
                    </div>
                    <div class="col-md-6">
                        <label class="form-label">2nd → 3rd Gap</label>
                        <input type="number" name="third_verify_time" class="form-control" placeholder="600" value="{get_val('third_verify_time', 600)}">
                    </div>
                </div>

                <!-- SHORTNER 1 -->
                <div class="section-title"><i class="bi bi-1-circle"></i> 1st Verify Shortner</div>
                <div class="shortner-box" style="border-left-color: #4e73df;">
                    <div class="row g-2">
                        <div class="col-md-6"><input type="text" name="shortner" class="form-control" placeholder="Website" value="{get_val('shortner', '')}"></div>
                        <div class="col-md-6"><input type="text" name="api" class="form-control" placeholder="API Key" value="{get_val('api', '')}"></div>
                    </div>
                    <div class="row g-2 mt-2">
                        <div class="col-12">
                            <label class="form-label" style="font-size:13px;"><i class="bi bi-book"></i> Tutorial Link for 1st Verify</label>
                            <input type="text" name="tutorial" class="form-control" placeholder="https://t.me/..." value="{get_val('tutorial', '')}">
                        </div>
                    </div>
                </div>

                <!-- SHORTNER 2 -->
                <div class="section-title"><i class="bi bi-2-circle"></i> 2nd Verify Shortner</div>
                <div class="shortner-box" style="border-left-color: #f1c40f;">
                    <div class="row g-2">
                        <div class="col-md-6"><input type="text" name="shortner_two" class="form-control" placeholder="Website" value="{get_val('shortner_two', '')}"></div>
                        <div class="col-md-6"><input type="text" name="api_two" class="form-control" placeholder="API Key" value="{get_val('api_two', '')}"></div>
                    </div>
                    <div class="row g-2 mt-2">
                        <div class="col-12">
                            <label class="form-label" style="font-size:13px;"><i class="bi bi-book"></i> Tutorial Link for 2nd Verify</label>
                            <input type="text" name="tutorial_two" class="form-control" placeholder="https://t.me/..." value="{get_val('tutorial_two', '')}">
                        </div>
                    </div>
                </div>

                <!-- SHORTNER 3 -->
                <div class="section-title"><i class="bi bi-3-circle"></i> 3rd Verify Shortner</div>
                <div class="shortner-box" style="border-left-color: #e74c3c;">
                    <div class="row g-2">
                        <div class="col-md-6"><input type="text" name="shortner_three" class="form-control" placeholder="Website" value="{get_val('shortner_three', '')}"></div>
                        <div class="col-md-6"><input type="text" name="api_three" class="form-control" placeholder="API Key" value="{get_val('api_three', '')}"></div>
                    </div>
                    <div class="row g-2 mt-2">
                        <div class="col-12">
                            <label class="form-label" style="font-size:13px;"><i class="bi bi-book"></i> Tutorial Link for 3rd Verify</label>
                            <input type="text" name="tutorial_three" class="form-control" placeholder="https://t.me/..." value="{get_val('tutorial_three', '')}">
                        </div>
                    </div>
                </div>

                <!-- MISC -->
                <div class="section-title"><i class="bi bi-gear"></i> Caption & Template</div>
                <div class="mb-3">
                    <label class="form-label">File Caption</label>
                    <textarea name="caption" class="form-control" rows="2">{get_val('caption', caption_default)}</textarea>
                </div>
                <div class="mb-3">
                    <label class="form-label">IMDB Template</label>
                    <textarea name="template" class="form-control" rows="2">{get_val('template', template_default)}</textarea>
                </div>

                <button type="submit" class="btn-update"><i class="bi bi-cloud-upload"></i> Update Settings</button>
                <div class="note text-center mt-3">💡 Only fill fields you want to change. Group-Specific Settings.</div>
            </form>
        </div>
    </body>
    </html>
    """
    return web.Response(text=html_content, content_type='text/html')

@routes.post("/update_settings")
async def update_settings(request):
    data = await request.post()
    group_id = data.get('group_id')
    
    if not group_id:
        return web.Response(text="<h3>❌ Error: Group ID is required.</h3><a href='/dashboard'>Go Back</a>", content_type='text/html')
    
    try:
        grp_id = int(group_id)
    except ValueError:
        return web.Response(text="<h3>❌ Error: Invalid Group ID.</h3><a href='/dashboard'>Go Back</a>", content_type='text/html')

    current_settings = await get_settings(grp_id)

    # Toggles
    for field in ['auto_filter', 'file_secure', 'imdb', 'spell_check', 'auto_delete', 'link', 'is_verify']:
        current_settings[field] = True if data.get(field) else False

    # Time
    for field in ['verify_time', 'third_verify_time']:
        val = data.get(field)
        if val and str(val).isdigit():
            current_settings[field] = int(val)

    # Text Fields (Including 3 Tutorials)
    text_fields = [
        'shortner', 'api', 
        'shortner_two', 'api_two', 
        'shortner_three', 'api_three', 
        'tutorial', 'tutorial_two', 'tutorial_three',
        'caption', 'template'
    ]
    for field in text_fields:
        val = data.get(field)
        if val is not None and val.strip() != '':
            current_settings[field] = val.strip()

    # Save all
    for key, value in current_settings.items():
        await save_group_settings(grp_id, key, value)

    return web.Response(
        text=f"""
        <!DOCTYPE html>
        <html>
        <head><meta charset="UTF-8"><title>Success</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
        </head>
        <body class="bg-light">
        <div class="container mt-5 text-center">
            <div class="card p-5 shadow-lg">
                <h2 class="text-success">✅ Settings Updated!</h2>
                <p>Group <code>{grp_id}</code> settings applied.</p>
                <a href="/dashboard?group_id={grp_id}" class="btn btn-primary">← Back to Dashboard</a>
            </div>
        </div>
        </body>
        </html>
        """, 
        content_type='text/html'
    )
