from datetime import datetime
from pymongo import MongoClient
from config import Config
import uuid

class MongoDB:
    def __init__(self):
        self.client = MongoClient(Config.MONGO_URI)
        self.db = self.client[Config.MONGO_DB]
        
        # Collections
        self.submissions = self.db.submissions
        self.reviews = self.db.reviews
        self.analysis_results = self.db.analysis_results
        self.repositories = self.db.repositories
        
        # Create indexes
        self.submissions.create_index([('student_id', 1), ('assignment_id', 1)])
        self.reviews.create_index([('submission_id', 1)])
        self.analysis_results.create_index([('submission_id', 1), ('file_path', 1)])

class Submission:
    @staticmethod
    def create(student_id, assignment_id, repo_url, branch='main'):
        submission_id = str(uuid.uuid4())
        submission = {
            '_id': submission_id,
            'student_id': student_id,
            'assignment_id': assignment_id,
            'repo_url': repo_url,
            'branch': branch,
            'status': 'pending',  # pending, analyzing, completed, failed
            'created_at': datetime.utcnow(),
            'completed_at': None,
            'total_files': 0,
            'analyzed_files': 0,
            'errors_count': 0,
            'warnings_count': 0
        }
        return submission

class Review:
    @staticmethod
    def create(submission_id, reviewer_id, feedback=''):
        review_id = str(uuid.uuid4())
        review = {
            '_id': review_id,
            'submission_id': submission_id,
            'reviewer_id': reviewer_id,
            'status': 'pending',  # pending, completed
            'feedback': feedback,
            'created_at': datetime.utcnow(),
            'completed_at': None,
            'overall_grade': None
        }
        return review

class AnalysisResult:
    @staticmethod
    def create(submission_id, file_path, file_name, language):
        result_id = str(uuid.uuid4())
        result = {
            '_id': result_id,
            'submission_id': submission_id,
            'file_path': file_path,
            'file_name': file_name,
            'language': language,
            'status': 'pending',  # pending, analyzed, failed
            'errors': [],
            'warnings': [],
            'compile_output': '',
            'analyzed_at': None,
            'passed': None
        }
        return result