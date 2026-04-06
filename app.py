import os, json, time, tempfile, shutil, threading
from flask import Flask, render_template, request, redirect, url_for, flash, abort, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

# Disable Paddle check at the very top
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"

"""
app.py  —  Scholaris Academic Integrity Platform
TOTAL STABILITY RESTORATION (Standard Sync Mode)
================================================
"""

from models import db, User, Course, Assignment, Submission, BulkCheckRun, BulkCheckResult

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'scholaris-secret-key-12345')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///scholaris.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024  # 1 GB

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- MODELS ---
# Handled in top-level import to avoid circular dependency errors

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- CORE LOGIC WRAPPER ---
def run_bulk_task(app_context, course_id, assignment_id, zip_path, run_id):
    with app_context:
        try:
            from logic import bulk_peer_comparison
            results, elapsed = bulk_peer_comparison(zip_path, assignment_id)
            
            run = BulkCheckRun.query.get(run_id)
            if not run: return
            
            run.status = 'completed'
            run.total_students = len(results)
            run.elapsed_sec = elapsed
            run.accepted = sum(1 for r in results if r['verdict'] == 'accepted')
            run.rejected = sum(1 for r in results if r['verdict'] == 'rejected')
            run.manual_review = sum(1 for r in results if r['verdict'] in ['manual_review', 'error'])
            
            for res in results:
                db.session.add(BulkCheckResult(
                    run_id=run.id,
                    student_name=res.get('student_name', 'Unknown'),
                    filename=res.get('filename', 'Unknown'),
                    similarity_score=float(res.get('similarity_score', 0.0)),
                    verdict=res.get('verdict', 'manual_review'),
                    peer_details=json.dumps(res.get('peer_details', {}))
                ))
            db.session.commit()
            print(f"[Bulk] Task #{run_id} finished: {len(results)} files in {elapsed}s")
        except Exception as e:
            db.session.rollback()
            print(f"[Bulk] Task #{run_id} FAILED: {e}")
            run = BulkCheckRun.query.get(run_id)
            if run:
                run.status = 'error'
                db.session.commit()
        finally:
            if os.path.exists(os.path.dirname(zip_path)):
                shutil.rmtree(os.path.dirname(zip_path), ignore_errors=True)

# --- ROUTES ---

@app.route('/')
def index():
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid email or password', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'admin':
        return redirect(url_for('admin_dashboard'))
    courses = Course.query.all()
    return render_template('dashboard.html', courses=courses)

@app.route('/course/<int:course_id>/assignment/<int:assignment_id>/bulk_check', methods=['GET', 'POST'])
@login_required
def bulk_check(course_id, assignment_id):
    if current_user.role != 'faculty': abort(403)
    course = Course.query.get_or_404(course_id)
    assignment = Assignment.query.get_or_404(assignment_id)
    
    if request.method == 'GET':
        history = BulkCheckRun.query.filter_by(assignment_id=assignment_id).order_by(BulkCheckRun.created_at.desc()).limit(10).all()
        return render_template('bulk_check.html', course=course, assignment=assignment, history=history)

    # Handle standard reliable upload
    zip_file = request.files.get('zip_file')
    if not zip_file or zip_file.filename == '':
        flash("Please select a ZIP file", "warning")
        return redirect(url_for('bulk_check', course_id=course_id, assignment_id=assignment_id))

    temp_dir = tempfile.mkdtemp(prefix='bulk_')
    zip_path = os.path.join(temp_dir, 'upload.zip')
    zip_file.save(zip_path)

    run = BulkCheckRun(course_id=course_id, assignment_id=assignment_id, status='processing', total_students=0)
    db.session.add(run)
    db.session.commit()

    # Simple background thread for stability in sync gunicorn
    threading.Thread(target=run_bulk_task, args=(app.app_context(), course_id, assignment_id, zip_path, run.id)).start()
    
    flash("Bulk check started! It will run in the background. Refresh this page to see results.", "success")
    return redirect(url_for('bulk_check', course_id=course_id, assignment_id=assignment_id))

@app.route('/generate-presigned-url', methods=['POST'])
@login_required
def generate_presigned_url():
    # Placeholder to prevent JS errors if the file isn't updated yet
    return jsonify({"error": "S3 Direct Upload is disabled for stability. Please use the standard upload form."}), 400

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000)