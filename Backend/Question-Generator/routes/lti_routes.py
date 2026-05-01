"""LTI (Learning Tools Interoperability) routes for Moodle integration - LTI 1.1 Simplified"""

from flask import Blueprint, request, render_template, jsonify, session, redirect, url_for
import hashlib
import time
from datetime import datetime

lti_bp = Blueprint('lti', __name__, url_prefix='/lti')


# ===============================
# LTI 1.1 CONFIGURATION
# ===============================

# Store your LTI credentials
LTI_CONSUMER_KEYS = {
    'testkey': 'secret',
    'moodle': 'moodle_secret',
    'ai_quiz_tool': 'ai_quiz_secret',
}

# Disable signature validation for testing (set to False in production)
BYPASS_SIGNATURE_VALIDATION = True


def validate_lti_11_request_simple(form_data):
    """Simplified LTI 1.1 validation."""
    oauth_consumer_key = form_data.get('oauth_consumer_key')
    
    if BYPASS_SIGNATURE_VALIDATION:
        if oauth_consumer_key in LTI_CONSUMER_KEYS or not oauth_consumer_key:
            return True, "Valid", _extract_launch_data(form_data)
    
    if oauth_consumer_key not in LTI_CONSUMER_KEYS:
        return False, f"Unknown consumer key: {oauth_consumer_key}", None
    
    return True, "Valid", _extract_launch_data(form_data)


def _extract_launch_data(form_data):
    """Extract launch data from form."""
    roles_raw = form_data.get('roles', 'Learner')
    if isinstance(roles_raw, str):
        roles = [r.strip() for r in roles_raw.split(',')]
    else:
        roles = ['Learner']
    
    return {
        'user_id': form_data.get('user_id', form_data.get('custom_user_id', 'test_user')),
        'user_name': form_data.get('lis_person_name_full', form_data.get('user_id', 'Test User')),
        'user_email': form_data.get('lis_person_contact_email_primary', 'test@example.com'),
        'user_image': form_data.get('lis_person_picture_url', ''),
        'roles': roles,
        'context_id': form_data.get('context_id', form_data.get('custom_course_id', 'test_course')),
        'context_title': form_data.get('context_title', form_data.get('custom_course_title', 'Test Course')),
        'resource_link_id': form_data.get('resource_link_id', 'test_resource'),
        'launch_presentation_locale': form_data.get('launch_presentation_locale', 'en'),
        'launch_presentation_document_target': form_data.get('launch_presentation_document_target', 'iframe'),
        'lti_version': form_data.get('lti_version', 'LTI-1p0'),
        'lti_message_type': form_data.get('lti_message_type', 'basic-lti-launch-request'),
        'tool_consumer_info_product_family_code': form_data.get('tool_consumer_info_product_family_code', 'moodle'),
        'tool_consumer_instance_guid': form_data.get('tool_consumer_instance_guid', ''),
    }


def is_instructor_role(roles):
    """Check if user has instructor/teacher role."""
    instructor_roles = [
        'instructor', 'teacher', 'contentdeveloper', 'teachingassistant',
        'urn:lti:role:ims/lis/instructor'
    ]
    for role in roles:
        role_lower = role.lower()
        for instructor in instructor_roles:
            if instructor in role_lower:
                return True
    return False


# ===============================
# LTI CONFIGURATION ENDPOINTS
# ===============================

