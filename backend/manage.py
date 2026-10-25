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
    mcp = sub.add_parser('issue-mcp-token', help='为 DeepSeek Harness 等客户端生成长期 Bearer Token')
    mcp.add_argument('username')
    mcp.add_argument('--days', type=int, default=365, help='有效期天数，默认 365')
    sub.add_parser('revoke-mcp-token', help='吊销该账号的 MCP Token').add_argument('username')
    sub.add_parser('list-mcp-tokens', help='列出 MCP Token 的账号和到期时间')
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
    elif args.command == 'issue-mcp-token':
        base = os.getenv('PUBLIC_BASE_URL', '').rstrip('/')
        if not base.startswith('https://'):
            raise ValueError('需要配置 HTTPS 的 PUBLIC_BASE_URL')
        token = store.issue_mcp_token(args.username, base + '/mcp', args.days)
        print('MCP Token（只显示一次，请妥善保存）：')
        print(token)
        return
    elif args.command == 'revoke-mcp-token':
        count = store.revoke_mcp_token(args.username)
        print(f'已吊销 {count} 个 MCP Token。')
        return
    elif args.command == 'list-mcp-tokens':
        print(json.dumps(store.mcp_tokens(), ensure_ascii=False, indent=2))
        return
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
