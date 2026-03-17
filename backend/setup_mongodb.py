# setup_mongodb.py
from pymongo import MongoClient
from datetime import datetime

# Connect to MongoDB
client = MongoClient('mongodb://localhost:27017/')
db = client['codetracker']

# Clear existing data
db.assignments.delete_many({})
db.students.delete_many({})

# Create assignments collection with the repositories
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
        "created_at": datetime.utcnow()
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
        "created_at": datetime.utcnow()
    }
]

# Insert assignments
db.assignments.insert_many(assignments)

# Create student
student = {
    "student_id": "student123",
    "name": "Dexter Facelo",
    "email": "dexter.facelo@student.edu",
    "year": 3,
    "course": "Computer Science"
}
db.students.update_one(
    {"student_id": "student123"},
    {"$set": student},
    upsert=True
)

print("✅ MongoDB setup complete!")
print(f"📚 Added {len(assignments)} assignments:")
for a in assignments:
    print(f"   - {a['title']}: {a['repo_url']}")    