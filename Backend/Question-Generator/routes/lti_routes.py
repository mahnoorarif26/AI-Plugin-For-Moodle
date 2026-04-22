"""LTI (Learning Tools Interoperability) routes."""

from flask import Blueprint, request, render_template, jsonify
from utils.lti_utils import LTI_JWKS

lti_bp = Blueprint('lti', __name__, url_prefix='/lti')


@lti_bp.route('/login', methods=['GET', 'POST'])
def lti_login():
    """LTI Login Endpoint."""
    return """
    <h1>LTI Login</h1>
    <p>Ready for Moodle LTI 1.1</p>
    <p>Test: <a href="/lti/launch">Launch Endpoint</a></p>
    """


@lti_bp.route('/launch', methods=['GET', 'POST'])
def lti_launch():
    """Main LTI Launch Endpoint."""
    try:
        if request.method == 'GET':
            return render_template('lti_test_launch.html')
        
        # LTI 1.1 POST handling
        lti_data = {
            'user_id': request.form.get('user_id', 'test_user'),
            'roles': request.form.get('roles', ''),
            'context_id': request.form.get('context_id', ''),
            'resource_link_id': request.form.get('resource_link_id', '')
        }
        
        # Determine role and route accordingly
        roles = lti_data['roles'].lower()
        if 'instructor' in roles or 'teacher' in roles:
            return render_template('teacher_generate.html', lti_data=lti_data)
        else:
            return render_template('student_quiz.html', lti_data=lti_data)
            
    except Exception as e:
        return jsonify({
            'error': 'LTI Launch failed',
            'details': str(e)
        }), 500


@lti_bp.route('/jwks', methods=['GET'])
def lti_jwks():
    """JWKS endpoint for LTI 1.3."""
    return jsonify(LTI_JWKS)


@lti_bp.route('/config', methods=['GET'])
def lti_config():
    """LTI configuration endpoint."""
    return jsonify({
        "title": "Quiz Generator",
        "description": "AI-powered quiz generation tool",
        "oidc_initiation_url": request.url_root + "lti/login",
        "target_link_uri": request.url_root + "lti/launch",
        "public_jwk_url": request.url_root + "lti/jwks"
    })