# app.py
from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
from datetime import datetime
import os
import tempfile
import shutil
import subprocess
import uuid
import threading
from git import Repo
from bson import ObjectId
import json

# Custom JSON encoder to handle ObjectId
class JSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, ObjectId):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        return json.JSONEncoder.default(self, o)

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# MongoDB connection
try:
    client = MongoClient('mongodb://localhost:27017/')
    db = client['codetracker']
    # Test connection
    client.admin.command('ping')
    print("✅ Connected to MongoDB")
except Exception as e:
    print(f"❌ MongoDB connection failed: {e}")
    print("Make sure MongoDB is running (mongod)")
    exit(1)

# Collections
assignments_collection = db['assignments']
students_collection = db['students']
submissions_collection = db['submissions']
reviews_collection = db['reviews']
analysis_results_collection = db['analysis_results']

@app.route('/api/assignments/<student_id>', methods=['GET'])
def get_student_assignments(student_id):
    """Get all assignments for a student"""
    try:
        print(f"📥 Fetching assignments for student: {student_id}")
        
        # Check if student exists
        student = students_collection.find_one({"student_id": student_id})
        if not student:
            # Create student if doesn't exist
            student = {
                "student_id": student_id,
                "name": "Dexter Facelo",
                "email": "dexter.facelo@student.edu",
                "year": 3,
                "course": "Computer Science"
            }
            students_collection.insert_one(student)
            print(f"✅ Created new student: {student_id}")
        
        # Get all assignments
        assignments = list(assignments_collection.find({}))
        print(f"📚 Found {len(assignments)} assignments in database")
        
        # Get submission status for each assignment
        result = []
        for assignment in assignments:
            submission = submissions_collection.find_one({
                "student_id": student_id,
                "assignment_id": assignment["assignment_id"]
            })
            
            assignment_data = {
                "assignment_id": assignment["assignment_id"],
                "title": assignment["title"],
                "description": assignment.get("description", ""),
                "due_date": assignment["due_date"],
                "difficulty": assignment["difficulty"],
                "language": assignment["language"],
                "repo_url": assignment["repo_url"],
                "branch": assignment.get("branch", "main"),
                "status": "pending"  # default status
            }
            
            if submission:
                assignment_data["status"] = submission.get("status", "pending")
                assignment_data["submission_id"] = str(submission["_id"])
                if "errors_count" in submission:
                    assignment_data["errors_count"] = submission["errors_count"]
                if "warnings_count" in submission:
                    assignment_data["warnings_count"] = submission["warnings_count"]
            
            result.append(assignment_data)
        
        response_data = {
            "success": True,
            "assignments": result
        }
        
        print(f"✅ Returning {len(result)} assignments for student {student_id}")
        return app.response_class(
            response=json.dumps(response_data, cls=JSONEncoder),
            status=200,
            mimetype='application/json'
        )
    except Exception as e:
        print(f"❌ Error in get_student_assignments: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        # Test MongoDB connection
        client.admin.command('ping')
        mongo_status = 'connected'
        
        # Count collections
        assignments_count = assignments_collection.count_documents({})
        students_count = students_collection.count_documents({})
        
        return jsonify({
            'status': 'healthy',
            'mongodb': mongo_status,
            'database': 'codetracker',
            'stats': {
                'assignments': assignments_count,
                'students': students_count
            },
            'timestamp': datetime.utcnow().isoformat()
        })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'mongodb': 'disconnected',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }), 500

