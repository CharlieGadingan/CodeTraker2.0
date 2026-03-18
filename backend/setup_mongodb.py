# setup_mongodb.py
from pymongo import MongoClient
from datetime import datetime

def setup_database():
    """Setup MongoDB database with initial data - avoids duplicates"""
    
    # Connect to MongoDB
    client = MongoClient('mongodb://localhost:27017/')
    db = client['codetracker']
    
    print("=" * 60)
    print("🚀 CodeTracker Database Setup")
    print("=" * 60)
    
    # Check current counts
    print(f"\n📊 Current database stats:")
    print(f"   Assignments: {db.assignments.count_documents({})}")
    print(f"   Students: {db.students.count_documents({})}")
    print(f"   Submissions: {db.submissions.count_documents({})}")
    print(f"   Reviews: {db.reviews.count_documents({})}")
    print(f"   Analysis Results: {db.analysis_results.count_documents({})}")
    
    # Create assignments with upsert (update or insert)
    print("\n📚 Setting up assignments...")
    
    assignments = [
        {
            "assignment_id": "c_language_basics",
            "title": "C Language Basics",
            "description": "Basic C programming exercises including loops, functions, and arrays",
            "due_date": "March 10, 2026",
            "difficulty": "Medium",
            "language": "C",
            "repo_url": "https://github.com/CharlieGadingan/clanguage.git",
            "branch": "main",
            "updated_at": datetime.utcnow()
        },
        {
            "assignment_id": "cpp_programming",
            "title": "C++ Programming Fundamentals",
            "description": "Object-oriented programming with C++ including classes and inheritance",
            "due_date": "March 24, 2026",
            "difficulty": "Hard",
            "language": "C++",
            "repo_url": "https://github.com/CharlieGadingan/cpp.git",
            "branch": "main",
            "updated_at": datetime.utcnow()
        }
    ]
    
    for assignment in assignments:
        # Check if assignment already exists
        existing = db.assignments.find_one({"assignment_id": assignment["assignment_id"]})
        
        if existing:
            # Update existing assignment
            db.assignments.update_one(
                {"assignment_id": assignment["assignment_id"]},
                {"$set": {
                    "title": assignment["title"],
                    "description": assignment["description"],
                    "due_date": assignment["due_date"],
                    "difficulty": assignment["difficulty"],
                    "language": assignment["language"],
                    "repo_url": assignment["repo_url"],
                    "branch": assignment["branch"],
                    "updated_at": datetime.utcnow()
                }}
            )
            print(f"   🔄 Updated: {assignment['title']}")
        else:
            # Insert new assignment with created_at
            assignment["created_at"] = datetime.utcnow()
            db.assignments.insert_one(assignment)
            print(f"   ✅ Created: {assignment['title']}")
    
    # Create student with upsert
    print("\n👤 Setting up student profile...")
    
    student = {
        "student_id": "student123",
        "name": "Dexter Facelo",
        "email": "dexter.facelo@student.edu",
        "year": 3,
        "course": "Computer Science",
        "updated_at": datetime.utcnow()
    }
    
    existing_student = db.students.find_one({"student_id": "student123"})
    if existing_student:
        db.students.update_one(
            {"student_id": "student123"},
            {"$set": student}
        )
        print("   🔄 Updated existing student")
    else:
        student["created_at"] = datetime.utcnow()
        db.students.insert_one(student)
        print("   ✅ Created new student")
    
    # Show final stats
    print(f"\n📊 Final database stats:")
    print(f"   Assignments: {db.assignments.count_documents({})}")
    print(f"   Students: {db.students.count_documents({})}")
    print(f"   Submissions: {db.submissions.count_documents({})}")
    print(f"   Reviews: {db.reviews.count_documents({})}")
    print(f"   Analysis Results: {db.analysis_results.count_documents({})}")
    
    # List all assignments
    print("\n📋 Assignments in database:")
    for assignment in db.assignments.find().sort("title", 1):
        created = assignment.get("created_at", "unknown")
        if isinstance(created, datetime):
            created = created.strftime("%Y-%m-%d")
        print(f"   • {assignment['title']} (ID: {assignment['assignment_id']})")
        print(f"     Repo: {assignment['repo_url']}")
        print(f"     Created: {created}")
        print()
    
    print("=" * 60)
    print("✅ Database setup complete!")
    print("=" * 60)

if __name__ == "__main__":
    setup_database()