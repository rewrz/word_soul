import os
import secrets
import subprocess
import sys

def run_command(command):
    """运行一个shell命令并返回其输出"""
    try:
        print(f"正在执行: {' '.join(command)}")
        # 使用 text=True 和 utf-8 编码来避免在 Windows 上出现编码问题
        result = subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8')
        # 打印命令的输出，方便调试
        if result.stdout:
            print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"命令执行失败: {' '.join(command)}")
        print(f"错误信息:\n{e.stderr}")
        return False
    except FileNotFoundError:
        print(f"错误: 找不到命令 '{command[0]}'. 请确保 flask 已安装并位于您的PATH中。")
        return False

def setup_environment():
    """配置项目的运行环境"""
    env_file = '.env'
    if not os.path.exists(env_file):
        print(f"未找到 .env 文件，正在创建...")
        secret_key = secrets.token_hex(32)
        jwt_secret_key = secrets.token_hex(32)
        with open(env_file, 'w', encoding='utf-8') as f:
            f.write(f"# --- Flask App Configuration ---\n")
            f.write(f"SECRET_KEY='{secret_key}'\n")
            f.write(f"JWT_SECRET_KEY='{jwt_secret_key}'\n\n")
            f.write(f"# --- AI Provider Configuration ---\n")
            f.write(f"# 选择一个提供商 (Choose one provider): openai, gemini, claude, local_openai\n")
            f.write(f"AI_PROVIDER='local_openai'\n\n")
            f.write(f"# --- API Keys & Endpoints ---\n")
            f.write(f"# 根据你选择的提供商，填写对应的密钥和URL\n")
            f.write(f"OPENAI_API_KEY=''\n")
            f.write(f"# 如果使用本地模型或代理，请设置此项\n")
            f.write(f"OPENAI_API_BASE_URL='http://localhost:1234/v1'\n")
            f.write(f"GEMINI_API_KEY=''\n")
            f.write(f"CLAUDE_API_KEY=''\n")
        print("已成功生成 .env 文件并写入密钥和AI配置占位符。")
    else:
        print(".env 文件已存在，将跳过创建。")

    print("\n正在检查数据库迁移环境...")
    # Flask-Migrate 默认的目录就是 'migrations'
    migrations_dir = 'migrations'
    if not os.path.exists(migrations_dir):
        print(f"未找到 '{migrations_dir}' 目录，正在初始化 Alembic...")
        if not run_command(['flask', 'db', 'init']):
            print("\n数据库迁移环境初始化失败。")
            sys.exit(1)

        print("\n正在生成初始迁移脚本...")
        # 首次执行 migrate 会根据当前 models 创建第一个迁移版本
        if not run_command(['flask', 'db', 'migrate', '-m', 'Initial database setup']):
            print("\n初始迁移脚本生成失败。")
            # 如果模型为空，这可能会失败，但对于一个新项目来说，这通常是必要的步骤。
            # 即使失败，后续的 upgrade 可能仍然可以工作（如果数据库是空的），但最好是停止。
            sys.exit(1)

    print("\n正在应用数据库迁移...")
    if run_command(['flask', 'db', 'upgrade']):
        print("数据库配置成功！")
    else:
        print("\n数据库配置失败。请检查上面的错误信息。")
        sys.exit(1)

if __name__ == '__main__':
    print("--- 开始配置《言灵》项目 ---")
    setup_environment()
    print("\n--- 项目配置完成！---")
    print("现在您可以运行 'flask run' 来启动开发服务器了。")
    print("对于生产环境，请考虑使用 Gunicorn 或 uWSGI 等生产级 WSGI 服务器。")