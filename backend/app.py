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
import re
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
CORS(app)

# MongoDB connection
try:
    client = MongoClient('mongodb://localhost:27017/')
    db = client['codetracker']
    client.admin.command('ping')
    print("✅ Connected to MongoDB")
except Exception as e:
    print(f"❌ MongoDB connection failed: {e}")
    exit(1)

# Collections
assignments_collection = db['assignments']
students_collection = db['students']
submissions_collection = db['submissions']
reviews_collection = db['reviews']
analysis_results_collection = db['analysis_results']

def clean_error_message(error_line):
    """Remove file paths and clean up error messages"""
    # Pattern to match: filename:line:column: error/warning: message
    match = re.search(r':(\d+):(\d+):\s+(error|warning):\s+(.*)$', error_line, re.IGNORECASE)
    
    if match:
        line_num = match.group(1)
        msg_type = match.group(3)
        message = match.group(4)
        
        return {
            'line': int(line_num),
            'type': msg_type.lower(),
            'message': message.strip()
        }
    else:
        # Try without column number
        match2 = re.search(r':(\d+):\s+(error|warning):\s+(.*)$', error_line, re.IGNORECASE)
        if match2:
            line_num = match2.group(1)
            msg_type = match2.group(2)
            message = match2.group(3)
            
            return {
                'line': int(line_num),
                'type': msg_type.lower(),
                'message': message.strip()
            }
        else:
            # Just extract the error/warning message
            if 'error:' in error_line.lower():
                parts = error_line.lower().split('error:')
                return {
                    'line': 0,
                    'type': 'error',
                    'message': parts[-1].strip()
                }
            elif 'warning:' in error_line.lower():
                parts = error_line.lower().split('warning:')
                return {
                    'line': 0,
                    'type': 'warning',
                    'message': parts[-1].strip()
                }
            else:
                return {
                    'line': 0,
                    'type': 'info',
                    'message': error_line.strip()
                }

