"""Admin commands run on the server, never exposed as MCP tools."""
import argparse
import getpass
import json
import os
from pathlib import Path
import sqlite3

from .store import Store


def main():
    parser = argparse.ArgumentParser(description='管理在线搜索账号；不影响本地 Skill')
    parser.add_argument('--database', type=Path,
                        default=Path(os.getenv('DATABASE_PATH', 'backend/data/service.sqlite3')))
    sub = parser.add_subparsers(dest='command', required=True)
    add = sub.add_parser('add-user', help='创建账号，交互输入密码')
    add.add_argument('username')
    add.add_argument('--limit', type=int, default=int(os.getenv('DEFAULT_DAILY_LIMIT', '5')))
    add.add_argument('--admin', action='store_true', help='创建管理员')
    for name in ('disable-user', 'enable-user', 'reset-password'):
        sub.add_parser(name).add_argument('username')
    limit = sub.add_parser('set-limit')
    limit.add_argument('username')
    limit.add_argument('limit', type=int)
    sub.add_parser('list-users')
    sub.add_parser('cleanup', help='清理过期授权及旧结果')
    sub.add_parser('make-admin', help='将已有账号设为管理员').add_argument('username')
    args = parser.parse_args()
    store = Store(args.database)
    if args.command in ('add-user', 'reset-password'):
        password = getpass.getpass('新密码（至少 12 个字符，不显示）：')
        if password != getpass.getpass('再次输入：'):
            raise ValueError('两次密码不一致')
        if args.command == 'add-user':
            store.add_user(args.username, password, args.limit, is_admin=args.admin)
        else:
            store.change_user(args.username, password=password)
    elif args.command == 'list-users':
        print(json.dumps(store.users(), ensure_ascii=False, indent=2))
        return
    elif args.command == 'set-limit':
        store.change_user(args.username, limit=args.limit)
    elif args.command == 'cleanup':
        store.cleanup()
    elif args.command == 'make-admin':
        store.change_user(args.username, is_admin=True)
    else:
        store.change_user(args.username, enabled=args.command == 'enable-user')
    print('已完成。')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, sqlite3.IntegrityError) as exc:
        raise SystemExit('操作失败：' + str(exc))
