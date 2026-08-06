from aiohttp import web
from database.users_chats_db import db
from utils import get_settings, save_group_settings
import json
import html

routes = web.RouteTableDef()

@routes.get("/", allow_head=True)
async def root_route_handler(request):
    return web.json_response({"status": "🚀 Bot is running!", "dashboard": "/dashboard"})

@routes.get("/dashboard")
async def dashboard(request):
    """Advanced, Clean Dashboard for Group Owners"""
    
    # Get group_id from query params to pre-fill settings if available
    group_id = request.query.get('group_id', '')
    settings = {}
    if group_id and group_id.startswith('-'):
        try:
            grp_id = int(group_id)
            settings = await get_settings(grp_id)
        except:
            pass
    
    # Helper to get value or default
    def get_val(key, default=''):
        return settings.get(key, default)
    
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
            body {{
                background: #f0f2f5;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                padding: 20px;
            }}
            .main-card {{
                max-width: 900px;
                margin: 0 auto;
                background: white;
                border-radius: 20px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.1);
                padding: 30px;
                border: none;
            }}
            .header {{
                text-align: center;
                border-bottom: 2px solid #e9ecef;
                padding-bottom: 20px;
                margin-bottom: 25px;
            }}
            .header h1 {{
                font-weight: 700;
                color: #1a1a2e;
            }}
            .header p {{
                color: #6c757d;
                font-size: 14px;
            }}
            .form-label {{
                font-weight: 600;
                font-size: 14px;
                color: #34495e;
            }}
            .form-control, .form-select {{
                border-radius: 10px;
                border: 1px solid #ced4da;
                padding: 10px 15px;
                font-size: 14px;
            }}
            .form-control:focus {{
                border-color: #4e73df;
                box-shadow: 0 0 0 0.2rem rgba(78, 115, 223, 0.25);
            }}
            .toggle-section {{
                background: #f8f9fc;
                padding: 20px;
                border-radius: 15px;
                margin-bottom: 25px;
                border: 1px solid #e3e6f0;
            }}
            .toggle-item {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 12px 0;
                border-bottom: 1px solid #eaecf4;
            }}
            .toggle-item:last-child {{
                border-bottom: none;
            }}
            .toggle-label {{
                display: flex;
                align-items: center;
                gap: 10px;
                font-weight: 500;
                color: #2c3e50;
            }}
            .toggle-label i {{
                font-size: 20px;
                width: 25px;
                color: #4e73df;
            }}
            .toggle-switch {{
                position: relative;
                width: 50px;
                height: 26px;
                flex-shrink: 0;
            }}
            .toggle-switch input {{
                opacity: 0;
                width: 0;
                height: 0;
            }}
            .toggle-slider {{
                position: absolute;
                cursor: pointer;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background-color: #ccc;
                transition: .3s;
                border-radius: 26px;
            }}
            .toggle-slider:before {{
                position: absolute;
                content: "";
                height: 18px;
                width: 18px;
                left: 4px;
                bottom: 4px;
                background-color: white;
                transition: .3s;
                border-radius: 50%;
            }}
            .toggle-switch input:checked + .toggle-slider {{
                background-color: #4e73df;
            }}
            .toggle-switch input:checked + .toggle-slider:before {{
                transform: translateX(24px);
            }}
            .section-title {{
                font-weight: 700;
                color: #1a1a2e;
                margin-top: 25px;
                margin-bottom: 15px;
                padding-bottom: 10px;
                border-bottom: 2px solid #e9ecef;
                display: flex;
                align-items: center;
                gap: 10px;
            }}
            .section-title i {{
                color: #4e73df;
            }}
            .shortner-box {{
                background: #f8f9fc;
                padding: 15px;
                border-radius: 10px;
                border-left: 4px solid #4e73df;
                margin-bottom: 15px;
            }}
            .btn-update {{
                background: #1a1a2e;
                border: none;
                padding: 12px 30px;
                font-weight: 600;
                border-radius: 50px;
                width: 100%;
                font-size: 16px;
                transition: 0.2s;
            }}
            .btn-update:hover {{
                background: #4e73df;
                transform: scale(1.01);
            }}
            .note {{
                font-size: 12px;
                color: #6c757d;
                margin-top: 5px;
            }}
            .group-id-input {{
                background: #f8f9fc;
                border-radius: 10px;
                padding: 15px;
                margin-bottom: 20px;
                border: 1px dashed #b7b9cc;
            }}
            @media (max-width: 576px) {{
                .main-card {{ padding: 20px; }}
            }}
        </style>
    </head>
    <body>
        <div class="main-card">
            <div class="header">
                <h1><i class="bi bi-robot" style="color:#4e73df;"></i> Bot Settings Dashboard</h1>
                <p>Manage your group's settings effortlessly. Changes apply instantly to <strong>this group only</strong>.</p>
            </div>

            <form action="/update_settings" method="post">
                <!-- Group ID Input -->
                <div class="group-id-input">
                    <label class="form-label"><i class="bi bi-tag"></i> <strong>Group ID (Required)</strong></label>
                    <input type="text" name="group_id" class="form-control" placeholder="Example: -100123456789" value="{group_id}" required>
                    <div class="note">⚠️ Make sure the Bot is Admin in this group, and you are the Admin too.</div>
                </div>

                <!-- ============ TOGGLES SECTION ============ -->
                <div class="toggle-section">
                    <div class="section-title"><i class="bi bi-toggle-on"></i> Feature Toggles (ON / OFF)</div>
                    
                    <div class="toggle-item">
                        <span class="toggle-label"><i class="bi bi-funnel"></i> Auto Filter</span>
                        <label class="toggle-switch">
                            <input type="checkbox" name="auto_filter" {'checked' if get_val('auto_filter', True) else ''}>
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                    
                    <div class="toggle-item">
                        <span class="toggle-label"><i class="bi bi-shield-lock"></i> File Secure (Forward Restriction)</span>
                        <label class="toggle-switch">
                            <input type="checkbox" name="file_secure" {'checked' if get_val('file_secure', False) else ''}>
                            <span class="toggle-slider"></span>
                        </label>
                    </div>

                    <div class="toggle-item">
                        <span class="toggle-label"><i class="bi bi-film"></i> IMDB Details</span>
                        <label class="toggle-switch">
                            <input type="checkbox" name="imdb" {'checked' if get_val('imdb', False) else ''}>
                            <span class="toggle-slider"></span>
                        </label>
                    </div>

                    <div class="toggle-item">
                        <span class="toggle-label"><i class="bi bi-spellcheck"></i> Spell Check (Suggestions)</span>
                        <label class="toggle-switch">
                            <input type="checkbox" name="spell_check" {'checked' if get_val('spell_check', True) else ''}>
                            <span class="toggle-slider"></span>
                        </label>
                    </div>

                    <div class="toggle-item">
                        <span class="toggle-label"><i class="bi bi-clock-history"></i> Auto Delete (Messages)</span>
                        <label class="toggle-switch">
                            <input type="checkbox" name="auto_delete" {'checked' if get_val('auto_delete', True) else ''}>
                            <span class="toggle-slider"></span>
                        </label>
                    </div>

                    <div class="toggle-item">
                        <span class="toggle-label"><i class="bi bi-link-45deg"></i> Result Mode (Link vs Button)</span>
                        <label class="toggle-switch">
                            <input type="checkbox" name="link" {'checked' if get_val('link', True) else ''}>
                            <span class="toggle-slider"></span>
                        </label>
                        <span class="note" style="margin-left:10px;">{'Links' if get_val('link', True) else 'Buttons'}</span>
                    </div>

                    <div class="toggle-item">
                        <span class="toggle-label"><i class="bi bi-check-circle"></i> Verification System</span>
                        <label class="toggle-switch">
                            <input type="checkbox" name="is_verify" {'checked' if get_val('is_verify', True) else ''}>
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                </div>

                <!-- ============ TIME MANAGEMENT ============ -->
                <div class="section-title"><i class="bi bi-hourglass-split"></i> Verification Time Management (Seconds)</div>
                <div class="row g-3">
                    <div class="col-md-6">
                        <label class="form-label">1st → 2nd Verify Gap</label>
                        <input type="number" name="verify_time" class="form-control" placeholder="e.g. 600 (10 mins)" value="{get_val('verify_time', 600)}">
                        <div class="note">Time (in seconds) before 2nd shortner appears.</div>
                    </div>
                    <div class="col-md-6">
                        <label class="form-label">2nd → 3rd Verify Gap</label>
                        <input type="number" name="third_verify_time" class="form-control" placeholder="e.g. 600 (10 mins)" value="{get_val('third_verify_time', 600)}">
                        <div class="note">Time (in seconds) before 3rd shortner appears.</div>
                    </div>
                </div>

                <!-- ============ SHORTNERS ============ -->
                <div class="section-title"><i class="bi bi-link"></i> Shortner Management (1, 2, 3)</div>
                
                <div class="shortner-box">
                    <h6><span class="badge bg-primary">1st Verify</span></h6>
                    <div class="row g-2">
                        <div class="col-md-6"><input type="text" name="shortner" class="form-control" placeholder="Website (e.g., linkshortify.com)" value="{get_val('shortner', '')}"></div>
                        <div class="col-md-6"><input type="text" name="api" class="form-control" placeholder="API Key" value="{get_val('api', '')}"></div>
                    </div>
                </div>

                <div class="shortner-box" style="border-left-color: #f1c40f;">
                    <h6><span class="badge bg-warning text-dark">2nd Verify</span></h6>
                    <div class="row g-2">
                        <div class="col-md-6"><input type="text" name="shortner_two" class="form-control" placeholder="Website" value="{get_val('shortner_two', '')}"></div>
                        <div class="col-md-6"><input type="text" name="api_two" class="form-control" placeholder="API Key" value="{get_val('api_two', '')}"></div>
                    </div>
                </div>

                <div class="shortner-box" style="border-left-color: #e74c3c;">
                    <h6><span class="badge bg-danger">3rd Verify</span></h6>
                    <div class="row g-2">
                        <div class="col-md-6"><input type="text" name="shortner_three" class="form-control" placeholder="Website" value="{get_val('shortner_three', '')}"></div>
                        <div class="col-md-6"><input type="text" name="api_three" class="form-control" placeholder="API Key" value="{get_val('api_three', '')}"></div>
                    </div>
                </div>

                <!-- ============ MISC SETTINGS ============ -->
                <div class="section-title"><i class="bi bi-gear"></i> Other Settings</div>
                
                <div class="mb-3">
                    <label class="form-label"><i class="bi bi-book"></i> Tutorial Link</label>
                    <input type="text" name="tutorial" class="form-control" placeholder="https://t.me/your_tutorial" value="{get_val('tutorial', '')}">
                </div>

                <div class="mb-3">
                    <label class="form-label"><i class="bi bi-card-text"></i> File Caption (Use: {{file_name}}, {{file_size}})</label>
                    <textarea name="caption" class="form-control" rows="2" placeholder="📁 {{file_name}}&#10;📦 {{file_size}}">{get_val('caption', '📁 {file_name}\n📦 {file_size}')}</textarea>
                </div>

                <div class="mb-3">
                    <label class="form-label"><i class="bi bi-code-square"></i> IMDB Template (Use: {{title}}, {{rating}}, etc.)</label>
                    <textarea name="template" class="form-control" rows="2" placeholder="🎬 {{title}}&#10;⭐ {{rating}}/10">{get_val('template', '🎬 {title}\n⭐ {rating}/10')}</textarea>
                </div>

                <!-- Submit Button -->
                <button type="submit" class="btn btn-update btn-primary text-white">
                    <i class="bi bi-cloud-upload"></i> Update Settings
                </button>
                
                <div class="note text-center mt-3">
                    <i class="bi bi-info-circle"></i> Leave fields blank to keep current values. 
                    <br> <strong>100% Group-Specific:</strong> Settings only apply to the Group ID you enter.
                </div>
            </form>
        </div>
        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/js/bootstrap.bundle.min.js"></script>
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
        return web.Response(text="<h3>❌ Error: Invalid Group ID format. Must be a number (e.g., -100123456).</h3><a href='/dashboard'>Go Back</a>", content_type='text/html')

    # Fetch current settings to retain values for fields not submitted (or to merge)
    current_settings = await get_settings(grp_id)

    # 1. Handle Toggles (Checkboxes) - if not present in POST, it means OFF
    toggle_fields = ['auto_filter', 'file_secure', 'imdb', 'spell_check', 'auto_delete', 'link', 'is_verify']
    for field in toggle_fields:
        current_settings[field] = True if data.get(field) else False

    # 2. Handle Time Fields
    time_fields = ['verify_time', 'third_verify_time']
    for field in time_fields:
        val = data.get(field)
        if val and str(val).isdigit():
            current_settings[field] = int(val)
        # If not provided or empty, keep the existing value (do not overwrite with None)
    
    # 3. Handle Text Fields (Shortners, API, Tutorial, Caption, Template)
    text_fields = [
        'shortner', 'api', 
        'shortner_two', 'api_two', 
        'shortner_three', 'api_three', 
        'tutorial', 'caption', 'template'
    ]
    for field in text_fields:
        val = data.get(field)
        if val is not None and val.strip() != '':
            current_settings[field] = val.strip()
        # If empty, we keep the existing value. We don't want to erase accidentally.
        # However, if user explicitly clears, they can't clear it from here. But that's fine for safety.
        # We'll allow clearing if they put a space? No, better to keep existing.

    # Save all settings back to DB
    await save_group_settings(grp_id, 'auto_filter', current_settings['auto_filter'])
    await save_group_settings(grp_id, 'file_secure', current_settings['file_secure'])
    await save_group_settings(grp_id, 'imdb', current_settings['imdb'])
    await save_group_settings(grp_id, 'spell_check', current_settings['spell_check'])
    await save_group_settings(grp_id, 'auto_delete', current_settings['auto_delete'])
    await save_group_settings(grp_id, 'link', current_settings['link'])
    await save_group_settings(grp_id, 'is_verify', current_settings['is_verify'])
    await save_group_settings(grp_id, 'verify_time', current_settings['verify_time'])
    await save_group_settings(grp_id, 'third_verify_time', current_settings['third_verify_time'])
    await save_group_settings(grp_id, 'shortner', current_settings['shortner'])
    await save_group_settings(grp_id, 'api', current_settings['api'])
    await save_group_settings(grp_id, 'shortner_two', current_settings['shortner_two'])
    await save_group_settings(grp_id, 'api_two', current_settings['api_two'])
    await save_group_settings(grp_id, 'shortner_three', current_settings['shortner_three'])
    await save_group_settings(grp_id, 'api_three', current_settings['api_three'])
    await save_group_settings(grp_id, 'tutorial', current_settings['tutorial'])
    await save_group_settings(grp_id, 'caption', current_settings['caption'])
    await save_group_settings(grp_id, 'template', current_settings['template'])

    # Redirect back to dashboard with the group_id pre-filled
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
                <div class="bi bi-check-circle-fill text-success" style="font-size: 60px;"></div>
                <h2 class="mt-3">✅ Settings Updated Successfully!</h2>
                <p class="text-muted">Settings for Group <code>{grp_id}</code> have been applied instantly.</p>
                <a href="/dashboard?group_id={grp_id}" class="btn btn-primary mt-3">← Go Back to Dashboard</a>
            </div>
        </div>
        </body>
        </html>
        """, 
        content_type='text/html'
    )
