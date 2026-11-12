import argparse
from getpass import getpass
from app.db import connect, initialize
from app.services.security import hash_password

p = argparse.ArgumentParser()
p.add_argument('username')
p.add_argument('--role', choices=['teacher', 'student'], default='student')
a = p.parse_args()
password = getpass('Password: ')
if len(password) < 8:
    raise SystemExit('Password must have at least 8 characters')
initialize()
with connect() as db:
    db.execute('INSERT INTO users(username,password,role) VALUES (?,?,?)', (a.username, hash_password(password), a.role))
print('User created')
