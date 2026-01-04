from flask import Flask, redirect, render_template, request, make_response, session, abort, jsonify, url_for
import secrets
from functools import wraps
import firebase_admin
from firebase_admin import credentials, firestore, auth
from datetime import timedelta
import os
from dotenv import load_dotenv
from music_processor import MusicProcessor, format_stem_name, get_instrument_emoji
import tempfile
from werkzeug.utils import secure_filename

load_dotenv()

# Set working directory to script directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY')

# Audio upload configuration
ALLOWED_EXTENSIONS = {'mp3', 'wav', 'flac', 'ogg', 'm4a'}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE

# Initialize music processor
music_processor = MusicProcessor()


# Configure session cookie settings
app.config['SESSION_COOKIE_SECURE'] = True# Ensure cookies are sent over HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = False  # Prevent JavaScript access to cookies
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=1)  # Adjust session expiration as needed
app.config['SESSION_REFRESH_EACH_REQUEST'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # Can be 'Strict', 'Lax', or 'None'


# Firebase Admin SDK setup
import json
import base64

# Check if Firebase config is in environment variable (Vercel) or file (local)
firebase_json = os.getenv('FIREBASE_CONFIG_JSON')
if firebase_json:
    # Decode base64 from environment variable
    try:
        firebase_config = json.loads(base64.b64decode(firebase_json).decode('utf-8'))
        cred = credentials.Certificate(firebase_config)
    except Exception as e:
        print(f"Error loading Firebase config from env: {e}")
        cred = credentials.Certificate("firebase-auth.json")
else:
    # Load from local file
    cred = credentials.Certificate("firebase-auth.json")

firebase_admin.initialize_app(cred)
db = firestore.client()



########################################
""" Authentication and Authorization """

# Decorator for routes that require authentication
def auth_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check if user is authenticated
        if 'user' not in session:
            return redirect(url_for('login'))
        
        else:
            return f(*args, **kwargs)
        
    return decorated_function


@app.route('/auth', methods=['POST'])
def authorize():
    token = request.headers.get('Authorization')
    if not token or not token.startswith('Bearer '):
        return "Unauthorized", 401

    token = token[7:]  # Strip off 'Bearer ' to get the actual token

    try:
        decoded_token = auth.verify_id_token(token, check_revoked=True, clock_skew_seconds=60) # Validate token here
        session['user'] = decoded_token # Add user to session
        return redirect(url_for('dashboard'))
    
    except:
        return "Unauthorized", 401


#####################
""" Public Routes """

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/login')
def login():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    else:
        return render_template('login.html')

@app.route('/signup')
def signup():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    else:
        return render_template('signup.html')


@app.route('/reset-password')
def reset_password():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    else:
        return render_template('forgot_password.html')

@app.route('/terms')
def terms():
    return render_template('terms.html')

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

@app.route('/logout')
def logout():
    session.pop('user', None)  # Remove the user from session
    response = make_response(redirect(url_for('login')))
    response.set_cookie('session', '', expires=0)  # Optionally clear the session cookie
    return response


##############################################
""" Private Routes (Require authorization) """

@app.route('/dashboard')
@auth_required
def dashboard():
    """Display dashboard with user stats"""
    user_id = session['user']['uid']
    try:
        # Fetch projects from user-specific collection
        projects_ref = db.collection('users').document(user_id).collection('projects').stream()
        projects_list = list(projects_ref)
        total_projects = len(projects_list)
        
        # Calculate processed songs and total extracts
        processed_songs = 0
        total_extracts = 0
        
        for project_doc in projects_list:
            project_data = project_doc.to_dict()
            if project_data.get('status') == 'completed':
                processed_songs += 1
            results = project_data.get('results', {})
            if results:
                total_extracts += len(results)
        
        return render_template('dashboard.html', 
                             total_projects=total_projects,
                             processed_songs=processed_songs,
                             total_extracts=total_extracts)
    except Exception as e:
        print(f"Error fetching dashboard data: {e}")
        return render_template('dashboard.html', 
                             total_projects=0,
                             processed_songs=0,
                             total_extracts=0)


@app.route('/projects')
@auth_required
def projects():
    """Display all projects for the logged-in user"""
    user_id = session['user']['uid']
    try:
        # Fetch projects from user-specific collection
        projects_ref = db.collection('users').document(user_id).collection('projects').stream()
        projects_list = []
        for doc in projects_ref:
            project_data = doc.to_dict()
            project_data['id'] = doc.id
            projects_list.append(project_data)
        
        return render_template('projects.html', projects=projects_list)
    except Exception as e:
        print(f"Error fetching projects: {e}")
        return render_template('projects.html', projects=[])


@app.route('/project/create', methods=['GET', 'POST'])
@auth_required
def create_project():
    """Create a new project"""
    if request.method == 'POST':
        user_id = session['user']['uid']
        project_name = request.form.get('project_name')
        project_description = request.form.get('project_description', '')
        
        if not project_name:
            return render_template('create_project.html', error='Project name is required'), 400
        
        try:
            # Check if project name already exists for this user
            existing_projects = db.collection('users').document(user_id).collection('projects').where('name', '==', project_name).stream()
            if any(existing_projects):
                return render_template('create_project.html', error=f'A project with name "{project_name}" already exists'), 400
            
            # Save project to user-specific collection
            project_data = {
                'name': project_name,
                'description': project_description,
                'created_at': firestore.SERVER_TIMESTAMP,
                'updated_at': firestore.SERVER_TIMESTAMP,
                'song_file': None,
                'results': {},
                'status': 'created'
            }
            # Store under users/{user_id}/projects/{project_id}
            doc_ref = db.collection('users').document(user_id).collection('projects').document()
            doc_ref.set(project_data)
            
            return redirect(url_for('project_detail', project_id=doc_ref.id))
        except Exception as e:
            print(f"Error creating project: {e}")
            return render_template('create_project.html', error='Failed to create project'), 500
    
    return render_template('create_project.html')


@app.route('/project/<project_id>')
@auth_required
def project_detail(project_id):
    """View details of a specific project"""
    user_id = session['user']['uid']
    try:
        # Fetch project from user-specific collection
        doc = db.collection('users').document(user_id).collection('projects').document(project_id).get()
        
        if not doc.exists:
            abort(404)
        
        project = doc.to_dict()
        project['id'] = doc.id
        return render_template('project_detail.html', project=project)
    except Exception as e:
        print(f"Error fetching project: {e}")
        abort(404)


@app.route('/project/<project_id>/upload', methods=['POST'])
@auth_required
def upload_song(project_id):
    """Handle song upload, processing, and storing results"""
    user_id = session['user']['uid']
    
    try:
        # Verify project ownership (user-specific collection)
        project_doc = db.collection('users').document(user_id).collection('projects').document(project_id).get()
        if not project_doc.exists:
            return jsonify({'error': 'Unauthorized'}), 403
        
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        # Validate file extension
        file_ext = file.filename.rsplit('.', 1)[-1].lower()
        if file_ext not in ALLOWED_EXTENSIONS:
            return jsonify({'error': f'Invalid file type. Allowed: {", ".join(ALLOWED_EXTENSIONS)}'}), 400
        
        # Save file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{file_ext}') as tmp_file:
            file.save(tmp_file.name)
            temp_audio_path = tmp_file.name
        
        try:
            # Update project status to processing
            db.collection('users').document(user_id).collection('projects').document(project_id).update({
                'status': 'processing',
                'processing_started_at': firestore.SERVER_TIMESTAMP
            })
            
            print(f"Processing audio for project: {project_id} (user: {user_id})")
            
            # Process and upload to Cloudinary
            results = music_processor.process_and_upload(
                temp_audio_path,
                project_id,
                user_id
            )
            
            # Format results for storage
            formatted_results = {}
            for stem_name, stem_data in results['stems'].items():
                # Include all stems, but mark failed ones
                display_name = format_stem_name(stem_name)
                formatted_results[stem_name] = {
                    'name': display_name,
                    'emoji': get_instrument_emoji(stem_name),
                    'url': stem_data.get('url'),
                    'public_id': stem_data.get('public_id'),
                    'format': stem_data.get('format'),
                    'size': stem_data.get('size'),
                    'error': stem_data.get('error')
                }
                print(f"Stem {stem_name}: url={stem_data.get('url')}, error={stem_data.get('error')}")
            
            # Save results to user-specific project (only include successful stems in return)
            successful_stems = {k: v for k, v in formatted_results.items() if v.get('url')}
            
            db.collection('users').document(user_id).collection('projects').document(project_id).update({
                'results': formatted_results,  # Store all (with errors for debugging)
                'status': 'completed',
                'total_stems': len(successful_stems),
                'processing_completed_at': firestore.SERVER_TIMESTAMP
            })
            
            return jsonify({
                'status': 'success',
                'message': 'Song processed successfully!',
                'results': successful_stems,  # Return only successful ones to frontend
                'total_stems': len(successful_stems)
            }), 200
        
        except Exception as e:
            # Update project status to failed
            db.collection('users').document(user_id).collection('projects').document(project_id).update({
                'status': 'failed',
                'error': str(e),
                'processing_failed_at': firestore.SERVER_TIMESTAMP
            })
            
            print(f"Error processing audio: {str(e)}")
            return jsonify({
                'status': 'error',
                'error': f'Processing failed: {str(e)}'
            }), 500
        
        finally:
            # Clean up temporary file
            if os.path.exists(temp_audio_path):
                os.remove(temp_audio_path)
    
    except Exception as e:
        print(f"Error in upload_song: {e}")
        return jsonify({'error': 'Upload failed'}), 500


@app.route('/project/<project_id>/results')
@auth_required
def get_results(project_id):
    """Fetch results for a project"""
    user_id = session['user']['uid']
    
    try:
        doc = db.collection('users').document(user_id).collection('projects').document(project_id).get()
        
        if not doc.exists:
            return jsonify({'error': 'Project not found'}), 404
        
        project = doc.to_dict()
        all_results = project.get('results', {})
        
        # Filter to only show successful stems (those with URLs)
        successful_results = {k: v for k, v in all_results.items() if v.get('url')}
        
        return jsonify({
            'status': project.get('status', 'unknown'),
            'results': successful_results,
            'total_stems': len(successful_results),
            'error': project.get('error')
        }), 200
    
    except Exception as e:
        print(f"Error fetching results: {e}")
        return jsonify({'error': 'Failed to fetch results'}), 500


@app.route('/project/<project_id>/rename', methods=['POST'])
@auth_required
def rename_project(project_id):
    """Rename a project"""
    try:
        user_id = session['user']['uid']
        data = request.get_json()
        new_name = data.get('name', '').strip()
        
        if not new_name:
            return jsonify({'error': 'Project name cannot be empty'}), 400
        
        # Get project reference
        project_ref = db.collection('users').document(user_id).collection('projects').document(project_id)
        project_doc = project_ref.get()
        
        if not project_doc.exists:
            return jsonify({'error': 'Project not found'}), 404
        
        # Check if new name already exists for this user
        existing_projects = db.collection('users').document(user_id).collection('projects').where('name', '==', new_name).stream()
        for doc in existing_projects:
            if doc.id != project_id:  # Allow same name if it's the same project
                return jsonify({'error': f'A project with name "{new_name}" already exists'}), 400
        
        # Update the project name
        project_ref.update({
            'name': new_name,
            'updated_at': firestore.SERVER_TIMESTAMP
        })
        
        return jsonify({'status': 'success', 'message': 'Project renamed successfully'}), 200
    
    except Exception as e:
        print(f"Error renaming project: {e}")
        return jsonify({'error': 'Failed to rename project'}), 500


@app.route('/project/<project_id>/delete', methods=['POST'])
@auth_required
def delete_project(project_id):
    """Delete a project"""
    try:
        user_id = session['user']['uid']
        
        # Get project reference
        project_ref = db.collection('users').document(user_id).collection('projects').document(project_id)
        project_doc = project_ref.get()
        
        if not project_doc.exists:
            return jsonify({'error': 'Project not found'}), 404
        
        # Delete the project
        project_ref.delete()
        
        return jsonify({'status': 'success', 'message': 'Project deleted successfully'}), 200
    
    except Exception as e:
        print(f"Error deleting project: {e}")
        return jsonify({'error': 'Failed to delete project'}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    host = '0.0.0.0'
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() in ('1', 'true', 'yes')
    app.run(host=host, port=port, debug=debug)