@app.route('/api/submit-repo', methods=['POST'])
def submit_repository():
    """Submit a repository for analysis"""
    try:
        data = request.json
        
        student_id = data.get('student_id', 'student123')
        assignment_id = data.get('assignment_id')
        repo_url = data.get('repo_url')
        branch = data.get('branch', 'main')
        
        if not all([assignment_id, repo_url]):
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
        
        # Check if assignment exists
        assignment = assignments_collection.find_one({"assignment_id": assignment_id})
        if not assignment:
            return jsonify({'success': False, 'error': 'Assignment not found'}), 404
        
        # Create submission
        submission_id = str(uuid.uuid4())
        submission = {
            '_id': submission_id,
            'student_id': student_id,
            'assignment_id': assignment_id,
            'repo_url': repo_url,
            'branch': branch,
            'status': 'pending',
            'created_at': datetime.utcnow(),
            'completed_at': None,
            'total_files': 0,
            'analyzed_files': 0,
            'errors_count': 0,
            'warnings_count': 0
        }
        
        submissions_collection.insert_one(submission)
        print(f"📝 Created submission: {submission_id} for {repo_url}")
        
        # Start analysis in background
        thread = threading.Thread(
            target=analyze_repository_background,
            args=(submission_id, repo_url, branch)
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'success': True,
            'submission_id': submission_id,
            'status': 'pending'
        })
        
    except Exception as e:
        print(f"❌ Error in submit_repository: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/analysis/<submission_id>', methods=['GET'])
def get_analysis(submission_id):
    """Get analysis results for a submission"""
    try:
        submission = submissions_collection.find_one({'_id': submission_id})
        if not submission:
            return jsonify({'success': False, 'error': 'Submission not found'}), 404
        
        # Get all analysis results
        results = list(analysis_results_collection.find(
            {'submission_id': submission_id}
        ))
        
        # Get review if exists
        review = reviews_collection.find_one(
            {'submission_id': submission_id}
        )
        
        # Convert ObjectId to string for JSON
        if '_id' in submission:
            submission['_id'] = str(submission['_id'])
        
        return app.response_class(
            response=json.dumps({
                'success': True,
                'submission': submission,
                'files': results,
                'review': review
            }, cls=JSONEncoder),
            status=200,
            mimetype='application/json'
        )
        
    except Exception as e:
        print(f"❌ Error in get_analysis: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/files/<submission_id>', methods=['GET'])
def get_files(submission_id):
    """Get list of analyzed files"""
    try:
        files = list(analysis_results_collection.find(
            {'submission_id': submission_id},
            {'file_path': 1, 'file_name': 1, 'language': 1, 'status': 1}
        ))
        
        return app.response_class(
            response=json.dumps({
                'success': True,
                'files': files
            }, cls=JSONEncoder),
            status=200,
            mimetype='application/json'
        )
        
    except Exception as e:
        print(f"❌ Error in get_files: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/save-feedback', methods=['POST'])
def save_feedback():
    """Save feedback and mark as reviewed"""
    try:
        data = request.json
        
        submission_id = data.get('submission_id')
        reviewer_id = data.get('reviewer_id', 'instructor1')
        feedback = data.get('feedback', '')
        
        if not submission_id:
            return jsonify({'success': False, 'error': 'Submission ID required'}), 400
        
        # Create or update review
        review_id = str(uuid.uuid4())
        review = {
            '_id': review_id,
            'submission_id': submission_id,
            'reviewer_id': reviewer_id,
            'status': 'completed',
            'feedback': feedback,
            'created_at': datetime.utcnow(),
            'completed_at': datetime.utcnow()
        }
        
        reviews_collection.update_one(
            {'submission_id': submission_id},
            {'$set': review},
            upsert=True
        )
        
        # Update submission status
        submissions_collection.update_one(
            {'_id': submission_id},
            {'$set': {'status': 'reviewed'}}
        )
        
        print(f"✅ Feedback saved for submission {submission_id}")
        
        return jsonify({
            'success': True,
            'message': 'Feedback saved successfully'
        })
        
    except Exception as e:
        print(f"❌ Error in save_feedback: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

def analyze_repository_background(submission_id, repo_url, branch):
    """Background task for repository analysis"""
    temp_dir = None
    try:
        # Create temp directory
        temp_dir = tempfile.mkdtemp()
        print(f"📦 Cloning {repo_url} to {temp_dir}")
        
        # Clone repository
        Repo.clone_from(repo_url, temp_dir, branch=branch, depth=1)
        
        # Find C/C++ files
        c_files = []
        for root, dirs, files in os.walk(temp_dir):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['build', 'dist', 'node_modules']]
            
            for file in files:
                if file.endswith(('.c', '.cpp', '.cc', '.cxx')):
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, temp_dir)
                    language = 'cpp' if file.endswith(('.cpp', '.cc', '.cxx')) else 'c'
                    c_files.append((file_path, rel_path, language))
        
        # Update submission with total files
        submissions_collection.update_one(
            {'_id': submission_id},
            {'$set': {
                'total_files': len(c_files),
                'status': 'analyzing'
            }}
        )
        
        print(f"🔍 Found {len(c_files)} C/C++ files to analyze")
        
        # Analyze each file
        total_errors = 0
        total_warnings = 0
        
        for file_path, rel_path, language in c_files:
            try:
                # Compile command
                if language == 'c':
                    cmd = ['gcc', '-fsyntax-only', '-Wall', '-Wextra', file_path]
                else:
                    cmd = ['g++', '-fsyntax-only', '-Wall', '-Wextra', file_path]
                
                # Run compilation
                process = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                # Parse errors and warnings using the clean_error_message function
                errors = []
                warnings = []
                
                for line in process.stderr.split('\n'):
                    if not line.strip():
                        continue
                    
                    cleaned = clean_error_message(line)
                    
                    if cleaned['type'] == 'error':
                        errors.append({
                            'line': cleaned['line'],
                            'message': cleaned['message'],
                            'type': 'error'
                        })
                        print(f"   📍 Clean error: Line {cleaned['line']} - {cleaned['message'][:60]}...")
                    elif cleaned['type'] == 'warning':
                        warnings.append({
                            'line': cleaned['line'],
                            'message': cleaned['message'],
                            'type': 'warning'
                        })
                        print(f"   📍 Clean warning: Line {cleaned['line']} - {cleaned['message'][:60]}...")
                
                # Store result
                result = {
                    'submission_id': submission_id,
                    'file_path': rel_path,
                    'file_name': os.path.basename(file_path),
                    'language': language,
                    'status': 'analyzed',
                    'errors': errors,
                    'warnings': warnings,
                    'compile_output': process.stderr,
                    'analyzed_at': datetime.utcnow(),
                    'passed': len(errors) == 0
                }
                
                analysis_results_collection.insert_one(result)
                
                total_errors += len(errors)
                total_warnings += len(warnings)
                
                # Update progress
                submissions_collection.update_one(
                    {'_id': submission_id},
                    {'$inc': {'analyzed_files': 1}}
                )
                
                status_icon = "✅" if len(errors) == 0 else "❌"
                print(f"{status_icon} Analyzed: {rel_path} - Errors: {len(errors)}, Warnings: {len(warnings)}")
                
            except Exception as e:
                print(f"❌ Error analyzing {rel_path}: {e}")
        
        # Mark submission as completed
        submissions_collection.update_one(
            {'_id': submission_id},
            {'$set': {
                'status': 'completed',
                'completed_at': datetime.utcnow(),
                'errors_count': total_errors,
                'warnings_count': total_warnings
            }}
        )
        
        print(f"✅ Analysis complete for {submission_id}")
        print(f"   Total errors: {total_errors}, warnings: {total_warnings}")
        
    except Exception as e:
        print(f"❌ Background analysis failed: {e}")
        submissions_collection.update_one(
            {'_id': submission_id},
            {'$set': {'status': 'failed', 'error': str(e)}}
        )
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
            print(f"🧹 Cleaned up {temp_dir}")

def parse_compiler_output(output, file_name):
    """Parse compiler output and clean file paths from messages"""
    errors = []
    warnings = []
    
    for line in output.split('\n'):
        if not line.strip():
            continue
        
        # Remove the full file path from the message
        # Example: /tmp/tmp123/file.c:14:11: error: message
        import re
        match = re.match(r'.*?:(\d+):(\d+):\s+(error|warning):\s+(.*)', line)
        if match:
            line_num = int(match.group(1))
            msg_type = match.group(3)
            message = match.group(4)
            
            if 'error' in msg_type.lower():
                errors.append({
                    'line': line_num,
                    'message': message.strip(),
                    'type': 'error'
                })
            else:
                warnings.append({
                    'line': line_num,
                    'message': message.strip(),
                    'type': 'warning'
                })
        elif 'error:' in line.lower():
            # Handle errors without line numbers
            errors.append({
                'line': 0,
                'message': line.split('error:')[-1].strip(),
                'type': 'error'
            })
        elif 'warning:' in line.lower():
            warnings.append({
                'line': 0,
                'message': line.split('warning:')[-1].strip(),
                'type': 'warning'
            })
    
    return errors, warnings

# Add this function to your app.py to clean compiler output
def clean_error_message(error_line):
    """Remove ALL file paths and clean up error messages - shows ONLY the message"""
    import re
    
    # First, remove everything up to and including the last colon before "error:" or "warning:"
    # This handles patterns like: C:\path\to\file.c:7:1: error: message
    # Or: /path/to/file.c:7:1: error: message
    
    # Step 1: Find where "error:" or "warning:" appears
    error_match = re.search(r'(error|warning):', error_line, re.IGNORECASE)
    
    if error_match:
        # Get the position of "error:" or "warning:"
        pos = error_match.start()
        # Find the last colon before this position
        last_colon = error_line.rfind(':', 0, pos)
        if last_colon != -1:
            # Extract everything after that colon
            message_part = error_line[last_colon + 1:].strip()
        else:
            message_part = error_line[pos:].strip()
    else:
        # If no error/warning tag, try to just get the last part after the last colon
        parts = error_line.split(':')
        if len(parts) >= 3:
            # Take everything after the second colon (usually the message)
            message_part = ':'.join(parts[2:]).strip()
        else:
            message_part = error_line.strip()
    
    # Further clean up the message
    # Remove any remaining "error:" or "warning:" prefix
    message_part = re.sub(r'^(error|warning):\s*', '', message_part, flags=re.IGNORECASE)
    
    # Remove any leading numbers/colons that might remain
    message_part = re.sub(r'^\d+:\d+:\s*', '', message_part)
    message_part = re.sub(r'^\d+:\s*', '', message_part)
    
    # Try to extract line number if present
    line_num = 0
    line_match = re.search(r':(\d+):', error_line)
    if line_match:
        line_num = int(line_match.group(1))
    
    # Determine if it's an error or warning
    msg_type = 'info'
    if 'error:' in error_line.lower() or error_line.lower().startswith('error'):
        msg_type = 'error'
    elif 'warning:' in error_line.lower() or error_line.lower().startswith('warning'):
        msg_type = 'warning'
    
    return {
        'line': line_num,
        'type': msg_type,
        'message': message_part
    }
# Update the analyze_file function to use this cleaner
def analyze_file(self, file_path, language):
    """Analyze a single C/C++ file"""
    result = {
        'errors': [],
        'warnings': [],
        'compile_output': '',
        'passed': True
    }
    
    try:
        if language == 'c':
            cmd = ['gcc', '-fsyntax-only', '-Wall', '-Wextra', '-std=c11', file_path]
        else:
            cmd = ['g++', '-fsyntax-only', '-Wall', '-Wextra', '-std=c++14', file_path]
        
        process = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        # Clean and parse each line
        for line in process.stderr.split('\n'):
            if not line.strip():
                continue
            
            cleaned = clean_error_message(line)
            
            if cleaned['type'] == 'error':
                result['errors'].append({
                    'line': cleaned['line'],
                    'message': cleaned['message'],
                    'type': 'error'
                })
                result['passed'] = False
            elif cleaned['type'] == 'warning':
                result['warnings'].append({
                    'line': cleaned['line'],
                    'message': cleaned['message'],
                    'type': 'warning'
                })
        
        result['compile_output'] = process.stderr
        
    except Exception as e:
        result['errors'].append({
            'line': 0,
            'message': f'Analysis error: {str(e)}',
            'type': 'error'
        })
        result['passed'] = False
    
    return result

@app.route('/', methods=['GET'])
def home():
    """Home endpoint with API info"""
    return jsonify({
        'name': 'CodeTracker API',
        'version': '1.0.0',
        'status': 'running',
        'endpoints': [
            '/api/health',
            '/api/assignments/<student_id>',
            '/api/submit-repo',
            '/api/analysis/<submission_id>',
            '/api/files/<submission_id>',
            '/api/save-feedback'
        ]
    })

if __name__ == '__main__':
    print("=" * 60)
    print("🚀 CodeTracker Backend Server")
    print("=" * 60)
    print(f"📡 MongoDB: mongodb://localhost:27017/codetracker")
    
    # Check if assignments exist
    assignments_count = assignments_collection.count_documents({})
    if assignments_count == 0:
        print("⚠️  No assignments found in database!")
        print("   Please run: python setup_mongodb.py")
    else:
        print(f"📚 Found {assignments_count} assignments in database")
        for a in assignments_collection.find():
            print(f"   • {a['title']}")
    
    print(f"🌐 Server running on: http://localhost:5500")
    print("=" * 60)
    
    app.run(debug=True, port=5500, host='0.0.0.0')