from app import app
from models import db, User

def upgrade_user(username="admin"):
    with app.app_context():
        user = User.query.filter_by(username=username).first()
        if not user:
            print(f"❌ Error: User '{username}' not found.")
            return

        user.role = "admin"
        db.session.commit()
        print(f"🚀 Success! User '{username}' is now a Super Admin.")

if __name__ == "__main__":
    upgrade_user()
