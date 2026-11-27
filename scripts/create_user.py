"""Provision an account from the server console without a default password."""
import argparse
import sqlite3
from getpass import getpass
from app.db import allocate_user_id, connect, initialize
from app.services.security import hash_password
from app.services.password_vault import encrypt_password
from app.services.credits import ADMIN_CREDITS
from app.services import points


def main():
    parser = argparse.ArgumentParser(description='创建账号；所有启用账号均可使用面试与上机系统')
    parser.add_argument('username')
    parser.add_argument('--admin', action='store_true', help='授予后台管理权限')
    args = parser.parse_args()
    password = getpass('Password: ')
    if not args.username or not password:
        parser.error('Username and password are required')
    initialize()
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            uid = db.execute('INSERT INTO users(id,username,password,password_ciphertext,is_admin,interview_credits) VALUES (?,?,?,?,?,?)',
                (allocate_user_id(db), args.username, hash_password(password), encrypt_password(password), args.admin,
                 ADMIN_CREDITS if args.admin else 0)).lastrowid
            if not args.admin:
                points.adjust(db, uid, points.default_points(db), kind='initial')
        except sqlite3.IntegrityError:
            parser.error('Username already exists')
    print('User created')


if __name__ == '__main__':
    main()