@app.route('/api/assignments/<student_id>', methods=['GET'])
def get_student_assignments(student_id):
    """Get all assignments for a student"""
    try:
        # Check if student exists
        student = students_collection.find_one({"student_id": student_id})
        if not student:
            student = {
                "student_id": student_id,
                "name": "Dexter Facelo",
                "email": "dexter.facelo@student.edu",
                "year": 3,
                "course": "Computer Science"
            }
            students_collection.insert_one(student)
        
        # Get all assignments
        assignments = list(assignments_collection.find({}))
        
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
                "status": "pending",
                "grade": None
            }
            
            if submission:
                assignment_data["status"] = submission.get("status", "pending")
                assignment_data["submission_id"] = str(submission["_id"])
                
                # Get review to check for grade
                review = reviews_collection.find_one({"submission_id": submission["_id"]})
                if review:
                    assignment_data["grade"] = review.get("grade")
                
                # Get analysis results
                analysis_results = list(analysis_results_collection.find({
                    "submission_id": submission["_id"]
                }))
                
                total_errors = 0
                total_warnings = 0
                for res in analysis_results:
                    total_errors += len(res.get("errors", []))
                    total_warnings += len(res.get("warnings", []))
                
                assignment_data["errors_count"] = total_errors
                assignment_data["warnings_count"] = total_warnings
                assignment_data["total_files"] = len(analysis_results)
            
            result.append(assignment_data)
        
        return app.response_class(
            response=json.dumps({"success": True, "assignments": result}, cls=JSONEncoder),
            status=200,
            mimetype='application/json'
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        client.admin.command('ping')
        assignments_count = assignments_collection.count_documents({})
        return jsonify({
            'status': 'healthy',
            'mongodb': 'connected',
            'assignments': assignments_count,
            'timestamp': datetime.utcnow().isoformat()
        })
    except Exception as e:
        return jsonify({'status': 'unhealthy', 'error': str(e)}), 500

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
        print(f"❌ Error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/save-grade', methods=['POST'])
def save_grade():
    """Save grade for a submission"""
    try:
        data = request.json
        submission_id = data.get('submission_id')
        grade = data.get('grade')
        
        if not submission_id:
            return jsonify({'success': False, 'error': 'Submission ID required'}), 400
        
        if grade is None or not isinstance(grade, (int, float)) or grade < 0 or grade > 100:
            return jsonify({'success': False, 'error': 'Grade must be a number between 0 and 100'}), 400
        
        # Check if submission exists
        submission = submissions_collection.find_one({'_id': submission_id})
        if not submission:
            return jsonify({'success': False, 'error': 'Submission not found'}), 404
        
        # Find or create review
        review = reviews_collection.find_one({'submission_id': submission_id})
        
        if review:
            # Update existing review
            reviews_collection.update_one(
                {'submission_id': submission_id},
                {'$set': {
                    'grade': grade,
                    'updated_at': datetime.utcnow()
                }}
            )
            print(f"✅ Updated grade for submission {submission_id}: {grade}")
        else:
            # Create new review
            review_id = str(uuid.uuid4())
            review = {
                '_id': review_id,
                'submission_id': submission_id,
                'grade': grade,
                'feedback': '',
                'status': 'pending',
                'created_at': datetime.utcnow(),
                'updated_at': datetime.utcnow()
            }
            reviews_collection.insert_one(review)
            print(f"✅ Created new review with grade for submission {submission_id}: {grade}")
        
        return jsonify({
            'success': True,
            'message': f'Grade {grade} saved successfully'
        })
        
    except Exception as e:
        print(f"❌ Error saving grade: {e}")
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
        
        # Convert ObjectId to string
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
        print(f"❌ Error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/files/<submission_id>', methods=['GET'])
def get_files(submission_id):
    """Get list of analyzed files"""
    try:
        files = list(analysis_results_collection.find(
            {'submission_id': submission_id},
            {
                'file_path': 1, 
                'file_name': 1, 
                'language': 1, 
                'status': 1, 
                'errors': 1, 
                'warnings': 1,
                'content': 1
            }
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
        print(f"❌ Error: {e}")
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
        
        # Check if submission exists
        submission = submissions_collection.find_one({'_id': submission_id})
        if not submission:
            return jsonify({'success': False, 'error': 'Submission not found'}), 404
        
        # Check if review already exists
        existing_review = reviews_collection.find_one({'submission_id': submission_id})
        
        if existing_review:
            # Update existing review
            reviews_collection.update_one(
                {'submission_id': submission_id},
                {'$set': {
                    'feedback': feedback,
                    'reviewer_id': reviewer_id,
                    'status': 'completed',
                    'completed_at': datetime.utcnow()
                }}
            )
            review_id = existing_review['_id']
            print(f"✅ Updated feedback for submission {submission_id}")
        else:
            # Create new review
            review_id = str(uuid.uuid4())
            review = {
                '_id': review_id,
                'submission_id': submission_id,
                'reviewer_id': reviewer_id,
                'feedback': feedback,
                'status': 'completed',
                'created_at': datetime.utcnow(),
                'completed_at': datetime.utcnow()
            }
            reviews_collection.insert_one(review)
            print(f"✅ Created new review for submission {submission_id}")
        
        # Update submission status
        submissions_collection.update_one(
            {'_id': submission_id},
            {'$set': {'status': 'reviewed'}}
        )
        
        return jsonify({
            'success': True,
            'message': 'Feedback saved successfully',
            'review_id': str(review_id)
        })
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

def analyze_repository_background(submission_id, repo_url, branch):
    """Background task for repository analysis - Gets ALL files content"""
    temp_dir = None
    try:
        # Create temp directory
        temp_dir = tempfile.mkdtemp()
        print(f"📦 Cloning {repo_url} to {temp_dir}")
        
        # Clone repository
        Repo.clone_from(repo_url, temp_dir, branch=branch, depth=1)
        
        # Find ALL files in the repository
        all_files = []
        
        for root, dirs, files in os.walk(temp_dir):
            # Skip hidden directories and .git
            dirs[:] = [d for d in dirs if not d.startswith('.') and d != '.git' and d != '__pycache__']
            
            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, temp_dir)
                
                # Determine language based on file extension
                language = 'unknown'
                ext = os.path.splitext(file)[1].lower()
                
                # C/C++ files
                if ext in ['.c']:
                    language = 'c'
                elif ext in ['.cpp', '.cc', '.cxx']:
                    language = 'cpp'
                elif ext in ['.h', '.hpp']:
                    language = 'header'
                
                # Other common languages
                elif ext in ['.py']:
                    language = 'python'
                elif ext in ['.js']:
                    language = 'javascript'
                elif ext in ['.html', '.htm']:
                    language = 'html'
                elif ext in ['.css']:
                    language = 'css'
                elif ext in ['.md']:
                    language = 'markdown'
                elif ext in ['.txt']:
                    language = 'text'
                elif ext in ['.json']:
                    language = 'json'
                elif ext in ['.xml']:
                    language = 'xml'
                elif ext in ['.yml', '.yaml']:
                    language = 'yaml'
                elif ext in ['.sh']:
                    language = 'shell'
                elif ext in ['.bat', '.cmd']:
                    language = 'batch'
                elif ext in ['.java']:
                    language = 'java'
                elif ext in ['.rb']:
                    language = 'ruby'
                elif ext in ['.php']:
                    language = 'php'
                elif ext in ['.go']:
                    language = 'go'
                elif ext in ['.rs']:
                    language = 'rust'
                elif ext in ['.swift']:
                    language = 'swift'
                elif ext in ['.kt', '.kts']:
                    language = 'kotlin'
                elif ext in ['.sql']:
                    language = 'sql'
                elif ext in ['.r']:
                    language = 'r'
                elif ext in ['.m']:
                    language = 'matlab'
                elif ext in ['.pl']:
                    language = 'perl'
                elif ext in ['.lua']:
                    language = 'lua'
                elif ext in ['.dart']:
                    language = 'dart'
                elif ext in ['.scala']:
                    language = 'scala'
                
                all_files.append((file_path, rel_path, language, file))
        
        # Update submission with total files
        submissions_collection.update_one(
            {'_id': submission_id},
            {'$set': {
                'total_files': len(all_files),
                'status': 'analyzing'
            }}
        )
        
        print(f"🔍 Found {len(all_files)} total files to process")
        print(f"📁 Repository: {repo_url}")
        
        # Process each file - ALWAYS read and store content
        total_errors = 0
        total_warnings = 0
        processed_count = 0
        
        for file_path, rel_path, language, file_name in all_files:
            try:
                # ALWAYS read file content for EVERY file
                content = ""
                file_size = os.path.getsize(file_path)
                
                # Try to read as text if file is not too large
                if file_size < 10 * 1024 * 1024:  # Skip files larger than 10MB
                    try:
                        # Try multiple encodings
                        encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1', 'ascii']
                        for encoding in encodings:
                            try:
                                with open(file_path, 'r', encoding=encoding) as f:
                                    content = f.read()
                                break
                            except (UnicodeDecodeError, LookupError):
                                continue
                        else:
                            # If all text encodings fail, try reading as binary and decode with errors='ignore'
                            try:
                                with open(file_path, 'rb') as f:
                                    content = f.read().decode('utf-8', errors='ignore')
                            except:
                                content = f"// Binary file: {file_name}\n// This file appears to be binary and cannot be displayed as text."
                    except Exception as e:
                        content = f"// Error reading file: {str(e)}"
                else:
                    content = f"// File too large: {file_size} bytes\n// This file exceeds the size limit for display."
                
                # Analyze only C/C++ files for errors/warnings
                errors = []
                warnings = []
                
                if language in ['c', 'cpp']:
                    # Compile command
                    if language == 'c':
                        cmd = ['gcc', '-fsyntax-only', '-Wall', '-Wextra', '-std=c11', file_path]
                    else:
                        cmd = ['g++', '-fsyntax-only', '-Wall', '-Wextra', '-std=c++14', file_path]
                    
                    try:
                        # Run compilation
                        process = subprocess.run(
                            cmd,
                            capture_output=True,
                            text=True,
                            timeout=30
                        )
                        
                        # Parse errors and warnings
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
                            elif cleaned['type'] == 'warning':
                                warnings.append({
                                    'line': cleaned['line'],
                                    'message': cleaned['message'],
                                    'type': 'warning'
                                })
                        
                    except subprocess.TimeoutExpired:
                        errors.append({
                            'line': 0,
                            'message': 'Compilation timeout',
                            'type': 'error'
                        })
                    except FileNotFoundError:
                        errors.append({
                            'line': 0,
                            'message': f'Compiler not found. Please install {"gcc" if language=="c" else "g++"}.',
                            'type': 'error'
                        })
                    except Exception as e:
                        errors.append({
                            'line': 0,
                            'message': f'Analysis error: {str(e)}',
                            'type': 'error'
                        })
                
                # Store result with file content for EVERY file
                result = {
                    'submission_id': submission_id,
                    'file_path': rel_path.replace('\\', '/'),  # Normalize path separators
                    'file_name': file_name,
                    'language': language,
                    'status': 'analyzed',
                    'errors': errors,
                    'warnings': warnings,
                    'content': content,  # ALWAYS store the content
                    'analyzed_at': datetime.utcnow(),
                    'passed': len(errors) == 0,
                    'file_size': file_size
                }
                
                # Insert into database
                analysis_results_collection.insert_one(result)
                
                total_errors += len(errors)
                total_warnings += len(warnings)
                processed_count += 1
                
                # Update progress every 5 files
                if processed_count % 5 == 0:
                    submissions_collection.update_one(
                        {'_id': submission_id},
                        {'$set': {
                            'analyzed_files': processed_count,
                            'errors_count': total_errors,
                            'warnings_count': total_warnings
                        }}
                    )
                    print(f"📊 Progress: {processed_count}/{len(all_files)} files processed")
                
                # Status icon based on issues
                if errors:
                    status_icon = "❌"
                elif warnings:
                    status_icon = "⚠️"
                else:
                    status_icon = "✅"
                    
                print(f"{status_icon} Processed: {rel_path} - Lang: {language}, Size: {file_size} bytes")
                
            except Exception as e:
                print(f"❌ Error processing {rel_path}: {e}")
                # Still store the file with error message
                result = {
                    'submission_id': submission_id,
                    'file_path': rel_path.replace('\\', '/'),
                    'file_name': file_name,
                    'language': language,
                    'status': 'failed',
                    'errors': [{'line': 0, 'message': f'Processing error: {str(e)}', 'type': 'error'}],
                    'warnings': [],
                    'content': f"// Error processing file: {str(e)}",
                    'analyzed_at': datetime.utcnow(),
                    'passed': False,
                    'file_size': 0
                }
                analysis_results_collection.insert_one(result)
                total_errors += 1
                processed_count += 1
        
        # Final update with complete stats
        submissions_collection.update_one(
            {'_id': submission_id},
            {'$set': {
                'status': 'completed',
                'completed_at': datetime.utcnow(),
                'analyzed_files': processed_count,
                'errors_count': total_errors,
                'warnings_count': total_warnings
            }}
        )
        
        print(f"\n{'='*50}")
        print(f"✅ Analysis complete for {submission_id}")
        print(f"{'='*50}")
        print(f"📊 SUMMARY:")
        print(f"   Total files: {len(all_files)}")
        print(f"   Successfully processed: {processed_count}")
        print(f"   Total errors: {total_errors}")
        print(f"   Total warnings: {total_warnings}")
        
        # Print summary by language
        lang_stats = {}
        for file_path, rel_path, language, file_name in all_files:
            lang_stats[language] = lang_stats.get(language, 0) + 1
        
        print(f"\n📁 Files by language:")
        for lang, count in sorted(lang_stats.items(), key=lambda x: x[1], reverse=True):
            print(f"   {lang}: {count}")
        
        # Print C/C++ files with issues
        print(f"\n🔍 C/C++ Files with issues:")
        c_files = analysis_results_collection.find({
            'submission_id': submission_id,
            'language': {'$in': ['c', 'cpp']},
            '$or': [
                {'errors': {'$ne': []}},
                {'warnings': {'$ne': []}}
            ]
        })
        
        for file in c_files:
            print(f"   📄 {file['file_name']}: {len(file['errors'])} errors, {len(file['warnings'])} warnings")
        
        print(f"{'='*50}")
        
    except Exception as e:
        print(f"❌ Background analysis failed: {e}")
        submissions_collection.update_one(
            {'_id': submission_id},
            {'$set': {'status': 'failed', 'error': str(e)}}
        )
    finally:
        # Clean up temp directory
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
            print(f"🧹 Cleaned up temporary directory: {temp_dir}")

@app.route('/', methods=['GET'])
def home():
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
            '/api/save-feedback',
            '/api/save-grade'
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
            print(f"   • {a['title']} - {a['repo_url']}")
    
    print(f"🌐 Server running on: http://localhost:5500")
    print("=" * 60)
    
    app.run(debug=True, port=5500, host='0.0.0.0')