@lti_bp.route('/config.xml', methods=['GET'])
def lti_config_xml():
    """LTI 1.1 Configuration XML for Moodle - Configured to open in same window."""
    base_url = request.url_root.rstrip('/')
    
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
    <cartridge_basiclti_link xmlns="http://www.imsglobal.org/xsd/imslticc_v1p0"
        xmlns:blti="http://www.imsglobal.org/xsd/imsbasiclti_v1p0"
        xmlns:lticm="http://www.imsglobal.org/xsd/imslticm_v1p0"
        xmlns:lticp="http://www.imsglobal.org/xsd/imslticp_v1p0">
        
        <blti:title>AI Quiz Generator</blti:title>
        <blti:description>Generate AI-powered quizzes and assignments inside Moodle</blti:description>
        <blti:launch_url>{base_url}/lti/launch</blti:launch_url>
        <blti:secure_launch_url>{base_url}/lti/launch</blti:secure_launch_url>
        
        <!-- Force same window/iframe embedding -->
        <blti:launch_presentation>
            <lticm:property name="document_target">iframe</lticm:property>
        </blti:launch_presentation>
        
        <blti:extensions platform="moodle2">
            <lticm:property name="tool_organisation">AI Quiz Generator</lticm:property>
            <lticm:property name="privacy_level">public</lticm:property>
            
            <!-- Course navigation - opens in same window -->
            <lticm:options name="course_navigation">
                <lticm:property name="enabled">true</lticm:property>
                <lticm:property name="text">AI Quiz Generator</lticm:property>
                <lticm:property name="default">enabled</lticm:property>
                <lticm:property name="window_target">same</lticm:property>
            </lticm:options>
            
            <!-- Activity link - opens in same window -->
            <lticm:options name="activity_link">
                <lticm:property name="enabled">true</lticm:property>
                <lticm:property name="text">AI Quiz Generator</lticm:property>
                <lticm:property name="window_target">same</lticm:property>
            </lticm:options>
        </blti:extensions>
        
        <blti:custom>
            <lticm:property name="course_id">$Context.id</lticm:property>
            <lticm:property name="user_id">$User.id</lticm:property>
            <lticm:property name="course_title">$Context.title</lticm:property>
        </blti:custom>
    </cartridge_basiclti_link>'''
    
    return xml, 200, {'Content-Type': 'application/xml'}


# ===============================
# MAIN LTI LAUNCH ENDPOINT
# ===============================

@lti_bp.route('/launch', methods=['GET', 'POST'])
def lti_launch():
    """Main LTI Launch Endpoint - Opens inside Moodle frame."""
    
    # GET request - show test form
    if request.method == 'GET':
        try:
            return render_template('lti_test_launch.html')
        except:
            return '''
            <html>
            <head>
                <title>AI Quiz Generator</title>
                <style>
                    body { font-family: Arial; padding: 20px; background: #f5f5f5; }
                    .container { max-width: 500px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; }
                    input, select { width: 100%; padding: 8px; margin: 10px 0; }
                    button { background: #4CAF50; color: white; padding: 10px 20px; border: none; cursor: pointer; }
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>AI Quiz Generator</h1>
                    <form method="POST">
                        <label>User ID:</label>
                        <input name="user_id" value="teacher123">
                        <label>Name:</label>
                        <input name="lis_person_name_full" value="Test Teacher">
                        <label>Role:</label>
                        <select name="roles">
                            <option value="Instructor">Instructor (Teacher)</option>
                            <option value="Learner">Learner (Student)</option>
                        </select>
                        <label>Course ID:</label>
                        <input name="context_id" value="course_101">
                        <label>Course Title:</label>
                        <input name="context_title" value="Test Course">
                        <button type="submit">Launch</button>
                    </form>
                </div>
            </body>
            </html>
            '''
    
    # POST request - handle LTI launch
    try:
        print("=" * 50)
        print("📥 LTI Launch - Opening in same window/frame")
        
        is_valid, message, launch_data = validate_lti_11_request_simple(request.form)
        
        if not is_valid:
            return render_template('lti_error.html', error=f"LTI Validation Failed: {message}")
        
        # Store launch data in session
        session['lti_launch_id'] = hashlib.md5(
            f"{launch_data['user_id']}_{launch_data['context_id']}_{time.time()}".encode()
        ).hexdigest()
        session['lti_user_id'] = launch_data['user_id']
        session['lti_user_name'] = launch_data['user_name']
        session['lti_user_email'] = launch_data['user_email']
        session['lti_context_id'] = launch_data['context_id']
        session['lti_context_title'] = launch_data['context_title']
        session['lti_roles'] = launch_data['roles']
        session['lti_is_instructor'] = is_instructor_role(launch_data['roles'])
        session['lti_launch_time'] = datetime.now().isoformat()
        
        # Check launch target - ensure it stays in Moodle frame
        launch_target = launch_data.get('launch_presentation_document_target', 'iframe')
        print(f"🎯 Launch target: {launch_target} (should be iframe/window)")
        
        # Redirect based on user role - these pages will open inside Moodle
        if session.get('lti_is_instructor'):
            # This will open in the same Moodle window/frame
            return redirect(url_for('teacher.teacher_generate'))
        else:
            # This will open in the same Moodle window/frame
            return redirect(url_for('student.student_index'))
            
    except Exception as e:
        print(f"❌ LTI Launch error: {e}")
        try:
            return render_template('lti_error.html', error=f"Launch failed: {str(e)}"), 500
        except:
            return f"Error: {str(e)}", 500


# ===============================
# UTILITY ENDPOINTS
# ===============================

@lti_bp.route('/status', methods=['GET'])
def lti_status():
    """Check LTI tool status."""
    return jsonify({
        "status": "active",
        "version": "LTI 1.1",
        "name": "AI Quiz Generator",
        "launch_behavior": "Opens inside Moodle (same window/frame)",
        "endpoints": {
            "launch": url_for('lti.lti_launch', _external=True),
            "config_xml": url_for('lti.lti_config_xml', _external=True)
        }
    })


@lti_bp.route('/clear-session', methods=['GET'])
def clear_session():
    """Clear LTI session data."""
    session.clear()
    return redirect(url_for('lti.lti_launch'))